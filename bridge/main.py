"""HabitatVLM bridge: Unity <-> VLM (SPEC 7).

Run (from the bridge/ folder, using the project venv):
    ..\\my_env\\Scripts\\python.exe -m uvicorn main:app --port 8000
Docs UI: http://localhost:8000/docs
"""
from __future__ import annotations

import base64
import io
import logging
import threading
import time
from datetime import datetime
from typing import Any, Optional, Union

from fastapi import FastAPI, HTTPException
from PIL import Image
from pydantic import BaseModel, Field, field_validator

from logger import RunLogger
from prompts import SYSTEM_PROMPT, build_user_prompt
from settings import load_settings
from validator import Command, ValidationError, validate
from vlm import VLMClient, VLMError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("bridge")

settings = load_settings()
vlm = VLMClient(settings)
runlog = RunLogger(settings.log_dir, settings.save_frames)
app = FastAPI(title="HabitatVLM bridge", version="0.2")


# ---------------------------------------------------------------- request models
# Unity's JsonUtility cannot write null or dictionaries, so empty strings mean
# "none" and dictionaries may arrive as lists of {name, state}/{name, kind}.

def _none_if_empty(v: Any) -> Any:
    return None if v in ("", "null", "None") else v


def _pairs_to_dict(v: Any, value_key: str) -> dict[str, str]:
    if v is None:
        return {}
    if isinstance(v, dict):
        return {str(k).lower(): str(x).lower() for k, x in v.items()}
    if isinstance(v, list):
        return {str(p["name"]).lower(): str(p[value_key]).lower() for p in v if p.get("name")}
    raise ValueError("expected an object or a list of {name, ...} pairs")


class EpisodeStartReq(BaseModel):
    task: str
    scene_objects: list[str]
    object_kinds: Union[dict[str, str], list[dict[str, str]], None] = None
    max_steps: Optional[int] = None
    task_id: Optional[str] = None

    @field_validator("object_kinds", mode="before")
    @classmethod
    def _kinds(cls, v):
        return _pairs_to_dict(v, "kind")


class RobotState(BaseModel):
    holding: Optional[str] = None
    near: list[str] = Field(default_factory=list)
    containers: Union[dict[str, str], list[dict[str, str]], None] = None

    @field_validator("holding", mode="before")
    @classmethod
    def _holding(cls, v):
        return _none_if_empty(v)

    @field_validator("containers", mode="before")
    @classmethod
    def _containers(cls, v):
        return _pairs_to_dict(v, "state")


class LastResult(BaseModel):
    action: Optional[str] = None
    target: Optional[str] = None
    object: Optional[str] = None
    location: Optional[str] = None
    success: bool = False
    reason: str = ""

    @field_validator("action", "target", "object", "location", mode="before")
    @classmethod
    def _empty(cls, v):
        return _none_if_empty(v)


class StepReq(BaseModel):
    episode_id: str
    step: int
    image_b64: str
    robot_state: RobotState = Field(default_factory=RobotState)
    last_result: Optional[LastResult] = None


class EpisodeEndReq(BaseModel):
    episode_id: str
    success: bool
    steps: int
    reason: str = ""
    last_result: Optional[LastResult] = None


# ---------------------------------------------------------------- episode state
class Episode:
    def __init__(self, req: EpisodeStartReq, eid: str):
        self.id = eid
        self.task = req.task
        self.task_id = req.task_id or ""
        self.max_steps = req.max_steps or settings.max_steps
        names = [n.strip().lower() for n in req.scene_objects]
        kinds = {**settings.object_kinds, **(req.object_kinds or {})}
        unknown = [n for n in names if n not in kinds]
        if unknown:
            raise HTTPException(400, f"No kind known for objects {unknown}; add them to config.yaml object_kinds or send object_kinds.")
        self.object_kinds = {n: kinds[n] for n in names}
        self.history: list[str] = []
        self.pending_row: Optional[dict[str, Any]] = None
        self.total_latency_ms = 0
        self.invalid_count = 0
        self.started = datetime.now().isoformat(timespec="seconds")


episodes: dict[str, Episode] = {}
_lock = threading.Lock()


def _flush_pending(ep: Episode, result: Optional[LastResult]) -> None:
    """Write the previous step's CSV row once Unity has reported its outcome."""
    if ep.pending_row is None:
        return
    row = ep.pending_row
    if result is not None and result.action:
        row["unity_success"] = result.success
        row["unity_reason"] = result.reason
    runlog.step(row)
    ep.pending_row = None


def _prepare_image(b64: str) -> bytes:
    try:
        raw = base64.b64decode(b64, validate=False)
        img = Image.open(io.BytesIO(raw)).convert("RGB")
    except Exception as e:
        raise HTTPException(400, f"image_b64 is not a valid image: {e}")
    size = settings.image_size
    if img.size != (size, size):
        img = img.resize((size, size))
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=settings.jpeg_quality)
    return out.getvalue()


# ---------------------------------------------------------------- endpoints
@app.get("/health")
def health():
    return {"status": "ok", "backend": vlm.backend_name, "model": vlm.model}


@app.post("/episode/start")
def episode_start(req: EpisodeStartReq):
    with _lock:
        base = "ep_" + datetime.now().strftime("%Y%m%d_%H%M%S")
        eid, n = base, 2
        while eid in episodes:          # two episodes in the same second
            eid, n = f"{base}_{n}", n + 1
        episodes[eid] = Episode(req, eid)
    log.info("Episode %s started: %r (%d objects)", eid, req.task, len(req.scene_objects))
    return {"episode_id": eid}


@app.post("/step")
def step(req: StepReq):
    ep = episodes.get(req.episode_id)
    if ep is None:
        raise HTTPException(404, f"Unknown episode_id {req.episode_id}")

    _flush_pending(ep, req.last_result)
    if req.last_result and req.last_result.action:
        r = req.last_result
        args = ",".join(x for x in (r.target, r.object, r.location) if x)
        ep.history.append(f"{r.action}({args})->{'ok' if r.success else 'fail'}")

    jpeg = _prepare_image(req.image_b64)
    runlog.frame(ep.id, req.step, jpeg)

    state = req.robot_state.model_dump()
    last = req.last_result.model_dump() if req.last_result else None
    history = ep.history[-settings.history_len :]

    error: Optional[str] = None
    cmd: Optional[Command] = None
    retries = 0
    latency_ms = 0
    for attempt in range(settings.max_retries_invalid + 1):
        retries = attempt
        prompt = build_user_prompt(ep.task, ep.object_kinds, state, last, history,
                                   req.step, ep.max_steps, error)
        t0 = time.perf_counter()
        try:
            raw = vlm.ask(jpeg, SYSTEM_PROMPT, prompt, step=req.step)
        except VLMError as e:
            latency_ms += int((time.perf_counter() - t0) * 1000)
            error = f"backend error: {e}"
            log.error("Step %s/%d: %s", ep.id, req.step, error)
            break  # retrying the prompt won't fix a dead backend
        latency_ms += int((time.perf_counter() - t0) * 1000)
        try:
            cmd = validate(raw, ep.object_kinds)
            error = None
            break
        except ValidationError as e:
            error = str(e)
            log.warning("Step %s/%d invalid (%s). Raw: %.200s", ep.id, req.step, error, raw)

    valid = cmd is not None
    if not valid:
        ep.invalid_count += 1
        cmd = Command(action="look_around", thought=f"(fallback) {error}")
    ep.total_latency_ms += latency_ms

    ep.pending_row = {
        "episode_id": ep.id, "step": req.step, "backend": vlm.backend_name, "model": vlm.model,
        "task": ep.task, "action": cmd.action, "target": cmd.target, "object": cmd.object,
        "location": cmd.location, "valid": valid, "retries": retries, "latency_ms": latency_ms,
        "thought": cmd.thought, "error": error,
    }
    log.info("Step %s/%d -> %s t=%s o=%s l=%s (%d ms, valid=%s) | %s", ep.id, req.step,
             cmd.action, cmd.target, cmd.object, cmd.location, latency_ms, valid, cmd.thought)
    return {
        **cmd.model_dump(),
        "meta": {"backend": vlm.backend_name, "model": vlm.model, "latency_ms": latency_ms,
                 "valid": valid, "retries": retries, "error": error or ""},
    }


@app.post("/episode/end")
def episode_end(req: EpisodeEndReq):
    ep = episodes.pop(req.episode_id, None)
    if ep is None:
        raise HTTPException(404, f"Unknown episode_id {req.episode_id}")
    _flush_pending(ep, req.last_result)
    runlog.episode({
        "episode_id": ep.id, "task_id": ep.task_id, "backend": vlm.backend_name, "model": vlm.model,
        "task": ep.task, "success": req.success, "steps": req.steps,
        "total_latency_ms": ep.total_latency_ms, "invalid_count": ep.invalid_count,
        "reason": req.reason, "started": ep.started,
        "ended": datetime.now().isoformat(timespec="seconds"),
    })
    log.info("Episode %s ended: success=%s steps=%d (%s)", ep.id, req.success, req.steps, req.reason)
    return {"logged": True}
