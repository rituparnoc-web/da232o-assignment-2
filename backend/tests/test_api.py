import asyncio
import json
from io import BytesIO
from base64 import b64encode
from uuid import uuid4

import httpx
import pytest
from PIL import Image

from app.main import create_app
from app.model_client import ModelError
from app.schemas import NavigateTo, StepRequest
from app.settings import Settings


class FakeModel:
    def __init__(self, proposal=None, error: ModelError | None = None, ready: bool = True):
        self.proposal = proposal or NavigateTo(action="navigate_to", target_id="object_01")
        self.error = error
        self.ready = ready

    async def is_ready(self) -> bool:
        return self.ready

    async def propose(self, request: StepRequest):
        if self.error:
            raise self.error
        return self.proposal, 17

    async def aclose(self) -> None:
        pass


def send_request(app, method: str, path: str, **kwargs) -> httpx.Response:
    async def send():
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://testserver",
            ) as client:
                return await client.request(method, path, **kwargs)

    return asyncio.run(send())


def make_request_payload() -> dict:
    image = BytesIO()
    Image.new("RGB", (2, 2), color="blue").save(image, format="PNG")
    return StepRequest(
        session_id=uuid4(),
        request_id=uuid4(),
        observation_id=3,
        instruction="Move to the blue container.",
        image_media_type="image/png",
        image_base64=b64encode(image.getvalue()).decode("ascii"),
        visible_targets=[{"target_id": "object_01", "category": "container"}],
    ).model_dump(mode="json")


def test_health_distinguishes_service_from_model_readiness():
    response = send_request(create_app(Settings(), FakeModel(ready=False)), "GET", "/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "model_ready": False,
        "model": "qwen2.5vl:3b",
    }


def test_cors_preflight_allows_local_browser_client():
    response = send_request(
        create_app(Settings(), FakeModel()),
        "OPTIONS",
        "/step",
        headers={
            "origin": "http://localhost:5173",
            "access-control-request-method": "POST",
            "access-control-request-headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_step_returns_correlated_proposal_and_backend_generated_action_id():
    payload = make_request_payload()
    response = send_request(create_app(Settings(), FakeModel()), "POST", "/step", json=payload)

    body = response.json()
    assert response.status_code == 200
    assert body["session_id"] == payload["session_id"]
    assert body["request_id"] == payload["request_id"]
    assert body["observation_id"] == payload["observation_id"]
    assert body["action_id"]
    assert body["proposal"] == {"action": "navigate_to", "target_id": "object_01"}
    assert body["inference_ms"] == 17


def test_step_rejects_model_target_outside_visible_allowlist():
    model = FakeModel(proposal=NavigateTo(action="navigate_to", target_id="object_99"))
    response = send_request(create_app(Settings(), model), "POST", "/step", json=make_request_payload())

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_proposal"


def test_step_returns_structured_timeout_without_fallback_action():
    model = FakeModel(error=ModelError("inference_timeout", "Vision model inference timed out"))
    response = send_request(create_app(Settings(), model), "POST", "/step", json=make_request_payload())

    assert response.status_code == 504
    assert response.json() == {
        "error": {"code": "inference_timeout", "message": "Vision model inference timed out"}
    }


def test_step_rejects_malformed_image_request():
    payload = make_request_payload()
    payload["image_base64"] = "not base64"
    response = send_request(create_app(Settings(), FakeModel()), "POST", "/step", json=payload)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


def test_decision_logs_are_correlated_and_exclude_image_data(caplog):
    caplog.set_level("INFO", logger="uvicorn.error.habitat")
    payload = make_request_payload()
    response = send_request(create_app(Settings(), FakeModel()), "POST", "/step", json=payload)

    events = [json.loads(record.message) for record in caplog.records if record.name == "uvicorn.error.habitat"]
    assert [event["event"] for event in events] == ["observation.received", "decision.sent"]
    assert all(event["request_id"] == payload["request_id"] for event in events)
    assert events[0]["details"]["instruction"] == payload["instruction"]
    assert events[1]["details"]["action_id"] == response.json()["action_id"]
    assert payload["image_base64"] not in caplog.text


def test_browser_events_join_server_logs_without_multiline_injection(caplog):
    caplog.set_level("INFO", logger="uvicorn.error.habitat")
    entry = {
        "event": "mission.started", "page_id": str(uuid4()), "sequence": 1,
        "session_id": str(uuid4()), "occurred_at": "2026-11-12T15:00:00Z",
        "details": {"instruction": "Deliver blue.\nThen stop.", "source": "not a log source"},
    }
    response = send_request(create_app(Settings(), FakeModel()), "POST", "/events", json=entry)

    assert response.status_code == 204
    record = next(record for record in caplog.records if record.name == "uvicorn.error.habitat")
    event = json.loads(record.message)
    assert event["source"] == "web"
    assert event["session_id"] == entry["session_id"]
    assert event["sequence"] == 1
    assert event["details"] == entry["details"]
    assert "\n" not in record.message


@pytest.mark.parametrize("change", [
    {"details": {"message": "x" * 2001}},
    {"details": {"nested": {"unexpected": True}}},
    {"image_base64": "not accepted by this endpoint"},
    {"event": "injected\nline"},
])
def test_browser_event_endpoint_rejects_unbounded_or_unexpected_fields(change):
    entry = {
        "event": "ui.message", "page_id": str(uuid4()), "sequence": 1,
        "occurred_at": "2026-11-12T15:00:00Z", "details": {},
        **change,
    }
    response = send_request(create_app(Settings(), FakeModel()), "POST", "/events", json=entry)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"