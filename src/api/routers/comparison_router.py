"""
/api/comparison — the core product's HTTP surface (build doc 8.3).

Thin router (Rule 2):
  - POST /{projectId}/{jobId}/start          build + assemble a session.
  - GET  /{projectId}/sessions               list a project's sessions.
  - GET  /{projectId}/sessions/{sessionId}   fetch one session.
  - POST /{projectId}/sessions/{sessionId}/chat   routed chat, streamed as SSE.
  - GET  /{projectId}/sessions/{sessionId}/summary   shareable summary.

The chat handler bridges ComparisonService.chat (an async event generator) into
an EventSourceResponse, JSON-encoding each event's payload as the SSE `data`.
"""

import json
import logging
from typing import AsyncIterator

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from src.api.dependencies import (
    UserContext,
    get_comparison_service,
    get_container,
    get_current_user,
)
from src.api.services.comparison_service import ComparisonService
from src.composition.container import AppContainer
from src.core.errors.app_error import AppError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/comparison", tags=["comparison"])


class ChatRequest(BaseModel):
    """Body for a chat turn — the user's free-text message."""

    message: str


@router.post("/{project_id}/{job_id}/start")
async def start_comparison(
    project_id: str,
    job_id: str,
    comparison: ComparisonService = Depends(get_comparison_service),
    user: UserContext = Depends(get_current_user),
):
    """
    Start a comparison: build the session and run Agents 5/6/7 to assemble it.

    Returns the populated ComparisonSession (with its table) for the frontend to
    render. All orchestration lives in the service + pipeline.
    """
    return await comparison.start(project_id, job_id)


@router.get("/{project_id}/sessions")
async def list_sessions(
    project_id: str,
    container: AppContainer = Depends(get_container),
    user: UserContext = Depends(get_current_user),
) -> list:
    """List the project's comparison sessions (single-partition query)."""
    return await container.session_store.list_for_project(project_id)


@router.get("/{project_id}/sessions/{session_id}")
async def get_session(
    project_id: str,
    session_id: str,
    container: AppContainer = Depends(get_container),
    user: UserContext = Depends(get_current_user),
):
    """Return one comparison session, or a 404-class AppError if missing."""
    session = await container.session_store.get(session_id, project_id)
    if session is None:
        raise AppError(
            code="COMPARISON_SESSION_NOT_FOUND",
            message="No comparison session found",
            context={"project_id": project_id, "session_id": session_id},
        )
    return session


@router.post("/{project_id}/sessions/{session_id}/chat")
async def chat(
    project_id: str,
    session_id: str,
    body: ChatRequest,
    comparison: ComparisonService = Depends(get_comparison_service),
    user: UserContext = Depends(get_current_user),
) -> EventSourceResponse:
    """
    Stream a routed chat turn as SSE (build doc 8.3).

    Each event dict from the service (`routed` / `message` / `done` / `error`)
    becomes one SSE frame whose `data` is the JSON-encoded payload. The service
    already wraps errors into an `error` frame, so the stream always ends cleanly.
    """

    async def event_stream() -> AsyncIterator[dict]:
        async for event in comparison.chat(project_id, session_id, body.message):
            yield {"data": json.dumps(event)}

    return EventSourceResponse(event_stream(), sep="\n")


@router.get("/{project_id}/sessions/{session_id}/summary")
async def session_summary(
    project_id: str,
    session_id: str,
    comparison: ComparisonService = Depends(get_comparison_service),
    user: UserContext = Depends(get_current_user),
) -> dict:
    """Return a shareable summary of the session (Agent 11)."""
    return await comparison.summarize(project_id, session_id)
