import json
import logging
from collections.abc import Mapping
from datetime import datetime, timezone

from app.schemas import StepRequest

logger = logging.getLogger("uvicorn.error.habitat")


def log_event(
    event: str,
    *,
    source: str = "backend",
    observation: StepRequest | None = None,
    context: dict[str, object] | None = None,
    data: Mapping[str, object] | None = None,
    **details: object,
) -> None:
    record = dict(context or {})
    if observation is not None:
        record.update(
            session_id=str(observation.session_id),
            request_id=str(observation.request_id),
            observation_id=observation.observation_id,
        )
    record.update(
        timestamp=datetime.now(timezone.utc).isoformat(),
        source=source,
        event=event,
        details=dict(data) if data is not None else details,
    )
    logger.info("%s", json.dumps(record, ensure_ascii=True, allow_nan=False))
