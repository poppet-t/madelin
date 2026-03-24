//! Syz-wrapper build script.
//!
//! This build script downloads, patches and builds Syzkaller.
//! The Syzlang description will be dump to json files in `OUT_DIR/sys/json`.
//! All the json format syscall descriptions will be included to source code
//! with `include_str!` macro (see `sys/mod.rs`), so that Healer can load them
//! without further manual efforts.
//! One can also skip this process and provide their own build via some extra env vars.
use std::{
    env,
    fs::{copy, create_dir, read_dir, remove_file, File},
    io::ErrorKind,
    path::{Path, PathBuf},
    process::{exit, Command},
};

/// Revision that the patches can be applied stably.
const STABLE_REVISION: &str = "169724fe58e8d7d0b4be6f59ca7c1e0f300399e1";
const STABLE_CSUM: &str = "293a65f4604dce1103ca94746fec6bb175229576271ffdcd319747cc33db2b89f5467acea86a2bf8b38c0fc95adea3c0";

fn main() {
    if env::var("SKIP_SYZ_BUILD").is_err() {
        check_env();
        fail_fast_if_host_cannot_build_arm64_executor();
        // TODO We cannot use the latest syz-executor any more, because `a7ce77be27d8e3728b97122a005bc5b23298cfc3` contains breaking change
        // Try to patch the latest revision first
        // const LATEST_REVISION: &str = "master";
        // let syz_dir = download(LATEST_REVISION, None);
        // if let Some(sys_dir) = build_syz(syz_dir) {
        // copy_sys(sys_dir);
        // } else {
        eprintln!("failed to patch and build latest revision, failback...");
        let syz_dir = download(STABLE_REVISION, Some(STABLE_CSUM));
        if let Some(sys_dir) = build_syz(syz_dir) {
            copy_sys(sys_dir);
            return;
        }
        eprintln!(
            "failed to build and patch Syzkaller with stable revision ({})",
            STABLE_REVISION
        );
        exit(1)
        // }
    } else if let Ok(sys_dir) = env::var("SYZ_SYS_DIR") {
        let sys_dir = PathBuf::from(sys_dir);
        copy_sys(sys_dir)
    } else {
        eprintln!("Directory that contains json format Syzlang description should be provided via `SYZ_SYS_DIR` env var, 
        when `SKIP_SYZ_BUILD` env var is set");
        exit(1)
    };
}

fn stable_syz_dir() -> PathBuf {
    let out_dir = env::var("OUT_DIR").unwrap();
    PathBuf::from(format!("{}/syzkaller-{}", out_dir, STABLE_REVISION))
}

fn has_tool(tool: &str) -> bool {
    Command::new("which")
        .arg(tool)
        .status()
        .map(|status| status.success())
        .unwrap_or(false)
}

/// Check required tool to build Syzkaller
fn check_env() {
    const TOOLS: [(&str, &str); 5] = [
        ("sha384sum", "check download"),
        ("unzip", "unzip syzkaller.zip"),
        ("patch", "patch patches/*.diff"),
        ("make", "build the syzkaller description and executor"),
        ("go", "build the syzkaller"),
    ];
    let mut missing = false;
    if !has_tool("wget") && !has_tool("curl") {
        eprintln!("missing tool wget or curl to download syzkaller.");
        missing = true;
    }
    for (tool, reason) in TOOLS.iter().copied() {
        if has_tool(tool) {
            continue;
        }
        eprintln!("missing tool {} to {}.", tool, reason);
        missing = true;
    }
    if missing {
        eprintln!("missing tools, please install them first");
        exit(1)
    }
}

fn download_syzkaller(repo_url: &str, syz_zip: &Path) {
    if has_tool("wget") {
        let wget = Command::new("wget")
            .arg("-O")
            .arg(syz_zip.to_str().unwrap())
            .arg(repo_url)
            .output()
            .unwrap_or_else(|e| {
                eprintln!("failed to spawn wget: {}", e);
                exit(1)
            });
        if !wget.status.success() {
            let stderr = String::from_utf8(wget.stderr).unwrap_or_default();
            eprintln!(
                "failed to download syzkaller from: {}, error: {}",
                repo_url, stderr
            );
            exit(1);
        }
        return;
    }

    let curl = Command::new("curl")
        .arg("--fail")
        .arg("--location")
        .arg("--silent")
        .arg("--show-error")
        .arg("-o")
        .arg(syz_zip.to_str().unwrap())
        .arg(repo_url)
        .output()
        .unwrap_or_else(|e| {
            eprintln!("failed to spawn curl: {}", e);
            exit(1)
        });
    if !curl.status.success() {
        let stderr = String::from_utf8(curl.stderr).unwrap_or_default();
        eprintln!(
            "failed to download syzkaller from: {}, error: {}",
            repo_url, stderr
        );
        exit(1);
    }
}

fn syz_runtime_layout_ready(syz_dir: &Path) -> bool {
    [
        syz_dir.join("bin").join("linux_arm64").join("syz-executor"),
        syz_dir.join("bin").join("syz-repro"),
        syz_dir.join("bin").join("syz-symbolize"),
        syz_dir.join("bin").join("syz-execprog"),
    ]
    .iter()
    .all(|path| path.is_file())
}

fn symlink_if_missing(from: &Path, to: &Path) {
    use std::os::unix::fs::symlink;

    if to.exists() {
        return;
    }
    if let Err(e) = symlink(from, to) {
        if e.kind() != ErrorKind::AlreadyExists {
            eprintln!(
                "failed to symlink {} -> {}: {}",
                to.display(),
                from.display(),
                e
            );
            exit(1);
        }
    }
}

fn make_syz_target(syz_dir: &Path, target: &str, target_os: Option<&str>, target_arch: Option<&str>) -> bool {
    let mut make = Command::new("make");
    make.current_dir(syz_dir.to_str().unwrap()).arg(target);
    if let Some(target_os) = target_os {
        make.env("TARGETOS", target_os);
    }
    if let Some(target_arch) = target_arch {
        make.env("TARGETARCH", target_arch);
        make.env("TARGETVMARCH", target_arch);
    }
    let output = make.output().unwrap_or_else(|e| {
        eprintln!("failed to spawn make: {}", e);
        exit(1);
    });
    if output.status.success() {
        return true;
    }
    let stderr = String::from_utf8(output.stderr).unwrap_or_default();
    eprintln!("failed to make {}: {}", target, stderr);
    false
}

fn ensure_runtime_entrypoints(syz_dir: &Path) {
    let bin_dir = syz_dir.join("bin");
    let target_dir = bin_dir.join("linux_arm64");
    let expected = [
        target_dir.join("syz-executor"),
        bin_dir.join("syz-execprog"),
        bin_dir.join("syz-repro"),
        bin_dir.join("syz-symbolize"),
    ];
    symlink_if_missing(
        Path::new("linux_arm64").join("syz-execprog").as_path(),
        &bin_dir.join("syz-execprog"),
    );
    let missing: Vec<PathBuf> = expected
        .iter()
        .filter(|path| !path.is_file())
        .cloned()
        .collect();
    if !missing.is_empty() {
        let missing_text = missing
            .iter()
            .map(|path| path.display().to_string())
            .collect::<Vec<_>>()
            .join(", ");
        if std::env::consts::OS == "macos" && !target_dir.join("syz-executor").is_file() {
            eprintln!(
                "linux/arm64 syz-executor is missing under {}. Building that executor is not supported on darwin hosts; use a Linux-built SYZ_DIR or run the build on Linux.",
                target_dir.display()
            );
        }
        eprintln!(
            "syzkaller build did not produce the required runtime layout under {}. missing: {}",
            bin_dir.display(),
            missing_text
        );
        exit(1);
    }
}

fn fail_fast_if_host_cannot_build_arm64_executor() {
    if std::env::consts::OS != "macos" {
        return;
    }

    let syz_dir = stable_syz_dir();
    if syz_runtime_layout_ready(&syz_dir) {
        return;
    }

    eprintln!(
        "darwin hosts cannot build the required linux/arm64 syz-executor locally for the arm64 KVM workflow. Use a Linux-built SYZ_DIR or run this build on Linux. If you already have generated syzkaller JSON descriptions, set SKIP_SYZ_BUILD=1 and SYZ_SYS_DIR=<path>."
    );
    exit(1);
}

fn apply_patch_if_needed(syz_dir: &Path, patch_file: &Path) -> bool {
    let forward = Command::new("patch")
        .current_dir(syz_dir.to_str().unwrap())
        .arg("--dry-run")
        .arg("-p1")
        .stdin(File::open(patch_file).unwrap())
        .output()
        .unwrap_or_else(|e| {
            eprintln!("failed to probe patch {}: {}", patch_file.display(), e);
            exit(1)
        });
    if forward.status.success() {
        let applied = Command::new("patch")
            .current_dir(syz_dir.to_str().unwrap())
            .arg("-p1")
            .stdin(File::open(patch_file).unwrap())
            .output()
            .unwrap_or_else(|e| {
                eprintln!("failed to spawn patch: {}", e);
                exit(1)
            });
        if applied.status.success() {
            return true;
        }
        let stderr = String::from_utf8(applied.stderr).unwrap_or_default();
        eprintln!("failde to patch {}: {}", patch_file.display(), stderr);
        return false;
    }

    let reversed = Command::new("patch")
        .current_dir(syz_dir.to_str().unwrap())
        .arg("-R")
        .arg("--dry-run")
        .arg("-p1")
        .stdin(File::open(patch_file).unwrap())
        .output()
        .unwrap_or_else(|e| {
            eprintln!("failed to probe reverse patch {}: {}", patch_file.display(), e);
            exit(1)
        });
    if reversed.status.success() {
        println!("patch already applied: {}", patch_file.display());
        return true;
    }

    let stderr = String::from_utf8(forward.stderr).unwrap_or_default();
    eprintln!("failde to patch {}: {}", patch_file.display(), stderr);
    false
}

fn download(syz_revision: &str, csum: Option<&str>) -> PathBuf {
    let repo_url = format!(
        "https://github.com/google/syzkaller/archive/{}.zip",
        syz_revision
    );
    let target = env::var("OUT_DIR").unwrap();
    let syz_zip = PathBuf::from(&format!("{}/syzkaller-{}.zip", target, syz_revision));
    let syz_dir = format!("{}/syzkaller-{}", target, syz_revision);
    let syz_dir = PathBuf::from(syz_dir);
    let mut need_unzip = true;

    if syz_dir.exists() {
        return syz_dir;
    }

    if syz_zip.exists() {
        let mut need_remove = false;
        if let Some(expected_csum) = csum {
            need_remove = !check_download_csum(&syz_zip, expected_csum);
        } else if try_unzip(&target, &syz_zip) {
            need_unzip = false;
        } else {
            need_remove = true;
        };

        if need_remove {
            remove_file(&syz_zip).unwrap_or_else(|e| {
                eprintln!(
                    "failed to removed broken file({}): {}",
                    syz_zip.display(),
                    e
                );
                exit(1);
            })
        }
    }

    if !syz_zip.exists() {
        println!("downloading syzkaller...");
        download_syzkaller(&repo_url, &syz_zip);
        if let Some(csum) = csum {
            if !check_download_csum(&syz_zip, csum) {
                eprintln!("downloaded file {} was broken", syz_zip.display());
                exit(1);
            }
        }
        println!("cargo:rerun-if-changed={}", syz_zip.display());
    }

    if need_unzip && !try_unzip(&target, &syz_zip) {
        eprintln!("failed to unzip the downloaded file: {}", syz_zip.display());
        exit(1);
    }

    assert!(syz_dir.exists());
    println!("cargo:rerun-if-changed={}", syz_dir.display());
    syz_dir
}

fn try_unzip<P: AsRef<Path>>(current_dir: &str, syz_zip: P) -> bool {
    let unzip = Command::new("unzip")
        .current_dir(current_dir)
        .arg(syz_zip.as_ref())
        .output()
        .unwrap_or_else(|e| {
            eprintln!("failed to spawn unzip: {}", e);
            exit(1)
        });
    unzip.status.success()
}

fn check_download_csum<P: AsRef<Path>>(syz_zip: P, expected_csum: &str) -> bool {
    let output = Command::new("sha384sum")
        .arg(syz_zip.as_ref())
        .output()
        .unwrap();
    if !output.status.success() {
        let stderr = String::from_utf8(output.stderr).unwrap_or_default();
        eprintln!("sha384sum failed: {}", stderr);
        exit(1)
    } else {
        let stdout = String::from_utf8(output.stdout).unwrap();
        let cksum = stdout.split(' ').next().unwrap();
        cksum.trim() == expected_csum
    }
}

fn build_syz(syz_dir: PathBuf) -> Option<PathBuf> {
    if !syz_runtime_layout_ready(&syz_dir) {
        let patch_dir = PathBuf::from("./patches");
        let headers = vec!["ivshm_setup.h", "features.h", "unix_sock_setup.h"];
        for header in headers {
            let to = format!("executor/{}", header);
            copy(patch_dir.join(&header), syz_dir.join(&to)).unwrap_or_else(|e| {
                eprintln!("failed to copy {} to {}: {}", header, to, e);
                exit(1)
            });
        }

        for f in read_dir(&patch_dir).unwrap().filter_map(|f| f.ok()) {
            let f = f.path();
            if let Some(ext) = f.extension() {
                if ext.to_str().unwrap() == "diff" {
                    let patch_file = syz_dir.join(f.file_name().unwrap());
                    copy(f, &patch_file).unwrap_or_else(|e| {
                        eprintln!(
                            "failed to copy patch file '{}': {}",
                            patch_file.display(),
                            e
                        );
                            exit(1)
                    });
                    if !apply_patch_if_needed(&syz_dir, &patch_file) {
                        return None;
                    }
                }
            }
        }

        for target in ["executor", "fuzzer", "execprog", "stress"] {
            if !make_syz_target(&syz_dir, target, Some("linux"), Some("arm64")) {
                return None;
            }
        }
        for target in ["repro", "symbolize"] {
            if !make_syz_target(&syz_dir, target, Some("linux"), Some("arm64")) {
                return None;
            }
        }
        ensure_runtime_entrypoints(&syz_dir);
        println!("cargo:rerun-if-changed={}", syz_dir.join("bin").display());
    }

    ensure_runtime_entrypoints(&syz_dir);
    copy_patched_syz_bin(&syz_dir);
    let sys_dir = syz_dir.join("sys").join("json");
    assert!(sys_dir.exists());
    println!("cargo:rerun-if-changed={}", sys_dir.display());
    Some(sys_dir)
}

fn copy_patched_syz_bin(syz_dir: &Path) {
    use std::os::unix::fs::symlink;

    let bin_dir = syz_dir.join("bin");
    if !bin_dir.exists() {
        eprintln!("executable files not exist: {}", syz_dir.display());
        exit(1);
    }
    // target/[debug/release]/build/syz-wrapper/out/..
    let out_dir = PathBuf::from(env::var("OUT_DIR").unwrap());
    let out_bin = out_dir
        .parent()
        .unwrap()
        .parent()
        .unwrap()
        .parent()
        .unwrap()
        .join("syz-bin");
    println!(
        "copy bin from {} to {}...",
        bin_dir.display(),
        out_bin.display()
    );
    if let Err(e) = symlink(&bin_dir, &out_bin) {
        if e.kind() != ErrorKind::AlreadyExists {
            eprintln!(
                "failed to hardlink bin dir from {} to {}: {}",
                bin_dir.display(),
                out_bin.display(),
                e
            );
            exit(1);
        }
    }
}

fn copy_sys(sys_dir: PathBuf) {
    let out_dir = PathBuf::from(env::var_os("OUT_DIR").unwrap());
    let out_sys = out_dir.join("sys");
    if let Err(e) = create_dir(&out_sys) {
        if e.kind() != ErrorKind::AlreadyExists {
            eprintln!("failed to create out sys dir: {}", e);
            exit(1)
        }
    }

    for f in read_dir(sys_dir).unwrap().filter_map(|f| f.ok()) {
        let p = f.path();
        if p.is_dir() {
            let out = out_sys.join(p.file_name().unwrap());
            if let Err(e) = create_dir(&out) {
                if e.kind() == ErrorKind::AlreadyExists {
                    continue;
                } else {
                    eprintln!("failed to create out os sys dir: {}", e);
                    exit(1)
                }
            }
            copy_dir_json(&p, &out)
        }
    }
    println!("cargo:rerun-if-changed={}", out_sys.display());
}

fn copy_dir_json<P: AsRef<Path>>(from: P, to: P) {
    for f in read_dir(from.as_ref()).unwrap().filter_map(|f| f.ok()) {
        let p = f.path();
        if let Some(ext) = p.extension() {
            if ext.to_str().unwrap() == "json" {
                let fname = p.file_name().unwrap();
                let to_fname = to.as_ref().join(fname);
                copy(&p, &to_fname).unwrap_or_else(|e| {
                    eprintln!(
                        "failed to copy from {} to {}: {}",
                        p.display(),
                        to_fname.display(),
                        e
                    );
                    exit(1)
                });
            }
        }
    }
}
