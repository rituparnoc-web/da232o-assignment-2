import asyncio
import json
from io import BytesIO
from base64 import b64encode
from uuid import uuid4

import httpx
import pytest
from PIL import Image

from app.model_client import ACTION_OUTPUT_SCHEMA, ModelError, OllamaModelClient, action_target_ids, allowed_actions
from app.schemas import StepRequest
from app.settings import Settings


def make_request() -> StepRequest:
    image = BytesIO()
    Image.new("RGB", (2, 2), color="blue").save(image, format="PNG")
    return StepRequest(
        session_id=uuid4(),
        request_id=uuid4(),
        observation_id=0,
        instruction="Pick up the blue container.",
        image_media_type="image/png",
        image_base64=b64encode(image.getvalue()).decode("ascii"),
        visible_targets=[{"target_id": "object_01", "category": "container"}],
    )


def test_ollama_request_contains_actual_image_and_returns_parsed_action(caplog):
    caplog.set_level("INFO", logger="uvicorn.error.habitat")
    captured_request = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_request.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={"message": {"content": '{"action":"navigate_to","target_id":"object_01"}'}},
        )

    async def run_test():
        client = OllamaModelClient(Settings(), transport=httpx.MockTransport(handler))
        try:
            proposal, inference_ms = await client.propose(make_request())
        finally:
            await client.aclose()
        return proposal, inference_ms

    proposal, inference_ms = asyncio.run(run_test())

    assert captured_request["model"] == "qwen2.5vl:3b"
    assert captured_request["format"] == ACTION_OUTPUT_SCHEMA
    assert captured_request["messages"][1]["images"] == [make_request().image_base64]
    assert '"in_interaction_range":false' in captured_request["messages"][1]["content"]
    assert "performs approach, pickup" in captured_request["messages"][0]["content"]
    assert '"allowed_actions"' in captured_request["messages"][1]["content"]
    assert '"allowed_target_ids"' in captured_request["messages"][1]["content"]
    assert captured_request["options"]["temperature"] == 0
    assert proposal.action == "navigate_to"
    assert proposal.target_id == "object_01"
    assert inference_ms >= 0
    events = [json.loads(record.message) for record in caplog.records if record.name == "uvicorn.error.habitat"]
    assert [event["event"] for event in events] == ["model.request", "model.response", "model.validated"]
    assert events[0]["details"]["prompt"]["instruction"] == make_request().instruction
    assert events[1]["details"]["content"] == '{"action":"navigate_to","target_id":"object_01"}'
    assert events[2]["details"]["proposal"]["target_id"] == "object_01"
    assert len({event["request_id"] for event in events}) == 1
    assert make_request().image_base64 not in caplog.text


def test_allowed_actions_follow_held_object_state():
    request = make_request()
    assert allowed_actions(request) == ["navigate_to", "pick_up", "stop", "finish"]
    assert action_target_ids(request)["pick_up"] == ["object_01"]

    carrying_request = StepRequest.model_validate({
        **request.model_dump(),
        "visible_targets": [
            {"target_id": "object_01", "category": "container", "in_interaction_range": False},
            {"target_id": "delivery_01", "category": "platform", "in_interaction_range": False},
        ],
        "held_object_id": "object_01",
    })
    assert allowed_actions(carrying_request) == ["navigate_to", "place_on", "stop", "finish"]
    assert action_target_ids(carrying_request)["navigate_to"] == ["delivery_01"]
    assert action_target_ids(carrying_request)["place_on"] == ["delivery_01"]
    assert "pick_up" not in allowed_actions(carrying_request)


@pytest.mark.parametrize("failure", ["timeout", "invalid_json"])
def test_model_failures_are_logged_without_a_fallback_action(caplog, failure):
    caplog.set_level("INFO", logger="uvicorn.error.habitat")

    def handler(request: httpx.Request) -> httpx.Response:
        if failure == "timeout":
            raise httpx.ReadTimeout("Timed out", request=request)
        return httpx.Response(200, json={"message": {"content": "not json " * 400}})

    async def run_test():
        client = OllamaModelClient(Settings(), transport=httpx.MockTransport(handler))
        try:
            with pytest.raises(ModelError):
                await client.propose(make_request())
        finally:
            await client.aclose()

    asyncio.run(run_test())
    events = [json.loads(record.message) for record in caplog.records if record.name == "uvicorn.error.habitat"]
    assert events[-1]["event"] == "model.failed"
    assert events[-1]["details"]["code"] == ("inference_timeout" if failure == "timeout" else "invalid_model_output")
    assert not any(event["event"] == "model.validated" for event in events)
    if failure == "invalid_json":
        reply = next(event for event in events if event["event"] == "model.response")
        assert len(reply["details"]["content"]) == 2000
        assert reply["details"]["truncated"] is True