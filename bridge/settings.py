"""Load config.yaml + .env once and expose the active backend settings."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

BRIDGE_DIR = Path(__file__).resolve().parent
load_dotenv(BRIDGE_DIR / ".env")


@dataclass
class BackendSettings:
    name: str
    type: str                      # "openai" | "mock"
    model: str
    base_url: str | None = None
    api_key: str | None = None
    timeout_s: float = 30.0


@dataclass
class Settings:
    raw: dict[str, Any]
    backend: BackendSettings
    temperature: float = 0.2
    max_tokens: int = 300
    json_mode: bool = True
    image_size: int = 512
    jpeg_quality: int = 80
    max_steps: int = 15
    max_retries_invalid: int = 1
    history_len: int = 3
    log_dir: Path = field(default_factory=lambda: BRIDGE_DIR / "logs")
    save_frames: bool = True
    object_kinds: dict[str, str] = field(default_factory=dict)


def _resolve_backend(name: str, cfg: dict[str, Any]) -> BackendSettings:
    backends = cfg.get("backends", {})
    if name not in backends:
        raise ValueError(f"Unknown backend '{name}'. Available: {', '.join(backends)}")
    b = backends[name]
    btype = b.get("type", "openai")
    if btype == "mock":
        return BackendSettings(name=name, type="mock", model=b.get("model", "scripted"))

    base_url = b.get("base_url")
    if b.get("base_url_env"):
        base_url = os.getenv(b["base_url_env"], "").strip() or None
        if not base_url:
            raise ValueError(
                f"Backend '{name}' needs env var {b['base_url_env']} (set it in bridge/.env)."
            )
    if not base_url:
        raise ValueError(f"Backend '{name}' has no base_url.")
    base_url = base_url.rstrip("/")
    # Ollama (local or tunnelled) exposes the OpenAI-compatible API under /v1
    if name in ("local", "kaggle") and not base_url.endswith("/v1"):
        base_url += "/v1"

    api_key = None
    if b.get("api_key_env"):
        api_key = os.getenv(b["api_key_env"], "").strip() or None
        if not api_key:
            raise ValueError(f"Backend '{name}' needs env var {b['api_key_env']} (set it in bridge/.env).")

    return BackendSettings(
        name=name,
        type="openai",
        model=b["model"],
        base_url=base_url,
        # Ollama ignores the key, but the OpenAI client requires a non-empty string
        api_key=api_key or "ollama",
        timeout_s=float(b.get("timeout_s", 30)),
    )


def load_settings(backend_override: str | None = None) -> Settings:
    with open(BRIDGE_DIR / "config.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    name = backend_override or os.getenv("VLM_BACKEND") or cfg.get("active_backend", "mock")
    log_dir = Path(cfg.get("log_dir", "logs"))
    if not log_dir.is_absolute():
        log_dir = BRIDGE_DIR / log_dir
    return Settings(
        raw=cfg,
        backend=_resolve_backend(name, cfg),
        temperature=float(cfg.get("temperature", 0.2)),
        max_tokens=int(cfg.get("max_tokens", 300)),
        json_mode=bool(cfg.get("json_mode", True)),
        image_size=int(cfg.get("image_size", 512)),
        jpeg_quality=int(cfg.get("jpeg_quality", 80)),
        max_steps=int(cfg.get("max_steps", 15)),
        max_retries_invalid=int(cfg.get("max_retries_invalid", 1)),
        history_len=int(cfg.get("history_len", 3)),
        log_dir=log_dir,
        save_frames=bool(cfg.get("save_frames", True)),
        object_kinds={k.lower(): v.lower() for k, v in (cfg.get("object_kinds") or {}).items()},
    )
