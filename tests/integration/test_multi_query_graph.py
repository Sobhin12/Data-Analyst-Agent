"""End-to-end test of the multi-sub-query loop through the real compiled graph,
with every LLM call stubbed out. This is the part of the redesign (orchestrator
splitting a question, sql_agent looping per sub-query via advance_sub_query,
analyst combining results) that's easiest to get wrong -- worth proving it
actually works at the graph level, not just per-node.
"""

import uuid
from unittest.mock import patch

from langchain_core.messages import AIMessage

from agent.graph import build_graph
from agent.nodes import analyst, clarification, orchestrator, sql_agent
from main import _fresh_turn_input


class TextStubLLM:
    """For plain-text .invoke(prompt) calls (orchestrator's JSON, analyst's prose)."""

    def __init__(self, contents: list[str]):
        self.contents = contents
        self.i = 0

    def invoke(self, prompt):
        content = self.contents[min(self.i, len(self.contents) - 1)]
        self.i += 1
        return AIMessage(content=content)


class ToolCallingStubLLM:
    """For the SQL agent's bind_tools().invoke(messages) loop."""

    def __init__(self, responses: list[AIMessage]):
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


def test_orchestrator_splits_a_comparison_and_both_sub_queries_run_and_combine():
    orchestrator_plan = (
        '{"sub_queries": ["total revenue for invoices in 2021", '
        '"total revenue for invoices in 2022"], '
        '"aggregation_strategy": "compare", "reasoning": "two distinct years"}'
    )

    sql_agent_responses = [
        _tool_call("execute_sql", {"sql": "SELECT SUM(Total) FROM Invoice WHERE strftime('%Y', InvoiceDate) = '2021'"}, "c1"),
        _final(),
        _tool_call("execute_sql", {"sql": "SELECT SUM(Total) FROM Invoice WHERE strftime('%Y', InvoiceDate) = '2022'"}, "c2"),
        _final(),
    ]

    with (
        patch.object(
            clarification, "score_ambiguity",
            return_value={"missing_filter": 0.0, "vague_intent": 0.0, "memory_resolves": False},
        ),
        patch.object(orchestrator, "get_llm", return_value=TextStubLLM([orchestrator_plan])),
        patch.object(sql_agent, "get_llm", return_value=ToolCallingStubLLM(sql_agent_responses)),
        patch.object(analyst, "get_llm", return_value=TextStubLLM(["2009 revenue was higher than 2010."])),
    ):
        graph = build_graph()
        thread_config = {"configurable": {"thread_id": str(uuid.uuid4())}}
        result = graph.invoke(
            _fresh_turn_input("compare 2021 vs 2022 total revenue"), thread_config
        )

    assert result["status"] == "done"
    assert len(result["sub_queries"]) == 2
    assert all(sq.status == "done" for sq in result["sub_queries"])
    assert result["report_type"] == "comparison"
    assert result["final_report"] == "2009 revenue was higher than 2010."
    # Each sub-query actually ran its own distinct SQL against the real DB.
    assert result["sub_queries"][0].result.rows != result["sub_queries"][1].result.rows
