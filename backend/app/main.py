from contextlib import asynccontextmanager
from typing import AsyncIterator
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.model_client import DecisionModel, ModelError, OllamaModelClient
from app.schemas import StepRequest, StepResponse, validate_proposal_target
from app.settings import Settings


def create_app(settings: Settings | None = None, model_client: DecisionModel | None = None) -> FastAPI:
    configuration = settings or Settings.from_environment()
    decision_model = model_client or OllamaModelClient(configuration)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await decision_model.aclose()

    app = FastAPI(title="Habitat VLM Backend", lifespan=lifespan)

    @app.exception_handler(RequestValidationError)
    async def request_validation_error(_: Request, __: RequestValidationError) -> JSONResponse:
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
        try:
            proposal, inference_ms = await decision_model.propose(observation)
            validate_proposal_target(proposal, observation)
        except ModelError as error:
            status_code = 504 if error.code == "inference_timeout" else 502
            return JSONResponse(
                status_code=status_code,
                content={"error": {"code": error.code, "message": str(error)}},
            )
        except ValueError as error:
            return JSONResponse(
                status_code=422,
                content={"error": {"code": "invalid_proposal", "message": str(error)}},
            )

        return StepResponse(
            session_id=observation.session_id,
            request_id=observation.request_id,
            observation_id=observation.observation_id,
            action_id=uuid4(),
            proposal=proposal,
            inference_ms=inference_ms,
        )

    return app


app = create_app()