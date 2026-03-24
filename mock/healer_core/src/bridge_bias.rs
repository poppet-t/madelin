use crate::{prog::Call, syscall::SyscallId, target::Target};
use serde::Deserialize;
use std::{
    collections::HashSet,
    fs::read_to_string,
    path::Path,
    sync::{OnceLock, RwLock},
};

#[derive(Debug, Clone, Deserialize, Default)]
pub struct BridgeBiasConfig {
    #[serde(default)]
    pub candidate_id: String,
    #[serde(default)]
    pub focus_syscall_families: Vec<String>,
    #[serde(default)]
    pub preserve_prefix_len: usize,
    #[serde(default)]
    pub prefer_two_thread_schedule: bool,
    #[serde(default)]
    pub prefer_collide: bool,
    #[serde(default)]
    pub mutate_near_steps: Vec<String>,
    #[serde(default)]
    pub keep_ordering_edges: Vec<String>,
    #[serde(default)]
    pub stable_prefix_resources: Vec<String>,
}

static GLOBAL_BIAS: OnceLock<RwLock<Option<BridgeBiasConfig>>> = OnceLock::new();

fn global_bias() -> &'static RwLock<Option<BridgeBiasConfig>> {
    GLOBAL_BIAS.get_or_init(|| RwLock::new(None))
}

pub fn load_bridge_bias(path: &Path) -> anyhow::Result<BridgeBiasConfig> {
    let content = read_to_string(path)?;
    let config: BridgeBiasConfig = serde_json::from_str(&content)?;
    Ok(config)
}

pub fn set_bridge_bias(config: Option<BridgeBiasConfig>) {
    let mut guard = global_bias().write().unwrap();
    *guard = config;
}

pub fn bridge_bias() -> Option<BridgeBiasConfig> {
    global_bias().read().unwrap().clone()
}

pub fn protected_prefix_len(call_count: usize) -> usize {
    bridge_bias()
        .map(|bias| bias.preserve_prefix_len.min(call_count))
        .unwrap_or(0)
}

fn family_matches_call_name(family: &str, call_name: &str) -> bool {
    if family == "openat$KVM" {
        call_name == "openat$KVM"
    } else {
        call_name.contains(family)
    }
}

pub fn protected_structural_len_for_names(call_names: &[&str]) -> usize {
    let Some(bias) = bridge_bias() else {
        return 0;
    };

    let prefix_len = bias.preserve_prefix_len.min(call_names.len());
    if bias.keep_ordering_edges.is_empty() || bias.focus_syscall_families.is_empty() {
        return prefix_len;
    }

    let mut protected_len = prefix_len;
    for call_name in &call_names[prefix_len..] {
        if bias
            .focus_syscall_families
            .iter()
            .any(|family| family_matches_call_name(family, call_name))
        {
            protected_len += 1;
        } else {
            break;
        }
    }

    protected_len
}

pub fn protected_structural_len(target: &Target, calls: &[Call]) -> usize {
    let prefix_len = protected_prefix_len(calls.len());
    let Some(bias) = bridge_bias() else {
        return prefix_len;
    };
    if bias.keep_ordering_edges.is_empty() || bias.focus_syscall_families.is_empty() {
        return prefix_len;
    }

    let call_names: Vec<&str> = calls
        .iter()
        .map(|call| target.syscall_of(call.sid()).name())
        .collect();
    protected_structural_len_for_names(&call_names)
}

pub fn weighted_syscalls(target: &Target) -> Option<Vec<(SyscallId, u64)>> {
    let bias = bridge_bias()?;
    let families: HashSet<String> = bias.focus_syscall_families.into_iter().collect();
    let mut weighted = Vec::new();
    for syscall in target.enabled_syscalls() {
        let name = syscall.name();
        let mut weight = 1_u64;
        for family in &families {
            if family_matches_call_name(family, name) {
                weight = weight.max(20);
            }
        }
        if weight > 1 {
            weighted.push((syscall.id(), weight));
        }
    }
    if weighted.is_empty() {
        None
    } else {
        Some(weighted)
    }
}

pub fn syscall_bias_multiplier(target: &Target, sid: SyscallId) -> u64 {
    let Some(bias) = bridge_bias() else {
        return 1;
    };
    let name = target.syscall_of(sid).name();
    let mut mult = 1_u64;
    for family in bias.focus_syscall_families {
        if family_matches_call_name(&family, name) {
            mult = mult.max(20);
        }
    }
    mult
}

#[cfg(test)]
mod tests {
    use super::{protected_structural_len_for_names, set_bridge_bias, BridgeBiasConfig};
    use std::sync::{Mutex, OnceLock};

    fn bias_lock() -> &'static Mutex<()> {
        static LOCK: OnceLock<Mutex<()>> = OnceLock::new();
        LOCK.get_or_init(|| Mutex::new(()))
    }

    #[test]
    fn structural_protection_extends_over_leading_focus_calls() {
        let _guard = bias_lock().lock().unwrap();
        set_bridge_bias(Some(BridgeBiasConfig {
            preserve_prefix_len: 3,
            focus_syscall_families: vec![
                "openat$KVM".to_string(),
                "KVM_CREATE_VM".to_string(),
                "KVM_CREATE_VCPU".to_string(),
                "KVM_ARM_VCPU_INIT".to_string(),
                "KVM_RUN".to_string(),
            ],
            keep_ordering_edges: vec!["free->use".to_string()],
            ..BridgeBiasConfig::default()
        }));

        let call_names = [
            "openat$KVM",
            "ioctl$KVM_CREATE_VM",
            "ioctl$KVM_CREATE_VCPU",
            "ioctl$KVM_ARM_VCPU_INIT",
            "ioctl$KVM_RUN",
            "close",
        ];
        assert_eq!(protected_structural_len_for_names(&call_names), 5);

        set_bridge_bias(None);
    }

    #[test]
    fn structural_protection_falls_back_to_prefix_without_ordering_edges() {
        let _guard = bias_lock().lock().unwrap();
        set_bridge_bias(Some(BridgeBiasConfig {
            preserve_prefix_len: 3,
            focus_syscall_families: vec!["KVM_RUN".to_string()],
            ..BridgeBiasConfig::default()
        }));

        let call_names = [
            "openat$KVM",
            "ioctl$KVM_CREATE_VM",
            "ioctl$KVM_CREATE_VCPU",
            "ioctl$KVM_RUN",
        ];
        assert_eq!(protected_structural_len_for_names(&call_names), 3);

        set_bridge_bias(None);
    }
}
