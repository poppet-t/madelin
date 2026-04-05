#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$(dirname "$SCRIPT_DIR")"
REPO_ROOT="$(cd "$BACKEND_DIR/../.." && pwd)"

REMOTE_HOST="${MADELIN_BUILDER_HOST:-172.16.225.132}"
REMOTE_USER="${MADELIN_BUILDER_USER:-charles}"
REMOTE_PASS="${MADELIN_BUILDER_PASSWORD:-}"
REMOTE_HOME="${MADELIN_BUILDER_HOME:-/home/$REMOTE_USER}"
REMOTE_SRC="${MADELIN_BUILDER_SRC:-$REMOTE_HOME/linux}"
REMOTE_KERNEL_CONFIG="${MADELIN_BUILDER_KERNEL_CONFIG:-$REMOTE_HOME/kernel-export/kernel.config}"
REMOTE_EXPORT_DIR="${MADELIN_BUILDER_EXPORT_DIR:-$REMOTE_HOME/kernel-export}"
LOCAL_PATCH="$REPO_ROOT/targets/net/proof/nftables-controlled-proof-uaf.patch"
LOCAL_OUT_DIR="$REPO_ROOT/syzkaller-runtime-export/kernel-export"
LOCAL_IMAGE="$LOCAL_OUT_DIR/nftables-proof-Image"
LOCAL_META="$LOCAL_OUT_DIR/nftables-proof-kernel.json"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
REMOTE_WORKTREE="$REMOTE_HOME/madelin-proof/linux-proof-$TIMESTAMP"
REMOTE_BUILD="$REMOTE_HOME/madelin-proof/build-proof-$TIMESTAMP"
REMOTE_PATCH="$REMOTE_HOME/madelin-proof/nftables-controlled-proof-uaf.patch"
REMOTE_META="$REMOTE_HOME/madelin-proof/nftables-proof-kernel.json"

usage() {
  cat >&2 <<'USAGE'
Usage: MADELIN_BUILDER_PASSWORD=<password> build_net_proof_kernel.sh

Builds a controlled-proof arm64 nf_tables kernel on the remote Linux builder
and stages the resulting Image + provenance metadata into:
  syzkaller-runtime-export/kernel-export/nftables-proof-Image
  syzkaller-runtime-export/kernel-export/nftables-proof-kernel.json

Optional env:
  MADELIN_BUILDER_HOST
  MADELIN_BUILDER_USER
  MADELIN_BUILDER_SRC
  MADELIN_BUILDER_KERNEL_CONFIG
  MADELIN_BUILDER_EXPORT_DIR
USAGE
  exit 2
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

[[ -n "$REMOTE_PASS" ]] || usage
[[ -f "$LOCAL_PATCH" ]] || { echo "Missing proof patch: $LOCAL_PATCH" >&2; exit 1; }

require_cmd expect
require_cmd ssh
require_cmd scp
require_cmd shasum
require_cmd python3

mkdir -p "$LOCAL_OUT_DIR"

run_remote() {
  EXPECT_HOST="$REMOTE_HOST" EXPECT_USER="$REMOTE_USER" EXPECT_PASS="$REMOTE_PASS" EXPECT_REMOTE_CMD="$1" \
    expect <<'EOF'
set timeout -1
set host $env(EXPECT_HOST)
set user $env(EXPECT_USER)
set pass $env(EXPECT_PASS)
set cmd $env(EXPECT_REMOTE_CMD)
spawn ssh -o StrictHostKeyChecking=no ${user}@${host} $cmd
expect {
  "password:" { send "$pass\r"; exp_continue }
  eof
}
catch wait result
set code [lindex $result 3]
exit $code
EOF
}

scp_to_remote() {
  EXPECT_HOST="$REMOTE_HOST" EXPECT_USER="$REMOTE_USER" EXPECT_PASS="$REMOTE_PASS" EXPECT_SRC="$1" EXPECT_DST="$2" \
    expect <<'EOF'
set timeout -1
set host $env(EXPECT_HOST)
set user $env(EXPECT_USER)
set pass $env(EXPECT_PASS)
set src $env(EXPECT_SRC)
set dst $env(EXPECT_DST)
spawn scp -o StrictHostKeyChecking=no $src ${user}@${host}:$dst
expect {
  "password:" { send "$pass\r"; exp_continue }
  eof
}
catch wait result
set code [lindex $result 3]
exit $code
EOF
}

scp_from_remote() {
  EXPECT_HOST="$REMOTE_HOST" EXPECT_USER="$REMOTE_USER" EXPECT_PASS="$REMOTE_PASS" EXPECT_SRC="$1" EXPECT_DST="$2" \
    expect <<'EOF'
set timeout -1
set host $env(EXPECT_HOST)
set user $env(EXPECT_USER)
set pass $env(EXPECT_PASS)
set src $env(EXPECT_SRC)
set dst $env(EXPECT_DST)
spawn scp -o StrictHostKeyChecking=no ${user}@${host}:$src $dst
expect {
  "password:" { send "$pass\r"; exp_continue }
  eof
}
catch wait result
set code [lindex $result 3]
exit $code
EOF
}

echo "[proof-kernel] remote host: $REMOTE_USER@$REMOTE_HOST"
echo "[proof-kernel] local patch: $LOCAL_PATCH"

run_remote "mkdir -p $REMOTE_HOME/madelin-proof"
scp_to_remote "$LOCAL_PATCH" "$REMOTE_PATCH"

REMOTE_BUILD_CMD=$(cat <<EOF
set -euo pipefail
cd $REMOTE_SRC
git worktree add --detach $REMOTE_WORKTREE HEAD
trap 'git -C $REMOTE_SRC worktree remove --force $REMOTE_WORKTREE >/dev/null 2>&1 || true' EXIT
mkdir -p $REMOTE_BUILD
cp $REMOTE_KERNEL_CONFIG $REMOTE_BUILD/.config
cd $REMOTE_WORKTREE
git apply $REMOTE_PATCH
make O=$REMOTE_BUILD ARCH=arm64 olddefconfig
make O=$REMOTE_BUILD ARCH=arm64 -j\$(nproc) Image
python3 - <<'PY'
import hashlib, json, pathlib, subprocess
repo = pathlib.Path("$REMOTE_WORKTREE")
build = pathlib.Path("$REMOTE_BUILD")
patch = pathlib.Path("$REMOTE_PATCH")
image = build / "arch/arm64/boot/Image"
meta = {
    "proof_mode": "controlled",
    "build_host": "$REMOTE_USER@$REMOTE_HOST",
    "source_repo": str(repo),
    "source_head": subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip(),
    "source_subject": subprocess.check_output(["git", "-C", str(repo), "show", "-s", "--format=%s", "HEAD"], text=True).strip(),
    "patch_path": str(patch),
    "patch_sha256": hashlib.sha256(patch.read_bytes()).hexdigest(),
    "config_path": str(pathlib.Path("$REMOTE_BUILD") / ".config"),
    "image_path": str(image),
}
pathlib.Path("$REMOTE_META").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\\n", encoding="utf-8")
PY
EOF
)

run_remote "$REMOTE_BUILD_CMD"
scp_from_remote "$REMOTE_BUILD/arch/arm64/boot/Image" "$LOCAL_IMAGE"
scp_from_remote "$REMOTE_META" "$LOCAL_META"

shasum -a 256 "$LOCAL_IMAGE" > "$LOCAL_IMAGE.sha256"
echo "[proof-kernel] image: $LOCAL_IMAGE"
echo "[proof-kernel] metadata: $LOCAL_META"
