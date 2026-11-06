"""CSV step/episode logs and saved frames (SPEC 8.5)."""
from __future__ import annotations

import csv
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

STEP_FIELDS = [
    "timestamp", "episode_id", "step", "backend", "model", "task",
    "action", "target", "object", "location", "valid", "retries",
    "latency_ms", "unity_success", "unity_reason", "thought", "error",
]
EPISODE_FIELDS = [
    "episode_id", "task_id", "backend", "model", "task", "success", "steps",
    "total_latency_ms", "invalid_count", "reason", "started", "ended",
]


class RunLogger:
    def __init__(self, log_dir: Path, save_frames: bool = True):
        self.dir = log_dir
        self.frames_dir = log_dir / "frames"
        self.save_frames = save_frames
        self.dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _append(self, name: str, fields: list[str], row: dict[str, Any]) -> None:
        path = self.dir / name
        with self._lock:
            new = not path.exists()
            with open(path, "a", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
                if new:
                    w.writeheader()
                w.writerow({k: ("" if row.get(k) is None else row.get(k)) for k in fields})

    def step(self, row: dict[str, Any]) -> None:
        row.setdefault("timestamp", datetime.now().isoformat(timespec="seconds"))
        self._append("steps.csv", STEP_FIELDS, row)

    def episode(self, row: dict[str, Any]) -> None:
        self._append("episodes.csv", EPISODE_FIELDS, row)

    def frame(self, episode_id: str, step: int, jpeg: bytes) -> Path | None:
        if not self.save_frames:
            return None
        d = self.frames_dir / episode_id
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{step:03d}.jpg"
        p.write_bytes(jpeg)
        return p
