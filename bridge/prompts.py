"""Prompt templates (SPEC 8.3).

v2 (9 Nov): the model kept going after the task was done (put items back, invented new
goals, read "STEP 8 of 15" as work still to do). Now it sees the full action history,
where every item is, an explicit "is the task already complete?" check, and a warning
when it repeats itself.
"""
from __future__ import annotations

from typing import Any

SYSTEM_PROMPT = """You control a robot in a space habitat. You see the robot's camera image.
Each turn choose exactly ONE next action from: move_to, pick, place, open, close, look_around, done.

Field usage:
- move_to: "target" = any object name
- pick: "object" = an item
- place: "object" = the item you hold, "location" = a surface or container
- open / close: "target" = a container
- look_around, done: no fields

How to decide:
1. FIRST compare the TASK with ROBOT STATE and ITEM LOCATIONS. If the task is already complete, reply "done" immediately.
2. Otherwise choose the one action that makes progress toward the task.

Rules:
- Only use object names from the provided list. Never invent names.
- Do exactly what the task asks, nothing more. Do not start other tasks.
- Never undo progress: do not put down an item the task asked you to pick up, do not take an item out of where the task asked you to put it, do not close a container the task asked you to open.
- To pick, place, open or close something you must be near it (move_to it first).
- A container must be open before placing items into it or picking items from it.
- If an action failed, read the reason and fix the cause instead of repeating it.

Reply with JSON only: {"thought": str, "action": str, "target": str|null, "object": str|null, "location": str|null}
Keep "thought" under 25 words."""


def _fmt_action(r: dict[str, Any]) -> str:
    args = ", ".join(str(r[k]) for k in ("target", "object", "location") if r.get(k))
    return f"{r['action']}({args})"


def _fmt_result(r: dict[str, Any] | None) -> str:
    if not r or not r.get("action"):
        return "none (this is the first action)"
    status = "SUCCESS" if r.get("success") else "FAILED"
    reason = r.get("reason") or ""
    return f"{_fmt_action(r)} -> {status}" + (f" ({reason})" if reason else "")


def build_user_prompt(
    task: str,
    object_kinds: dict[str, str],
    robot_state: dict[str, Any],
    last_result: dict[str, Any] | None,
    history: list[str],
    step: int,
    max_steps: int,
    error: str | None = None,
    warning: str | None = None,
) -> str:
    by_kind: dict[str, list[str]] = {}
    for name, kind in object_kinds.items():
        by_kind.setdefault(kind, []).append(name)
    objects = "\n".join(f"  {k}s: {', '.join(sorted(v))}" for k, v in sorted(by_kind.items()))

    containers = robot_state.get("containers") or {}
    cont = ", ".join(f"{k} is {v}" for k, v in containers.items()) or "none"
    near = ", ".join(robot_state.get("near") or []) or "nothing"
    holding = robot_state.get("holding") or "nothing"
    items = robot_state.get("items") or {}
    item_lines = "\n".join(f"  {k}: {v}" for k, v in sorted(items.items())) or "  (unknown)"

    if history:
        hist = "\n".join(f"  {i + 1}. {h}" for i, h in enumerate(history))
    else:
        hist = "  none yet"

    lines = [
        f"TASK: {task}",
        "VALID OBJECT NAMES:",
        objects,
        "ROBOT STATE:",
        f"  holding: {holding}",
        f"  near: {near}",
        f"  containers: {cont}",
        "ITEM LOCATIONS:",
        item_lines,
        f"ACTIONS SO FAR ({len(history)} used, limit {max_steps}):",
        hist,
        f"LAST ACTION RESULT: {_fmt_result(last_result)}",
    ]
    if warning:
        lines.append(f"WARNING: {warning}")
    if error:
        lines.append(f"Your last reply was invalid because: {error}. Reply again with valid JSON only.")
    lines.append("Is the TASK already complete according to the state above? If yes, reply with action \"done\". "
                 "Otherwise give the next action. Reply with JSON only.")
    return "\n".join(lines)


def repetition_warning(history: list[str]) -> str | None:
    """Detect the model going in circles: same action twice, or an A-B-A-B pattern."""
    acts = [h.split("->")[0].strip() for h in history]
    if len(acts) >= 4 and acts[-1] == acts[-3] and acts[-2] == acts[-4] and acts[-1] != acts[-2]:
        return (f"you are alternating between {acts[-2]} and {acts[-1]}. This undoes your own progress. "
                "Check whether the task is already complete; if so reply done.")
    if len(acts) >= 2 and acts[-1] == acts[-2]:
        return (f"you repeated {acts[-1]} twice in a row. Do not repeat it again; "
                "check whether the task is already complete, otherwise choose a different action.")
    return None
