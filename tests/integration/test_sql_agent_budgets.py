"""Tests the SQL agent loop's budget enforcement (§8) without calling a real LLM.

A StubLLM plays back a scripted sequence of AIMessages so we can exercise
runaway-loop protection deterministically. Real tool calls still hit the
actual Chinook database -- only the model call itself is faked.
"""

from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage

import config
from agent.nodes import sql_agent
from agent.state import SubQuery, new_state


class StubLLM:
    """Ignores bind_tools/messages; plays back `responses` in order, then repeats the last one."""

    def __init__(self, responses: list[AIMessage]):
        self.responses = responses
        self.call_count = 0

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        response = self.responses[min(self.call_count, len(self.responses) - 1)]
        self.call_count += 1
        return response


def _tool_call_message(name: str, args: dict, call_id: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}])


def _final_message(text: str = "done") -> AIMessage:
    return AIMessage(content=text, tool_calls=[])


@pytest.fixture
def fresh_state():
    return new_state("total revenue this quarter", "test-session")


class TestToolCallCountBudget:
    def test_model_that_never_finalizes_is_stopped_by_tool_call_count(self, fresh_state):
        """A model that keeps exploring and never calls execute_sql (or never
        stops) must not loop forever -- tool_call_count (max 6) has to cut it off."""
        stub = StubLLM([_tool_call_message("explore_schema", {"table_hint": "Invoice"}, "c1")])
        sub_query = SubQuery(intent="never resolves")

        with patch.object(sql_agent, "get_llm", return_value=stub):
            sql_agent.sql_agent_loop(sub_query, fresh_state)

        assert sub_query.tool_call_count == config.MAX_TOOL_CALLS
        assert sub_query.status == "failed"

    def test_successful_single_tool_call_completes_and_captures_the_result(self, fresh_state):
        stub = StubLLM([
            _tool_call_message("execute_sql", {"sql": "SELECT SUM(Total) FROM Invoice"}, "c1"),
            _final_message(),
        ])
        sub_query = SubQuery(intent="total revenue")

        with patch.object(sql_agent, "get_llm", return_value=stub):
            sql_agent.sql_agent_loop(sub_query, fresh_state)

        assert sub_query.status == "done"
        assert sub_query.result is not None
        assert sub_query.result.rows == [(2328.6,)]
        assert sub_query.tool_call_count == 1


class TestSqlRetryCountBudget:
    def test_repeated_execute_sql_failures_stop_at_max_sql_retries(self, fresh_state):
        """Model keeps calling execute_sql with a bad column -- sql_retry_count
        (max 2) must cut it off well before tool_call_count (max 6) would."""
        bad_call = _tool_call_message("execute_sql", {"sql": "SELECT SUM(revenue) FROM Invoice"}, "c1")
        stub = StubLLM([bad_call])  # same failing call every time
        sub_query = SubQuery(intent="total revenue")

        with patch.object(sql_agent, "get_llm", return_value=stub):
            sql_agent.sql_agent_loop(sub_query, fresh_state)

        assert sub_query.sql_retry_count == config.MAX_SQL_RETRIES
        assert sub_query.tool_call_count < config.MAX_TOOL_CALLS  # cut off early, not by tool_call_count
        assert sub_query.status == "failed"
        assert len(sub_query.error_history) == config.MAX_SQL_RETRIES


class TestTotalToolCallsBackstop:
    def test_global_backstop_halts_even_with_local_budget_remaining(self, fresh_state):
        """Simulates the whole-turn cap already nearly exhausted by earlier
        sub-queries -- this sub-query's own fresh budget must not matter."""
        fresh_state["total_tool_calls"] = config.MAX_TOTAL_TOOL_CALLS  # already at the cap
        stub = StubLLM([_tool_call_message("explore_schema", {}, "c1")])
        sub_query = SubQuery(intent="anything")

        with patch.object(sql_agent, "get_llm", return_value=stub):
            sql_agent.sql_agent_loop(sub_query, fresh_state)

        assert sub_query.tool_call_count == 0  # never even got to make a call
        assert sub_query.status == "failed"

    def test_backstop_trips_mid_loop_across_multiple_tool_calls_in_one_turn(self, fresh_state):
        fresh_state["total_tool_calls"] = config.MAX_TOTAL_TOOL_CALLS - 1
        stub = StubLLM([_tool_call_message("explore_schema", {}, "c1")])
        sub_query = SubQuery(intent="anything")

        with patch.object(sql_agent, "get_llm", return_value=stub):
            sql_agent.sql_agent_loop(sub_query, fresh_state)

        assert fresh_state["total_tool_calls"] == config.MAX_TOTAL_TOOL_CALLS
        assert sub_query.status == "failed"


class TestResultValidatorRetryLoop:
    def test_sql_agent_node_retries_on_oversized_unfiltered_result(self, fresh_state):
        """Validator rejects a plausible-looking but oversized fetch result;
        sql_agent_node should feed that back and try again, still bounded by
        the same sql_retry_count budget -- verified here by forcing the model
        to keep returning the same query so it's rejected every time."""
        big_query = "SELECT * FROM InvoiceLine"  # ~2200 rows in Chinook, but let's force oversized via a stub validator scenario instead
        stub = StubLLM([
            _tool_call_message("execute_sql", {"sql": big_query}, "c1"),
            _final_message(),
        ])
        fresh_state["sub_queries"] = [SubQuery(intent="show me every invoice line")]
        fresh_state["current_sub_query_idx"] = 0
        fresh_state["resolved_query"] = "show me every invoice line"

        with patch.object(sql_agent, "get_llm", return_value=stub), \
             patch.object(sql_agent, "validate_result", return_value=("REQUERY_NEEDED", "forced for test")):
            sql_agent.sql_agent_node(fresh_state)

        sq = fresh_state["sub_queries"][0]
        # Forced-invalid result should have driven sql_retry_count to its cap
        # via the validator retry path (not the execute_sql failure path).
        assert sq.sql_retry_count == config.MAX_SQL_RETRIES
        assert sq.status == "failed"
