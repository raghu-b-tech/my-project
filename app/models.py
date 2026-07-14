"""Request/response schemas.

Validation happens here, at the boundary, before any handler logic runs -
FastAPI rejects malformed requests with a 422 before our code ever sees
them. This is the first of several defense layers described in
`app/security.py`.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

#: Supported reply languages for the MVP. Gemini can handle far more; this
#: list is what the frontend exposes so QA can cover every option.
SUPPORTED_LANGUAGES = ("en", "es", "fr", "pt", "ar", "de", "ja", "ko", "zh")

#: Accessibility needs the fan can flag, used to steer both which venue
#: facts get retrieved and how the model phrases its answer.
ACCESSIBILITY_TAGS = (
    "wheelchair",
    "low_vision",
    "hard_of_hearing",
    "sensory_sensitivity",
    "service_animal",
)


class ChatRequest(BaseModel):
    """A single turn from a fan."""

    message: str = Field(
        ...,
        min_length=1,
        max_length=2000,  # server-side re-checked/truncated in security.py
        description="The fan's question, in any language.",
    )
    language: str = Field(default="en", description="BCP-47-ish language code.")
    current_zone: str | None = Field(
        default=None, description="Fan's current zone id, e.g. 'gate-c'."
    )
    accessibility_needs: list[str] = Field(
        default_factory=list,
        max_length=len(ACCESSIBILITY_TAGS),
        description="Subset of ACCESSIBILITY_TAGS.",
    )


class HealthResponse(BaseModel):
    status: str
    venue: str
