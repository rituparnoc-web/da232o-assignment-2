"""Parse and validate the VLM's reply (SPEC 8.4).

The model only chooses WHAT to do; here we make sure the choice is well-formed:
  1. Reply parses as JSON (code fences / <think> blocks / chatter stripped)
  2. action is in the vocabulary
  3. required fields for that action are present
  4. every referenced name is a known scene object
  5. type rules (pick/place object = item, open/close target = container,
     place location = surface|container)
Preconditions like reach and gripper state are checked in Unity.
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

from pydantic import BaseModel

ACTIONS = {"move_to", "pick", "place", "open", "close", "look_around", "done"}

# action -> {field: allowed kinds (None = any known object)}
REQUIRED: dict[str, dict[str, Optional[set[str]]]] = {
    "move_to": {"target": None},
    "pick": {"object": {"item"}},
    "place": {"object": {"item"}, "location": {"surface", "container"}},
    "open": {"target": {"container"}},
    "close": {"target": {"container"}},
    "look_around": {},
    "done": {},
}

NAME_FIELDS = ("target", "object", "location")


class Command(BaseModel):
    action: str
    target: Optional[str] = None
    object: Optional[str] = None
    location: Optional[str] = None
    thought: str = ""


class ValidationError(ValueError):
    pass


_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def extract_json(raw: str) -> dict[str, Any]:
    text = _THINK_RE.sub("", raw or "").strip()
    m = _FENCE_RE.search(text)
    if m:
        text = m.group(1).strip()
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        # fall back to the first {...} block in the text
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise ValidationError("reply is not JSON")
        try:
            obj = json.loads(text[start : end + 1])
        except json.JSONDecodeError as e:
            raise ValidationError(f"reply is not valid JSON ({e.msg})")
    if isinstance(obj, list) and obj and isinstance(obj[0], dict):
        obj = obj[0]  # model returned a list of actions: take the first
    if not isinstance(obj, dict):
        raise ValidationError("reply JSON must be an object")
    return obj


def _clean_name(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip().lower().replace(" ", "_").replace("-", "_")
    return None if s in ("", "null", "none") else s


def validate(raw: str, object_kinds: dict[str, str]) -> Command:
    """Return a valid Command or raise ValidationError with a short, model-readable reason."""
    obj = extract_json(raw)

    action = _clean_name(obj.get("action"))
    if not action:
        raise ValidationError('missing "action"')
    if action not in ACTIONS:
        raise ValidationError(f'action "{action}" is not one of {sorted(ACTIONS)}')

    fields = {f: _clean_name(obj.get(f)) for f in NAME_FIELDS}

    # Small, safe repairs for common slips (e.g. pick with "target" instead of "object")
    if action in ("pick", "place") and not fields["object"] and fields["target"]:
        fields["object"], fields["target"] = fields["target"], None
    if action in ("open", "close", "move_to") and not fields["target"]:
        fields["target"] = fields["object"] or fields["location"]
    if action == "place" and not fields["location"] and fields["target"]:
        fields["location"] = fields["target"]

    required = REQUIRED[action]
    for f, kinds in required.items():
        name = fields[f]
        if not name:
            raise ValidationError(f'action "{action}" requires field "{f}"')
        if name not in object_kinds:
            raise ValidationError(f'"{name}" is not a known object name')
        if kinds and object_kinds[name] not in kinds:
            raise ValidationError(
                f'"{f}" for "{action}" must be a {" or ".join(sorted(kinds))}, '
                f'but "{name}" is a {object_kinds[name]}'
            )

    # Drop fields the action does not use, so Unity gets a clean command
    for f in NAME_FIELDS:
        if f not in required:
            fields[f] = None

    thought = str(obj.get("thought") or "").strip()
    return Command(action=action, thought=thought[:300], **fields)
