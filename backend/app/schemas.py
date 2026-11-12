from __future__ import annotations

import base64
import binascii
from datetime import datetime
from io import BytesIO
from typing import Annotated, Literal, TypeAlias
from uuid import UUID

from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

MAX_IMAGE_BYTES = 2 * 1024 * 1024
MAX_IMAGE_BASE64_CHARS = 4 * ((MAX_IMAGE_BYTES + 2) // 3)
MAX_IMAGE_DIMENSION = 4096
MAX_IMAGE_PIXELS = 8_388_608

TargetId: TypeAlias = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"),
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


LogValue: TypeAlias = Annotated[str, StringConstraints(max_length=2000)] | int | float | bool | None


class ClientEvent(StrictModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    event: str = Field(pattern=r"^[a-z][a-z0-9_.]{0,63}$")
    occurred_at: datetime
    page_id: UUID
    sequence: int = Field(ge=1)
    session_id: UUID | None = None
    request_id: UUID | None = None
    observation_id: int | None = Field(default=None, ge=0)
    action_id: UUID | None = None
    details: dict[Annotated[str, StringConstraints(max_length=64)], LogValue] = Field(
        default_factory=dict, max_length=32,
    )


class NavigateTo(StrictModel):
    action: Literal["navigate_to"]
    target_id: TargetId


class PickUp(StrictModel):
    action: Literal["pick_up"]
    target_id: TargetId


class PlaceOn(StrictModel):
    action: Literal["place_on"]
    target_id: TargetId


class Stop(StrictModel):
    action: Literal["stop"]


class Finish(StrictModel):
    action: Literal["finish"]


ActionProposal: TypeAlias = Annotated[
    NavigateTo | PickUp | PlaceOn | Stop | Finish,
    Field(discriminator="action"),
]


class TargetDescriptor(StrictModel):
    target_id: TargetId
    category: Literal["container", "platform"]
    in_interaction_range: bool = False


class ActionResult(StrictModel):
    action_id: UUID
    status: Literal["succeeded", "failed", "cancelled"]
    target_id: TargetId | None = None
    error_code: str | None = None


class StepRequest(StrictModel):
    session_id: UUID
    request_id: UUID
    observation_id: int = Field(ge=0)
    instruction: str = Field(min_length=1, max_length=1000)
    image_media_type: Literal["image/jpeg", "image/png"]
    image_base64: str = Field(min_length=1, max_length=MAX_IMAGE_BASE64_CHARS)
    visible_targets: list[TargetDescriptor] = Field(max_length=64)
    held_object_id: TargetId | None = None
    previous_action_result: ActionResult | None = None

    @field_validator("instruction")
    @classmethod
    def reject_blank_instruction(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("instruction must not be blank")
        return value

    @field_validator("image_base64")
    @classmethod
    def validate_image_base64_size(cls, value: str) -> str:
        try:
            decoded = base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError) as error:
            raise ValueError("image_base64 must contain valid base64") from error

        if not decoded or len(decoded) > MAX_IMAGE_BYTES:
            raise ValueError("decoded image must be between 1 byte and 2 MiB")
        return value

    @model_validator(mode="after")
    def validate_image_media_type(self) -> StepRequest:
        image = base64.b64decode(self.image_base64, validate=True)
        try:
            with Image.open(BytesIO(image)) as decoded_image:
                image_format = decoded_image.format
                width, height = decoded_image.size
                if (
                    width > MAX_IMAGE_DIMENSION
                    or height > MAX_IMAGE_DIMENSION
                    or width * height > MAX_IMAGE_PIXELS
                ):
                    raise ValueError("image dimensions exceed the configured limit")
                decoded_image.load()
        except (Image.DecompressionBombError, OSError, UnidentifiedImageError) as error:
            raise ValueError("image_base64 must contain a valid image") from error

        expected_format = "PNG" if self.image_media_type == "image/png" else "JPEG"
        if image_format != expected_format:
            raise ValueError("image bytes do not match image_media_type")
        return self

    @field_validator("visible_targets")
    @classmethod
    def reject_duplicate_target_ids(cls, targets: list[TargetDescriptor]) -> list[TargetDescriptor]:
        target_ids = [target.target_id for target in targets]
        if len(target_ids) != len(set(target_ids)):
            raise ValueError("visible target IDs must be unique")
        return targets


class StepResponse(StrictModel):
    session_id: UUID
    request_id: UUID
    observation_id: int = Field(ge=0)
    action_id: UUID
    proposal: ActionProposal
    inference_ms: int = Field(ge=0)


def validate_proposal_target(proposal: ActionProposal, request: StepRequest) -> None:
    if not isinstance(proposal, (NavigateTo, PickUp, PlaceOn)):
        return

    target = next(
        (candidate for candidate in request.visible_targets if candidate.target_id == proposal.target_id),
        None,
    )
    if target is None:
        raise ValueError("action target is not in the current visible-target allowlist")

    if isinstance(proposal, PickUp) and target.category != "container":
        raise ValueError("pick_up requires a visible container target")
    if isinstance(proposal, PlaceOn) and target.category != "platform":
        raise ValueError("place_on requires a visible platform target")
    if isinstance(proposal, PickUp):
        if request.held_object_id is not None:
            raise ValueError("pick_up is invalid while an object is held")
    if isinstance(proposal, PlaceOn):
        if request.held_object_id is None:
            raise ValueError("place_on is invalid when no object is held")
