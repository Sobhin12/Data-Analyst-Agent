"""Integration tests for the FastAPI backend (api.py), with every LLM call
stubbed out -- proves /health and /query work through the real compiled
graph, not just that the route wiring is correct.
"""

from unittest.mock import patch

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

import api
from agent.nodes import analyst, orchestrator, sql_agent


class TextStubLLM:
    def __init__(self, contents):
        self.contents = contents
        self.i = 0

    def invoke(self, prompt):
        content = self.contents[min(self.i, len(self.contents) - 1)]
        self.i += 1
        return AIMessage(content=content)


class ToolCallingStubLLM:
    def __init__(self, responses):
        self.responses = responses
        self.i = 0

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        response = self.responses[min(self.i, len(self.responses) - 1)]
        self.i += 1
        return response


def _tool_call(name, args, call_id):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}])


def _final():
    return AIMessage(content="done", tool_calls=[])


_PLAN = (
    '{"needs_clarification": false, "sub_queries": ["total number of artists"], '
    '"aggregation_strategy": "single", "reasoning": "single aggregate"}'
)


def test_health_ok():
    with TestClient(api.app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_query_returns_final_report_without_sql_by_default():
    sql_agent_responses = [
        _tool_call("execute_sql", {"sql": "SELECT COUNT(*) FROM Artist"}, "c1"),
        _final(),
    ]
    with (
        patch.object(orchestrator, "get_llm", return_value=TextStubLLM([_PLAN])),
        patch.object(sql_agent, "get_llm", return_value=ToolCallingStubLLM(sql_agent_responses)),
        patch.object(analyst, "get_llm", return_value=TextStubLLM(["There are 275 artists."])),
    ):
        with TestClient(api.app) as client:
            response = client.post("/query", json={"query": "how many artists are there?"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "done"
    assert body["final_report"] == "There are 275 artists."
    assert "session_id" in body and body["session_id"]
    assert "sub_queries" not in body


def test_query_debug_flag_includes_sub_queries_in_order():
    sql_agent_responses = [
        _tool_call("execute_sql", {"sql": "SELECT COUNT(*) FROM Artist"}, "c1"),
        _final(),
    ]
    with (
        patch.object(orchestrator, "get_llm", return_value=TextStubLLM([_PLAN])),
        patch.object(sql_agent, "get_llm", return_value=ToolCallingStubLLM(sql_agent_responses)),
        patch.object(analyst, "get_llm", return_value=TextStubLLM(["There are 275 artists."])),
    ):
        with TestClient(api.app) as client:
            response = client.post(
                "/query", json={"query": "how many artists are there?", "debug": True}
            )

    body = response.json()
    assert len(body["sub_queries"]) == 1
    sub = body["sub_queries"][0]
    assert sub["intent"] == "total number of artists"
    assert sub["sql"] == "SELECT COUNT(*) FROM Artist"
    assert sub["row_count"] >= 1
    assert len(sub["rows"]) == sub["row_count"]


def test_query_reuses_provided_session_id():
    sql_agent_responses = [
        _tool_call("execute_sql", {"sql": "SELECT COUNT(*) FROM Artist"}, "c1"),
        _final(),
    ]
    with (
        patch.object(orchestrator, "get_llm", return_value=TextStubLLM([_PLAN])),
        patch.object(sql_agent, "get_llm", return_value=ToolCallingStubLLM(sql_agent_responses)),
        patch.object(analyst, "get_llm", return_value=TextStubLLM(["There are 275 artists."])),
    ):
        with TestClient(api.app) as client:
            response = client.post(
                "/query", json={"query": "how many artists are there?", "session_id": "fixed-session"}
            )

    assert response.json()["session_id"] == "fixed-session"
