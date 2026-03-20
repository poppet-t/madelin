use crate::{syscall::SyscallId, target::Target};
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

pub fn weighted_syscalls(target: &Target) -> Option<Vec<(SyscallId, u64)>> {
    let bias = bridge_bias()?;
    let families: HashSet<String> = bias.focus_syscall_families.into_iter().collect();
    let mut weighted = Vec::new();
    for syscall in target.enabled_syscalls() {
        let name = syscall.name();
        let mut weight = 1_u64;
        for family in &families {
            if family == "openat$KVM" && name == "openat$KVM" {
                weight = weight.max(20);
            }
            if family != "openat$KVM" && name.contains(family) {
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
        if family == "openat$KVM" && name == "openat$KVM" {
            mult = mult.max(20);
        }
        if family != "openat$KVM" && name.contains(&family) {
            mult = mult.max(20);
        }
    }
    mult
}
