use std::path::{Path, PathBuf};

fn resolve_from_candidates(candidates: &[PathBuf], tool_name: &str, syz_dir: &Path) -> Result<PathBuf, String> {
    for candidate in candidates {
        if candidate.exists() {
            return Ok(candidate.clone());
        }
    }

    let checked = candidates
        .iter()
        .map(|candidate| candidate.display().to_string())
        .collect::<Vec<_>>()
        .join(" and ");
    Err(format!(
        "missing {} under {} (checked {})",
        tool_name,
        syz_dir.display(),
        checked
    ))
}

pub fn resolve_tool_path<P: AsRef<Path>>(syz_dir: P, tool_name: &str) -> Result<PathBuf, String> {
    let syz_dir = syz_dir.as_ref();
    let candidates = [
        syz_dir.join("bin").join(tool_name),
        syz_dir.join(tool_name),
    ];
    resolve_from_candidates(&candidates, tool_name, syz_dir)
}

pub fn resolve_executor_path<P: AsRef<Path>>(syz_dir: P, os: &str, arch: &str) -> Result<PathBuf, String> {
    let syz_dir = syz_dir.as_ref();
    let target_dir = format!("{}_{}", os, arch);
    let candidates = [
        syz_dir.join("bin").join(&target_dir).join("syz-executor"),
        syz_dir.join(&target_dir).join("syz-executor"),
    ];
    resolve_from_candidates(&candidates, "syz-executor", syz_dir)
}

#[cfg(test)]
mod tests {
    use super::{resolve_executor_path, resolve_tool_path};
    use std::{
        fs::{create_dir_all, remove_dir_all, write},
        path::PathBuf,
        time::{SystemTime, UNIX_EPOCH},
    };

    fn temp_case_dir(case_name: &str) -> PathBuf {
        let unique = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let path = std::env::temp_dir().join(format!("syz-path-test-{case_name}-{unique}"));
        create_dir_all(&path).unwrap();
        path
    }

    #[test]
    fn resolves_tools_from_syzkaller_root_layout() {
        let root = temp_case_dir("root");
        let bin_dir = root.join("bin");
        let target_dir = bin_dir.join("linux_arm64");
        create_dir_all(&target_dir).unwrap();
        write(bin_dir.join("syz-repro"), b"stub").unwrap();
        write(bin_dir.join("syz-symbolize"), b"stub").unwrap();
        write(target_dir.join("syz-executor"), b"stub").unwrap();

        assert_eq!(
            resolve_tool_path(&root, "syz-repro").unwrap(),
            bin_dir.join("syz-repro")
        );
        assert_eq!(
            resolve_executor_path(&root, "linux", "arm64").unwrap(),
            target_dir.join("syz-executor")
        );

        remove_dir_all(root).unwrap();
    }

    #[test]
    fn resolves_tools_from_direct_syz_bin_layout() {
        let root = temp_case_dir("direct");
        let target_dir = root.join("linux_arm64");
        create_dir_all(&target_dir).unwrap();
        write(root.join("syz-repro"), b"stub").unwrap();
        write(root.join("syz-symbolize"), b"stub").unwrap();
        write(target_dir.join("syz-executor"), b"stub").unwrap();

        assert_eq!(
            resolve_tool_path(&root, "syz-symbolize").unwrap(),
            root.join("syz-symbolize")
        );
        assert_eq!(
            resolve_executor_path(&root, "linux", "arm64").unwrap(),
            target_dir.join("syz-executor")
        );

        remove_dir_all(root).unwrap();
    }
}
