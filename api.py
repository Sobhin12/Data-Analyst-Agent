"""FastAPI backend for the text-to-SQL agent.

Two endpoints only: GET /health and POST /query. Reuses the exact same
turn-input construction as the CLI and Streamlit front ends -- see
main.py's _fresh_turn_input.

    uvicorn api:app --reload

By default /query returns only the plain-English report (no SQL, no raw
rows), matching the project's "no SQL is ever shown to the user" principle.
Pass "debug": true in the request body to opt into a sub_queries array
(intent -> sql -> data rows, in execution order) for callers that want to
inspect the agent's work.
"""

import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from agent.graph import build_graph
from agent.logging_config import configure_logging
from db.loader import get_engine
from main import _fresh_turn_input

logger = logging.getLogger(__name__)

_graph = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    global _graph
    _graph = build_graph()
    yield


app = FastAPI(title="Data Analyst Agent API", lifespan=lifespan)


class QueryRequest(BaseModel):
    query: str
    session_id: str | None = None
    debug: bool = False


@app.get("/health")
def health():
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as e:
        logger.exception("health check: database unreachable")
        raise HTTPException(status_code=503, detail=f"database unreachable: {e}")
    return {"status": "ok"}


@app.post("/query")
def query(req: QueryRequest):
    session_id = req.session_id or str(uuid.uuid4())
    thread_config = {"configurable": {"thread_id": session_id}}

    logger.info("api: turn start: %r (session=%s)", req.query, session_id)
    try:
        result = _graph.invoke(_fresh_turn_input(req.query), thread_config)
    except Exception:
        logger.exception("api: turn failed with an unhandled exception")
        raise HTTPException(status_code=500, detail="internal error")
    logger.info("api: turn end: status=%s (session=%s)", result.get("status"), session_id)

    response = {
        "session_id": session_id,
        "status": result.get("status", "failed"),
        "final_report": result.get("final_report"),
        "assumption_note": result.get("assumption_note"),
        "clarification_request": result.get("clarification_request"),
        "option_cards": result.get("option_cards"),
    }

    if req.debug:
        # Ordered list, execution order: index i -> "intent -> sql -> data rows".
        response["sub_queries"] = [
            {
                "intent": sq.intent,
                "sql": sq.sql,
                "columns": sq.result.columns if sq.result else [],
                "rows": sq.result.rows if sq.result else [],
                "row_count": sq.result.row_count if sq.result else 0,
            }
            for sq in result.get("sub_queries", [])
        ]

    return response
