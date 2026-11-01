import asyncio
import json
from io import BytesIO
from base64 import b64encode
from uuid import uuid4

import httpx
from PIL import Image

from app.model_client import OllamaModelClient
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


def test_ollama_request_contains_actual_image_and_returns_parsed_action():
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

    assert captured_request["model"] == "llama3.2-vision:11b"
    assert captured_request["messages"][1]["images"] == [make_request().image_base64]
    assert captured_request["options"]["temperature"] == 0
    assert proposal.action == "navigate_to"
    assert proposal.target_id == "object_01"
    assert inference_ms >= 0