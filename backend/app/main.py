from contextlib import asynccontextmanager
from typing import AsyncIterator
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.model_client import DecisionModel, ModelError, OllamaModelClient
from app.event_log import log_event
from app.schemas import ClientEvent, StepRequest, StepResponse, validate_proposal_target
from app.settings import Settings


def create_app(settings: Settings | None = None, model_client: DecisionModel | None = None) -> FastAPI:
    configuration = settings or Settings.from_environment()
    decision_model = model_client or OllamaModelClient(configuration)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await decision_model.aclose()

    app = FastAPI(title="Habitat VLM Backend", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["GET", "POST"],
        allow_headers=["content-type"],
    )

    @app.exception_handler(RequestValidationError)
    async def request_validation_error(request: Request, _: RequestValidationError) -> JSONResponse:
        log_event("request.rejected", path=request.url.path, code="invalid_request")
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "invalid_request", "message": "Request validation failed"}},
        )

    @app.get("/health")
    async def health() -> dict[str, object]:
        model_ready = await decision_model.is_ready()
        return {
            "status": "ok",
            "model_ready": model_ready,
            "model": configuration.model_name,
        }

    @app.post("/step", response_model=StepResponse)
    async def step(observation: StepRequest) -> StepResponse | JSONResponse:
        log_event(
            "observation.received", observation=observation,
            instruction=observation.instruction,
            image_media_type=observation.image_media_type,
            image_base64_chars=len(observation.image_base64),
            visible_targets=[target.model_dump() for target in observation.visible_targets],
            held_object_id=observation.held_object_id,
            previous_action_result=(
                observation.previous_action_result.model_dump(mode="json")
                if observation.previous_action_result else None
            ),
        )
        try:
            proposal, inference_ms = await decision_model.propose(observation)
            validate_proposal_target(proposal, observation)
        except ModelError as error:
            log_event("decision.failed", observation=observation, code=error.code, message=str(error))
            status_code = 504 if error.code == "inference_timeout" else 502
            return JSONResponse(
                status_code=status_code,
                content={"error": {"code": error.code, "message": str(error)}},
            )
        except ValueError as error:
            log_event("decision.rejected", observation=observation, code="invalid_proposal", message=str(error))
            return JSONResponse(
                status_code=422,
                content={"error": {"code": "invalid_proposal", "message": str(error)}},
            )

        result = StepResponse(
            session_id=observation.session_id,
            request_id=observation.request_id,
            observation_id=observation.observation_id,
            action_id=uuid4(),
            proposal=proposal,
            inference_ms=inference_ms,
        )
        log_event(
            "decision.sent", observation=observation,
            action_id=str(result.action_id), proposal=proposal.model_dump(), inference_ms=inference_ms,
        )
        return result

    @app.post("/events", status_code=204)
    async def client_event(entry: ClientEvent) -> Response:
        context = entry.model_dump(mode="json", exclude={"event", "details"}, exclude_none=True)
        log_event(entry.event, source="web", context=context, data=entry.details)
        return Response(status_code=204)

    return app


app = create_app()