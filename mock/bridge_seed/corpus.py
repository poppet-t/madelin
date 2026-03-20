from __future__ import annotations

from typing import Any


def _call_texts(steps: list[dict[str, Any]]) -> list[str]:
    return [str(step["text"]) for step in steps if isinstance(step, dict) and isinstance(step.get("text"), str)]


def _dedupe_programs(programs: list[str]) -> list[str]:
    return list(dict.fromkeys(programs))


def seed_to_initial_programs(seed: dict[str, Any]) -> list[str]:
    setup_calls = _call_texts(seed.get("setup_sequence", []))
    trigger_calls = _call_texts(seed.get("trigger_sequence", []))
    programs: list[str] = []

    if setup_calls:
        programs.append("\n".join(setup_calls + trigger_calls[:1]) + "\n")
        programs.append("\n".join(setup_calls + trigger_calls) + "\n")

    if len(trigger_calls) >= 2:
        programs.append("\n".join(setup_calls + trigger_calls[:2]) + "\n")

    if any("KVM_CREATE_DEVICE" in call for call in trigger_calls + setup_calls):
        device_prog = []
        for call in setup_calls + trigger_calls:
            device_prog.append(call)
            if "KVM_SET_DEVICE_ATTR" in call:
                break
        programs.append("\n".join(device_prog) + "\n")

    reg_prog = [call for call in setup_calls + trigger_calls if "ONE_REG" in call or "KVM_ARM_VCPU_INIT" in call]
    if reg_prog:
        programs.append("\n".join(setup_calls + [call for call in reg_prog if call not in setup_calls]) + "\n")

    return [program for program in _dedupe_programs(programs) if program.strip()]
