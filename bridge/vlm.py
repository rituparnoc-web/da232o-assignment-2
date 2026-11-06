"""ask_vlm(): one function that hides which model backend is in use (SPEC 8.1).

All real backends (Ollama local, Ollama on Kaggle, Gemini, Groq, OpenRouter) are
reached through the OpenAI-compatible chat API, so only base_url/model/key differ.
"""
from __future__ import annotations

import base64
import json
import logging
import time

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    BadRequestError,
    OpenAI,
)

from settings import Settings

log = logging.getLogger("bridge.vlm")

BACKOFF_S = (2, 4, 8)          # SPEC 8.1: 3 attempts with exponential back-off
RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504, 520, 522, 524, 530}

# Scripted reply sequence for the mock backend (SPEC Phase 3 "fake commands").
MOCK_SCRIPT = [
    {"thought": "Go to the shelf with the red canister.", "action": "move_to", "target": "shelf_a"},
    {"thought": "Pick up the red canister.", "action": "pick", "object": "red_canister"},
    {"thought": "Go to the left cabinet.", "action": "move_to", "target": "cabinet_left"},
    {"thought": "Open the left cabinet.", "action": "open", "target": "cabinet_left"},
    {"thought": "Place the canister inside.", "action": "place", "object": "red_canister", "location": "cabinet_left"},
    {"thought": "Close the cabinet.", "action": "close", "target": "cabinet_left"},
    {"thought": "Task complete.", "action": "done"},
]


class VLMError(RuntimeError):
    """Backend unreachable or kept failing after all retries."""


class VLMClient:
    def __init__(self, settings: Settings):
        self.s = settings
        self.b = settings.backend
        self._client: OpenAI | None = None
        self._json_mode = settings.json_mode
        if self.b.type == "openai":
            self._client = OpenAI(
                base_url=self.b.base_url,
                api_key=self.b.api_key,
                timeout=self.b.timeout_s,
                max_retries=0,          # we do our own back-off
            )

    @property
    def backend_name(self) -> str:
        return self.b.name

    @property
    def model(self) -> str:
        return self.b.model

    def ask(self, image_jpeg: bytes, system_prompt: str, user_prompt: str, *, step: int = 0) -> str:
        """Return the raw text reply from the configured backend."""
        if self.b.type == "mock":
            reply = MOCK_SCRIPT[min(step, len(MOCK_SCRIPT) - 1)]
            return json.dumps({"target": None, "object": None, "location": None, **reply})

        b64 = base64.b64encode(image_jpeg).decode("ascii")
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                ],
            },
        ]

        last_err: Exception | None = None
        for attempt in range(len(BACKOFF_S)):
            try:
                kwargs = dict(
                    model=self.b.model,
                    messages=messages,
                    temperature=self.s.temperature,
                    max_tokens=self.s.max_tokens,
                )
                if self._json_mode:
                    kwargs["response_format"] = {"type": "json_object"}
                resp = self._client.chat.completions.create(**kwargs)
                text = resp.choices[0].message.content or ""
                return text
            except BadRequestError as e:
                # Some backends reject response_format; drop it once and retry immediately.
                if self._json_mode and "response_format" in str(e).lower():
                    log.warning("Backend rejected JSON mode; continuing without it.")
                    self._json_mode = False
                    continue
                raise VLMError(f"Bad request: {e}") from e
            except APIStatusError as e:
                if e.status_code not in RETRYABLE_STATUS:
                    raise VLMError(f"HTTP {e.status_code}: {e.message}") from e
                last_err = e
            except (APIConnectionError, APITimeoutError) as e:
                last_err = e
            wait = BACKOFF_S[attempt]
            log.warning("VLM call failed (%s); retry %d in %ss", last_err, attempt + 1, wait)
            time.sleep(wait)
        raise VLMError(f"Backend '{self.b.name}' failed after retries: {last_err}")
