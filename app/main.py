"""FastAPI entrypoint.

Route handlers stay thin on purpose - they parse the request, call into
`app.assistant`, and format the response. All the logic worth unit testing
lives in modules that don't import FastAPI at all, so those tests run in
milliseconds with no ASGI server involved.
"""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app import knowledge_base as kb
from app.assistant import TurnMeta, handle_turn
from app.config import ConfigError, get_settings
from app.gemini_client import GeminiClient, GeminiUnavailableError
from app.models import ChatRequest, HealthResponse
from app.rate_limiter import FixedWindowRateLimiter

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("fanpath")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Builds long-lived, expensive objects once per process, not per request."""
    try:
        settings = get_settings()
    except ConfigError as exc:
        logger.error("Startup aborted - configuration problem: %s", exc)
        raise
    app.state.settings = settings
    app.state.gemini = GeminiClient(settings)
    app.state.limiter = FixedWindowRateLimiter(settings.rate_limit_per_minute)
    logger.info("FanPath ready - venue=%s model=%s", kb.venue_name(), settings.gemini_model)
    yield


app = FastAPI(title="FanPath", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    """Serves the single-page frontend."""
    return FileResponse("static/index.html")


@app.get("/healthz", response_model=HealthResponse)
async def healthz() -> HealthResponse:
    """Liveness check - confirms the process is up and venue data loaded."""
    return HealthResponse(status="ok", venue=kb.venue_name())


def _sse(event: str, data: dict[str, Any]) -> str:
    """Formats one Server-Sent Events record.

    Args:
        event: SSE event name (e.g. "meta", "token", "done", "error").
        data: JSON-serializable payload for this event.

    Returns:
        A complete SSE record, including the trailing blank line.
    """
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@app.post("/api/chat")
async def chat(request: ChatRequest, http_request: Request) -> StreamingResponse:
    """Streams an assistant reply as Server-Sent Events.

    Event sequence: one `meta` event (see TurnMeta), any number of `token`
    events, then either `done` or `error`.
    """
    # NOTE: behind a reverse proxy this would need X-Forwarded-For handling,
    # or every fan shares one rate-limit bucket. Fine for local/demo use;
    # flagged here so it isn't mistaken for a production-ready setup.
    client_key = http_request.client.host if http_request.client else "unknown"
    if not http_request.app.state.limiter.allow(client_key):
        raise HTTPException(status_code=429, detail="Too many requests - please slow down.")

    settings = http_request.app.state.settings
    gemini = http_request.app.state.gemini

    async def event_stream():
        """Runs one turn and formats each step as an SSE record."""
        try:
            async for item in handle_turn(
                settings,
                gemini,
                message=request.message,
                language=request.language,
                current_zone=request.current_zone,
                accessibility_needs=request.accessibility_needs,
            ):
                if isinstance(item, TurnMeta):
                    yield _sse("meta", {"category": item.category, "eta_minutes": item.eta_minutes})
                else:
                    yield _sse("token", {"text": item})
            yield _sse("done", {})
        except GeminiUnavailableError as exc:
            logger.warning("Gemini unavailable: %s", exc)
            yield _sse("error", {"message": str(exc)})

    return StreamingResponse(event_stream(), media_type="text/event-stream")
