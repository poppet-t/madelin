# Syzkaller runtime proof

## What this document proves

Which syzkaller binary path is actually used by the Madelin backend, and that it is
not accidentally using a system-installed syzkaller.

---

## In-repo syzkaller tree

**Location**: `syzkaller/` (repo root)

**Type**: Complete upstream checkout — `https://github.com/google/syzkaller.git`

**Head commit** (as of audit): `aeea1c723`
`sys/linux: fix incorect initialization of io uring pointers`

**Modifications**: None — `git status` inside `syzkaller/` shows 0 dirty files.
This is a clean upstream reference checkout, not a fork.

**Built binaries**: None present in `syzkaller/bin/` — the tree is source-only.

---

## How the backend selects its syzkaller path

### Environment variable: `SYZ_DIR`

All scripts and the integration layer require `SYZ_DIR` to be explicitly set by
the operator before invoking any syzkaller-backed workflow.

**No script falls back to a system `syz-manager`** — if `SYZ_DIR` is unset, the
scripts either fail early or skip syzkaller invocation.

### Backend integration code

`backend/syz-guided/integration/syzkaller_runner.py`:

```python
def check_syz_available(syz_dir: pathlib.Path) -> dict:
    results = {}
    for binary in ["syz-manager", "syz-executor", "syz-execprog"]:
        path = syz_dir / "linux_arm64" / binary
        results[binary] = path.exists()
    return results
```

```python
def generate_syz_config(..., syz_dir: pathlib.Path | None = None, ...) -> dict:
    ...
    if syz_dir:
        config["syzkaller"] = str(syz_dir)
```

**Binary path layout expected**:
```
$SYZ_DIR/linux_arm64/syz-manager
$SYZ_DIR/linux_arm64/syz-executor
$SYZ_DIR/linux_arm64/syz-execprog
```

This matches the standard `make TARGETOS=linux TARGETARCH=arm64` syzkaller build
output layout.

---

## Known working run evidence

**Location**: `syzkaller-runtime-export/`

The preserved run config (`arm64-kvm-isolated.cfg`) shows:

```json
{
  "name": "arm64-kvm-isolated",
  "target": "linux/arm64",
  "syzkaller": "/home/charles/syzkaller",
  "type": "isolated",
  "vm": {
    "targets": ["127.0.0.1:10022"]
  }
}
```

**Interpretation**:
- The working run used a syzkaller at `/home/charles/syzkaller` on the original
  operator's Linux host — a separately built syzkaller tree.
- This is not the in-repo `syzkaller/` directory (which is source-only, no binaries).
- The operator built syzkaller locally and pointed `SYZ_DIR` (or hardcoded the path
  in the config) to that build.
- The in-repo `syzkaller/` tree is the reference source for reproducible builds.

**Runtime export artifacts prove**:
- Kernel used: `Image` (arm64, 148 MB)
- Disk image: `arm64-isolated-overlay.qcow2` (69 MB)
- SSH target: `root@127.0.0.1:10022`
- Seed filesystem: `seed.img` (374 KB)
- Checksums preserved: `SHA256SUMS.txt`

---

## How to reproduce: build syzkaller from in-repo source

```bash
cd syzkaller
make TARGETOS=linux TARGETARCH=arm64
# Produces: bin/linux_arm64/syz-manager, syz-executor, syz-execprog
export SYZ_DIR="$PWD/bin"
```

Then invoke the backend smoke path or full campaign:
```bash
# Smoke (no KVM required)
bash backend/syz-guided/scripts/smoke_seedgen.sh
bash backend/syz-guided/scripts/smoke_campaign.sh
bash backend/syz-guided/scripts/smoke_triage.sh

# Full run (requires KVM environment)
export SYZ_DIR=/path/to/built/syzkaller/bin
bash backend/syz-guided/scripts/run_kvm_candidate.sh <candidate_dir>
```

---

## Build verification (2026-04-01)

Built from `syzkaller/` source tree (`aeea1c723`) on macOS 26.3.1, Go 1.24.5:

```
GOOS=linux GOARCH=arm64 go build -o /tmp/syz-manager-linux-arm64 ./syz-manager/
  → ELF 64-bit, ARM aarch64, 72M
  → SHA-256: 433bd5c0eb2685c430a620f3d00c257b8abee65ad87602121e14c046ddb8d7cf

GOOS=darwin GOARCH=arm64 go build -o /tmp/syz-manager-darwin-arm64 ./syz-manager/
  → Mach-O, 76M ✓

GOOS=linux GOARCH=arm64 go build -o /tmp/syz-execprog-linux-arm64 ./tools/syz-execprog/
  → ELF 64-bit, ARM aarch64, 52M
  → SHA-256: 6750bb32c51e96757fdafb1bd8164faab51398ad7cbedb459aa37b841983ced3
```

The source tree builds cleanly without any patches.
syz-executor requires CGO cross-compilation and was not attempted.

---

## Old mock/ syzkaller vs new backend syzkaller

The deleted `mock/` directory built a **patched** syzkaller at commit
`169724fe58e8d7d0b4be6f59ca7c1e0f300399e1`. Those patches are preserved in the
Trash at:
`~/.Trash/mock/target/release/build/syz_wrapper-735a785e24c7dd02/out/syzkaller-169724fe.../`

Three patches were applied to the mock syzkaller:

| Diff | Purpose | Why no longer needed |
|------|---------|----------------------|
| `executor.diff` | Added IVSHM (inter-VM shared memory), Unix socket IPC, features check to executor.cc | IVSHM was for Healer corpus sharing; stock syz-manager handles corpus natively |
| `sysgen.diff` | Added JSON export of syscall descriptions (for ML language model trainer) | ML model manager is not part of the v1 backend |
| `targets.diff` | Added `json:"-"` tag on NeedSyscallDefine func to support JSON serialization | Not needed without sysgen JSON output |

The binaries built from the patched tree:
```
bin/linux_arm64/syz-execprog  (20M, linux/arm64 ELF)
bin/linux_arm64/syz-fuzzer    (20M, linux/arm64 ELF)
bin/linux_arm64/syz-stress    (20M, linux/arm64 ELF)
bin/syz-repro                 (93M, darwin/arm64 Mach-O — host binary)
bin/syz-execprog → linux_arm64/syz-execprog (symlink)
```

Note: `syz-manager` binary was NOT built in the mock path — the mock used
`syz-execprog` + Healer's own orchestration rather than syz-manager.

**The new `backend/syz-guided/` uses stock upstream syzkaller (no patches).**
This is the correct choice per AGENTS.md: "Prefer stock or lightly patched syzkaller
over deep forks."

---

## No system syzkaller is used

Evidence:
1. No script has an unconditional `syz-manager` call without `$SYZ_DIR`.
2. `syzkaller_runner.py` takes `syz_dir` as an explicit parameter (not env-lookup).
3. The preserved working run config uses an absolute path, not `PATH` lookup.
4. `check_syz_available()` checks absolute `syz_dir / "linux_arm64" / binary` — not `which syz-manager`.

---

## Summary

| Question | Answer |
|----------|--------|
| Is in-repo syzkaller modified? | No — clean upstream checkout at `aeea1c723` |
| Are built binaries in-repo? | No — operator must build from `syzkaller/` or supply externally |
| How does backend select syzkaller? | Via `SYZ_DIR` env var or explicit `syz_dir` parameter |
| Can system syzkaller be accidentally used? | No — no PATH-based fallback exists |
| What did the known working run use? | Operator-built syzkaller at `/home/charles/syzkaller` on Linux host |
| What is the recommended build path? | `cd syzkaller && make TARGETOS=linux TARGETARCH=arm64` |
