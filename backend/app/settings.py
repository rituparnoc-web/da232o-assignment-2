from __future__ import annotations

from dataclasses import dataclass
import os
from urllib.parse import urlparse


@dataclass(frozen=True)
class Settings:
    ollama_url: str = "http://127.0.0.1:11434"
    model_name: str = "qwen2.5vl:3b"
    inference_timeout_seconds: float = 120.0

    @classmethod
    def from_environment(cls) -> Settings:
        settings = cls(
            ollama_url=os.getenv("OLLAMA_URL", cls.ollama_url).rstrip("/"),
            model_name=os.getenv("VLM_MODEL", cls.model_name),
            inference_timeout_seconds=float(os.getenv("VLM_TIMEOUT_SECONDS", "120")),
        )
        parsed_url = urlparse(settings.ollama_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise ValueError("OLLAMA_URL must be an absolute HTTP or HTTPS URL")
        if settings.inference_timeout_seconds <= 0:
            raise ValueError("VLM_TIMEOUT_SECONDS must be greater than zero")
        if not settings.model_name.strip():
            raise ValueError("VLM_MODEL must not be blank")
        return settings