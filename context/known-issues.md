# Known Issues

## Typical risk areas
- schema drift between stages
- bridge-to-MOCK ordering semantics not being enforced strongly enough downstream
- demo-only paths becoming mistaken for general support
- environment-dependent verifier or kernel-fuzzing workflows
- shell-script sprawl and duplicated workflow logic

## Current Blockers
- A real arm64 KVM launch still requires a Linux-capable `SYZ_DIR`, an arm64 disk image, an SSH key, and an arm64 kernel image; those runtime assets were not present in this session.
- This macOS host cannot build the required `linux/arm64 syz-executor` locally, so `mock/syz_wrapper` now stops immediately with an explicit unsupported-host error.
- The system Python on this machine still lacks `jsonschema`, `z3`, and `pytest`; future bridge validation should continue to use a reproducible local venv.
- Docs-path flattening is still deferred, so the nested `docs/plans/docs/plans/*` layout remains a maintenance point until references are migrated.

## Use this file to track
- open technical debt
- weak validation coverage
- missing typed errors
- unsupported cases that need better surfacing
- reproducibility gaps
