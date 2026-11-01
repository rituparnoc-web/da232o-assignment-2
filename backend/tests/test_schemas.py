from io import BytesIO
from base64 import b64encode
from uuid import uuid4

import pytest
from PIL import Image
from pydantic import TypeAdapter, ValidationError

from app.schemas import (
    ActionProposal,
    Finish,
    NavigateTo,
    PickUp,
    PlaceOn,
    StepRequest,
    Stop,
    validate_proposal_target,
)

ACTION_ADAPTER = TypeAdapter(ActionProposal)


def make_png() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (2, 2), color="blue").save(buffer, format="PNG")
    return buffer.getvalue()


def make_request() -> StepRequest:
    return StepRequest(
        session_id=uuid4(),
        request_id=uuid4(),
        observation_id=0,
        instruction="Pick up the blue container and place it on the platform.",
        image_media_type="image/png",
        image_base64=b64encode(make_png()).decode("ascii"),
        visible_targets=[
            {"target_id": "object_01", "category": "container"},
            {"target_id": "delivery_01", "category": "platform"},
        ],
    )


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"action": "navigate_to", "target_id": "object_01"}, NavigateTo),
        ({"action": "pick_up", "target_id": "object_01"}, PickUp),
        ({"action": "place_on", "target_id": "delivery_01"}, PlaceOn),
        ({"action": "stop"}, Stop),
        ({"action": "finish"}, Finish),
    ],
)
def test_action_contract_accepts_each_permitted_action(payload, expected):
    assert isinstance(ACTION_ADAPTER.validate_python(payload), expected)


@pytest.mark.parametrize(
    "payload",
    [
        {"action": "fly", "target_id": "object_01"},
        {"action": "stop", "target_id": "object_01"},
        {"action": "pick_up", "target_id": "object_01", "coordinates": [0, 0, 0]},
    ],
)
def test_action_contract_rejects_unknown_or_extra_fields(payload):
    with pytest.raises(ValidationError):
        ACTION_ADAPTER.validate_python(payload)


def test_target_allowlist_rejects_targets_not_in_current_observation():
    request = make_request()

    with pytest.raises(ValueError, match="visible-target allowlist"):
        validate_proposal_target(PickUp(action="pick_up", target_id="object_99"), request)


def test_target_allowlist_enforces_action_category():
    request = make_request()

    with pytest.raises(ValueError, match="visible container"):
        validate_proposal_target(PickUp(action="pick_up", target_id="delivery_01"), request)

    with pytest.raises(ValueError, match="visible platform"):
        validate_proposal_target(PlaceOn(action="place_on", target_id="object_01"), request)


def test_target_allowlist_accepts_matching_visible_targets():
    request = make_request()

    validate_proposal_target(PickUp(action="pick_up", target_id="object_01"), request)
    validate_proposal_target(PlaceOn(action="place_on", target_id="delivery_01"), request)


def test_step_request_rejects_truncated_image_even_with_valid_png_header():
    with pytest.raises(ValidationError, match="valid image"):
        StepRequest(
            session_id=uuid4(),
            request_id=uuid4(),
            observation_id=0,
            instruction="Move to the container.",
            image_media_type="image/png",
            image_base64=b64encode(b"\x89PNG\r\n\x1a\n").decode("ascii"),
            visible_targets=[],
        )