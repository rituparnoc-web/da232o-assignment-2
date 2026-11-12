"""Prompt templates (SPEC 8.3).

v2 (9 Nov): the model kept going after the task was done (put items back, invented new
goals, read "STEP 8 of 15" as work still to do). Now it sees the full action history,
where every item is, an explicit "is the task already complete?" check, and a warning
when it repeats itself.

v3 (12 Nov), from the 24-task suite (22/24 with v2). Failures/waste were all multi-step:
- T08: put an item in cabinet_left for "the right cabinet" -> match task words to names,
  check the location name before placing.
- T21: held an item, reached the destination, then walked away without placing (twice)
  -> "holding + near the destination = place now"; one item at a time.
- T16/T08: walked between objects after the task was done -> thought must list each part
  of the task as done/not done; warning for move_to-only wandering and 3x repeats.
All rules stay room-independent (no object names from a specific room).

v3.1 (12 Nov): v3's "match task words to object names exactly" made the model refuse
"open the purple cabinet" (T12: "no purple cabinet in the valid names") - colours are only
in the image. Now: objects may be described by name, colour or position; resolve via the
image + item locations, reply with the exact name.

v3.2 (12 Nov): "locations" = named spots on the floor (Unity kind "location"):
home_base (where the robot started; "base", "home", "start") and marked_spot (a floor
point the user clicked). move_to stands on it; place puts the item on the floor there.
"""
from __future__ import annotations

from typing import Any

PROMPT_VERSION = "v3.2"

SYSTEM_PROMPT = """You control a robot in a space habitat. You see the robot's camera image.
Each turn choose exactly ONE next action from: move_to, pick, place, open, close, look_around, done.

Field usage:
- move_to: "target" = any object name
- pick: "object" = an item
- place: "object" = the item you hold, "location" = a surface, container or location
- open / close: "target" = a container
- look_around, done: no fields
Locations are spots on the floor. home_base is where the robot started (its base / home / start position).
move_to a location makes the robot stand there; place at a location puts the item on the floor there.
If the user pointed at something, the task ends with (the user pointed at: "this" = name, "there" = name).

How to decide:
1. Split the TASK into its parts (each item and where it must end up, each container and its required state).
2. Check every part against ROBOT STATE and ITEM LOCATIONS. If ALL parts are satisfied, reply "done" immediately.
3. Otherwise choose the one action that makes progress on the first unfinished part.

Rules:
- Only use object names from the provided list. Never invent names.
- Do exactly what the task asks, nothing more. Do not start other tasks.
- Never undo progress: do not put down an item the task asked you to pick up, do not take an item out of where the task asked you to put it, do not close a container the task asked you to open.
- To pick, place, open or close something you must be near it (move_to it first).
- A container must be open before placing items into it or picking items from it.
- If an action failed, read the reason and fix the cause instead of repeating it.
- The robot holds ONE item at a time. For several items: pick one -> move_to its destination -> place it -> then go back for the next.
- If you are holding an item and you are near the place the task wants it, place it NOW (open the container first if it is closed). Do not walk away while holding it.
- Tasks may describe objects by name, colour or position (e.g. "the purple cabinet", "the canister on the table"). Use the image and ITEM LOCATIONS to decide which listed object is meant, then use its exact name in your reply. Before a place, check the location is the one the task means.

Reply with JSON only: {"thought": str, "action": str, "target": str|null, "object": str|null, "location": str|null}
In "thought" list each task part as done/not done, then the next step, e.g. "red in cabinet_x: done; blue in cabinet_x: not done -> pick blue". Under 40 words."""


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
    lines.append("Check each part of the TASK against the state above. If every part is done, reply with action \"done\". "
                 "Otherwise give the next action. Reply with JSON only.")
    return "\n".join(lines)


def repetition_warning(history: list[str]) -> str | None:
    """Detect the model going in circles: same action twice, or an A-B-A-B pattern."""
    acts = [h.split("->")[0].strip() for h in history]
    if len(acts) >= 3 and acts[-1] == acts[-2] == acts[-3]:
        return (f"you have done {acts[-1]} three times in a row. It changes nothing. "
                "If every part of the task is done reply done; otherwise choose a DIFFERENT action.")
    if len(acts) >= 3 and all(a.startswith("move_to(") for a in acts[-3:]) and len(set(acts[-3:])) > 1:
        return ("your last 3 actions were only move_to; walking around does not change anything. "
                "If you are holding an item, place it where the task wants it. "
                "If every part of the task is done, reply done.")
    if len(acts) >= 4 and acts[-1] == acts[-3] and acts[-2] == acts[-4] and acts[-1] != acts[-2]:
        return (f"you are alternating between {acts[-2]} and {acts[-1]}. This undoes your own progress. "
                "Check whether the task is already complete; if so reply done.")
    if len(acts) >= 2 and acts[-1] == acts[-2]:
        return (f"you repeated {acts[-1]} twice in a row. Do not repeat it again; "
                "check whether the task is already complete, otherwise choose a different action.")
    return None
