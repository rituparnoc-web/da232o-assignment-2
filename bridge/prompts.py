"""Prompt templates (SPEC 8.3)."""
from __future__ import annotations

from typing import Any

SYSTEM_PROMPT = """You control a robot in a space habitat. You see the robot's camera image.
Choose exactly ONE next action from: move_to, pick, place, open, close, look_around, done.
Only use object names from the provided list. Never invent names.
Reply with JSON only: {"thought": str, "action": str, "target": str|null, "object": str|null, "location": str|null}
Field usage:
- move_to: "target" = any object name
- pick: "object" = an item
- place: "object" = the item you hold, "location" = a surface or container
- open / close: "target" = a container
- look_around, done: no fields
Rules: you can only pick/place/open/close things you are near (move_to first).
Containers must be open before placing items inside. Say "done" when the task is complete.
Keep "thought" under 25 words."""


def _fmt_result(r: dict[str, Any] | None) -> str:
    if not r or not r.get("action"):
        return "none (first step)"
    args = ", ".join(f"{k}={r[k]}" for k in ("target", "object", "location") if r.get(k))
    status = "SUCCESS" if r.get("success") else f"FAILED ({r.get('reason') or 'no reason'})"
    return f"{r['action']}({args}) -> {status}"


def build_user_prompt(
    task: str,
    object_kinds: dict[str, str],
    robot_state: dict[str, Any],
    last_result: dict[str, Any] | None,
    history: list[str],
    step: int,
    max_steps: int,
    error: str | None = None,
) -> str:
    by_kind: dict[str, list[str]] = {}
    for name, kind in object_kinds.items():
        by_kind.setdefault(kind, []).append(name)
    objects = "\n".join(f"  {k}s: {', '.join(sorted(v))}" for k, v in sorted(by_kind.items()))

    containers = robot_state.get("containers") or {}
    cont = ", ".join(f"{k}={v}" for k, v in containers.items()) or "unknown"
    near = ", ".join(robot_state.get("near") or []) or "nothing"
    holding = robot_state.get("holding") or "nothing"

    lines = [
        f"TASK: {task}",
        f"STEP: {step + 1} of {max_steps}",
        "VALID OBJECT NAMES:",
        objects,
        "ROBOT STATE:",
        f"  holding: {holding}",
        f"  near: {near}",
        f"  containers: {cont}",
        f"LAST ACTION: {_fmt_result(last_result)}",
        f"RECENT ACTIONS: {'; '.join(history) if history else 'none'}",
    ]
    if error:
        lines.append(f"Your last reply was invalid because: {error}. Reply again with valid JSON only.")
    lines.append("What is the next action? Reply with JSON only.")
    return "\n".join(lines)
