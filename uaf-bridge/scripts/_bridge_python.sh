#!/usr/bin/env bash

bridge_python_is_available() {
  local candidate="$1"
  if [[ "$candidate" == */* ]]; then
    [[ -x "$candidate" ]]
    return
  fi
  command -v "$candidate" >/dev/null 2>&1
}

bridge_python_passes_preflight() {
  local candidate="$1"
  local bridge_root="$2"
  "$candidate" "$bridge_root/scripts/check_env.py" >/dev/null 2>&1
}

select_bridge_python() {
  local bridge_root="$1"
  local override="${PYTHON:-}"
  local fallback=""
  local candidate

  if [[ -n "$override" ]]; then
    if bridge_python_is_available "$override"; then
      printf '%s\n' "$override"
      return 0
    fi
    printf 'error: requested PYTHON is not executable: %s\n' "$override" >&2
    return 1
  fi

  for candidate in \
    "$bridge_root/.venv_ci/bin/python" \
    "$bridge_root/.venv/bin/python" \
    "$bridge_root/.venv_sys/bin/python" \
    "python3"
  do
    if ! bridge_python_is_available "$candidate"; then
      continue
    fi
    if [[ -z "$fallback" ]]; then
      fallback="$candidate"
    fi
    if bridge_python_passes_preflight "$candidate" "$bridge_root"; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done

  if [[ -n "$fallback" ]]; then
    printf '%s\n' "$fallback"
    return 0
  fi

  printf 'python3\n'
}
