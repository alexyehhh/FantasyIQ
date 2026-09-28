"""The AI Analyst endpoint: Milestone 9's one workflow, a start/sit explanation.

Thin, like the others: request/response translation only. The agent loop and the tools it
calls live in app/ai/.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.ai import agent
from app.ai.rate_limit import RateLimiter, RateLimitExceeded
from app.core.config import get_settings
from app.db.session import get_db
from app.schemas.analyst import StartSitRequest, StartSitResponse, ToolCall

router = APIRouter(tags=["analyst"])

_settings = get_settings()
# Module-level so it persists across requests in this process; tests monkeypatch it directly
# rather than going through settings, since it needs to hold state between calls.
_limiter = RateLimiter(
    [
        (_settings.analyst_rate_limit_per_minute, 60),
        (_settings.analyst_rate_limit_per_day, 86400),
    ]
)


@router.post("/analyst/start-sit", response_model=StartSitResponse)
def start_sit(
    request: StartSitRequest,
    db: Session = Depends(get_db),  # noqa: B008 — idiomatic FastAPI DI
) -> StartSitResponse:
    try:
        _limiter.check()
    except RateLimitExceeded as exc:
        raise HTTPException(
            status_code=429,
            detail=f"Too many analyst requests; try again in {exc.retry_after:.0f}s",
            headers={"Retry-After": str(round(exc.retry_after))},
        ) from exc

    message = agent.start_sit_message(
        [c.model_dump() for c in request.candidates], week=request.week, scoring=request.scoring
    )
    try:
        reply = agent.ask(db, message)
    except agent.AgentConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except agent.AgentRoundLimitExceeded as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except agent.AgentUpstreamError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return StartSitResponse(
        explanation=reply.text,
        tool_calls=[
            ToolCall(name=t.name, arguments=t.arguments, result=t.result)
            for t in reply.tool_calls
        ],
    )
