"""SQL agent: bounded tool-calling loop + independent result validator.

See docs/text_to_sql_agent_design_spec.md §3.3, §3.6, §3.7, §8.
"""

import json
import logging
from dataclasses import dataclass

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

import config
from agent.llm import get_llm
from agent.state import AgentState, ExecutionResult, SubQuery
from agent.tools.db_tools import tools_sql_agent

logger = logging.getLogger(__name__)

_TOOLS_BY_NAME = {t.name: t for t in tools_sql_agent}

_SYSTEM_PROMPT = """You are a SQL agent working against a SQLite database. You have tools to explore
the schema, inspect sample values and column stats, and execute SQL.

Rules:
- Use tools as needed before writing SQL -- don't guess table or column names.
- Match string filter values exactly as they appear in sample_values.
- SELECT only. Never write INSERT/UPDATE/DELETE/DROP/CREATE/ALTER.
- Prefer explicit JOINs. Add LIMIT 1000 unless the query is an aggregate.
- If execute_sql returns an error, read the corrective_hint and adjust -- don't
  repeat the same failing query.
- Once execute_sql succeeds with a result you're confident answers the intent,
  stop calling tools.
"""

_CORRECTIVE_HINTS = {
    "SYNTAX_ERROR": "The SQL has a syntax error. Fix the syntax; the schema is still valid.",
    "UNKNOWN_COLUMN": "That column doesn't exist. Call explore_schema again to find the correct column name.",
    "UNKNOWN_TABLE": "That table doesn't exist. Call explore_schema again to find the correct table name.",
    "TYPE_MISMATCH": "Comparing incompatible types. Cast the value or change the filter's type.",
    "AMBIGUOUS_COLUMN": "That column exists in multiple tables. Qualify it with the table name.",
    "TIMEOUT": "The query was too slow. Simplify it or add a more selective filter.",
    "FORBIDDEN_STATEMENT": "Only a single read-only SELECT is allowed. Remove any second statement or non-SELECT keywords.",
    "UNKNOWN": "Re-explore the schema and reconsider the query from scratch.",
}


def _invoke_tool(call: dict) -> dict:
    tool_obj = _TOOLS_BY_NAME.get(call["name"])
    if tool_obj is None:
        return {"success": False, "error": f"Unknown tool: {call['name']}", "error_type": "UNKNOWN"}
    try:
        result = tool_obj.invoke(call["args"])
    except Exception as e:  # tool itself raised -- surface it as a normal failure, don't crash the loop
        return {"success": False, "error": str(e), "error_type": "UNKNOWN"}
    return result if isinstance(result, dict) else {"success": True, "value": result}


def sql_agent_loop(sub_query: SubQuery, state: AgentState, retry_note: str | None = None) -> SubQuery:
    """Runs the bounded tool-calling loop for one sub-query. See spec §3.3."""
    logger.info("sql_agent: starting loop for sub-query %r", sub_query.intent)
    llm_with_tools = get_llm().bind_tools(tools_sql_agent)

    messages = [
        SystemMessage(content=_SYSTEM_PROMPT),
        HumanMessage(
            content=(
                f"Sub-query intent: {sub_query.intent}\n"
                f"Overall question (for context): {state.get('resolved_query', '')}"
            )
        ),
    ]
    if retry_note:
        logger.info("sql_agent: retrying with validator feedback: %s", retry_note)
        messages.append(HumanMessage(content=retry_note))

    while sub_query.tool_call_count < config.MAX_TOOL_CALLS:
        if state["total_tool_calls"] >= config.MAX_TOTAL_TOOL_CALLS:
            logger.warning(
                "sql_agent: total_tool_calls backstop reached (%d) -- stopping before this sub-query got a fresh call",
                state["total_tool_calls"],
            )
            sub_query.status = "failed"
            return sub_query

        response = llm_with_tools.invoke(messages)
        messages.append(response)

        if not response.tool_calls:
            sub_query.status = "done" if sub_query.result is not None else "failed"
            logger.info("sql_agent: model finished, status=%s", sub_query.status)
            return sub_query

        for call in response.tool_calls:
            sub_query.tool_call_count += 1
            state["total_tool_calls"] += 1
            logger.info(
                "sql_agent: tool call #%d -> %s(%s)",
                sub_query.tool_call_count, call["name"], call["args"],
            )
            result = _invoke_tool(call)

            if call["name"] == "execute_sql":
                if result.get("success"):
                    logger.info(
                        "sql_agent: execute_sql succeeded, %d row(s)", result.get("row_count", 0)
                    )
                    sub_query.sql = call["args"].get("sql")
                    sub_query.result = ExecutionResult(
                        success=True,
                        rows=result.get("rows", []),
                        columns=result.get("columns", []),
                        row_count=result.get("row_count", 0),
                    )
                else:
                    logger.warning(
                        "sql_agent: execute_sql failed [%s]: %s (retry %d/%d)",
                        result.get("error_type"), result.get("error"),
                        sub_query.sql_retry_count + 1, config.MAX_SQL_RETRIES,
                    )
                    sub_query.sql_retry_count += 1
                    sub_query.error_history.append(result.get("error", ""))
                    result = dict(result)
                    result["corrective_hint"] = _CORRECTIVE_HINTS.get(
                        result.get("error_type"), _CORRECTIVE_HINTS["UNKNOWN"]
                    )

            messages.append(
                ToolMessage(content=json.dumps(result, default=str), tool_call_id=call["id"])
            )

            if (
                call["name"] == "execute_sql"
                and not result.get("success")
                and sub_query.sql_retry_count >= config.MAX_SQL_RETRIES
            ):
                logger.warning("sql_agent: sql_retry_count cap reached, giving up on this sub-query")
                sub_query.status = "failed"
                return sub_query

            if state["total_tool_calls"] >= config.MAX_TOTAL_TOOL_CALLS:
                logger.warning(
                    "sql_agent: total_tool_calls backstop reached (%d) mid-loop",
                    state["total_tool_calls"],
                )
                sub_query.status = "failed"
                return sub_query

    logger.warning("sql_agent: tool_call_count cap (%d) reached without a final answer", config.MAX_TOOL_CALLS)
    sub_query.status = "failed"  # tool_call_count budget exhausted without a final answer
    return sub_query


@dataclass
class QueryIntent:
    type: str  # "aggregate" | "fetch" | "existence"
    expects_data: bool
    expects_large_result: bool


_AGGREGATE_WORDS = ("total", "sum", "average", "avg", "count", "how many", "top", "rank", "compare")
_EXISTENCE_WORDS = ("does", "is there", "exist", "any ")
_EXPECTS_LARGE_WORDS = ("all ", "every ", "entire", "complete list", "everything")


def infer_intent(intent_text: str) -> QueryIntent:
    """Lightweight heuristic -- good enough to route the validator's checks, not a full parser."""
    lowered = intent_text.lower()
    if any(w in lowered for w in _EXISTENCE_WORDS):
        return QueryIntent(type="existence", expects_data=False, expects_large_result=False)
    if any(w in lowered for w in _AGGREGATE_WORDS):
        return QueryIntent(type="aggregate", expects_data=True, expects_large_result=False)
    # A plain fetch ("show me sales") is usually missing a filter if it returns
    # a huge result -- only an explicit "all"/"every"/"entire" signals that a
    # large result is actually expected.
    expects_large = any(w in lowered for w in _EXPECTS_LARGE_WORDS)
    return QueryIntent(type="fetch", expects_data=True, expects_large_result=expects_large)


def validate_result(result: ExecutionResult, intent: QueryIntent) -> tuple[str, str]:
    """See spec §3.7. Returns (verdict, reason) where verdict is VALID or REQUERY_NEEDED."""
    if result.row_count == 0:
        if intent.type == "aggregate":
            return "VALID", "Zero is a valid aggregate result (e.g. no matching rows)"
        if intent.expects_data:
            return "REQUERY_NEEDED", "Zero rows returned for a data fetch query"
        return "VALID", "Zero rows is a valid answer for an existence check"

    if result.row_count > config.LARGE_RESULT_ROW_THRESHOLD and not intent.expects_large_result:
        return "REQUERY_NEEDED", "Result set too large -- query may be missing a filter"

    return "VALID", "Result looks plausible"


def sql_agent_node(state: AgentState) -> AgentState:
    idx = state["current_sub_query_idx"]
    sub_query = state["sub_queries"][idx]
    logger.info("sql_agent_node: processing sub-query[%d] = %r", idx, sub_query.intent)

    retry_note = None
    while True:
        sql_agent_loop(sub_query, state, retry_note=retry_note)

        if sub_query.status != "done" or sub_query.result is None:
            break  # the tool loop itself failed (budget exhausted or model gave up)

        intent = infer_intent(sub_query.intent)
        verdict, reason = validate_result(sub_query.result, intent)
        logger.info("result_validator: verdict=%s (%s)", verdict, reason)
        if verdict == "VALID":
            break

        if (
            sub_query.sql_retry_count >= config.MAX_SQL_RETRIES
            or state["total_tool_calls"] >= config.MAX_TOTAL_TOOL_CALLS
        ):
            logger.warning("sql_agent_node: validator rejected result and no budget remains, giving up")
            sub_query.status = "failed"
            sub_query.error_history.append(reason)
            break

        logger.info(
            "sql_agent_node: validator rejected result, retrying (sql_retry_count -> %d)",
            sub_query.sql_retry_count + 1,
        )
        sub_query.sql_retry_count += 1
        sub_query.error_history.append(reason)
        retry_note = (
            f"Your previous query executed successfully, but the result looks wrong: {reason}. "
            f"Previous SQL: {sub_query.sql}. Reconsider and try again."
        )
        sub_query.status = "pending"

    logger.info("sql_agent_node: sub-query[%d] finished with status=%s", idx, sub_query.status)
    state["sub_queries"][idx] = sub_query
    return state
