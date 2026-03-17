from __future__ import annotations

import sys


def print_cli_error(tool_name: str, error: Exception, candidate_id: str | None = None) -> int:
    prefix = f"[{tool_name}] error"
    if candidate_id:
        prefix += f" [candidate_id={candidate_id}]"
    print(f"{prefix}: {error}", file=sys.stderr, flush=True)
    return 1
