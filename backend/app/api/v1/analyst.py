"""The AI Analyst endpoint: Milestone 9's one workflow, a start/sit explanation.

Thin, like the others: request/response translation only. The agent loop and the tools it
calls live in app/ai/.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.ai import agent
from app.db.session import get_db
from app.schemas.analyst import StartSitRequest, StartSitResponse, ToolCall

router = APIRouter(tags=["analyst"])


@router.post("/analyst/start-sit", response_model=StartSitResponse)
def start_sit(
    request: StartSitRequest,
    db: Session = Depends(get_db),  # noqa: B008 — idiomatic FastAPI DI
) -> StartSitResponse:
    message = agent.start_sit_message(
        [c.model_dump() for c in request.candidates], week=request.week, scoring=request.scoring
    )
    try:
        reply = agent.ask(db, message)
    except agent.AgentConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except agent.AgentRoundLimitExceeded as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return StartSitResponse(
        explanation=reply.text,
        tool_calls=[
            ToolCall(name=t.name, arguments=t.arguments, result=t.result)
            for t in reply.tool_calls
        ],
    )
