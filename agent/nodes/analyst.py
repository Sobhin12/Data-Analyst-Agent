"""Analyst node: report type classification, sufficiency check, explanation generation.

See docs/text_to_sql_agent_design_spec.md §3.8, §9.
"""

import logging
import re
from datetime import datetime, timezone

import config
from agent.llm import get_llm
from agent.state import AgentState, SubQuery
from agent.tools.analyst_tools import summarize_table

logger = logging.getLogger(__name__)

_RANKING_WORDS = ("top ", "rank", "highest", "lowest", "best", "worst")
_TREND_WORDS = ("trend", "over time", "monthly", "weekly", "growth", "change over")
_ALERT_WORDS = ("anomaly", "unusual", "spike", "spiked", "drop", "dropped")
_COMPARISON_WORDS = ("compare", " vs ", "versus", "difference between")

_REQUESTED_N_PATTERN = re.compile(r"top\s+(\d+)", re.IGNORECASE)
_REGION_PATTERN = re.compile(r"\b(north|south|east|west)\b", re.IGNORECASE)
_PERIOD_PATTERN = re.compile(
    r"\b(this\s+(?:week|month|quarter|year)|last\s+(?:week|month|quarter|year)|"
    r"q[1-4]\s*\d{0,4}|\d{4})\b",
    re.IGNORECASE,
)
_METRIC_WORDS = (
    "revenue", "sales", "profit", "spending", "orders", "customers",
    "invoices", "tracks", "albums", "refunds", "signups",
)


def classify_report_type(resolved_query: str, sub_queries: list[SubQuery]) -> str:
    lowered = resolved_query.lower()
    if any(w in lowered for w in _RANKING_WORDS):
        return "ranking"
    if len(sub_queries) >= 2 or any(w in lowered for w in _COMPARISON_WORDS):
        return "comparison"
    if any(w in lowered for w in _TREND_WORDS):
        return "trend"
    if any(w in lowered for w in _ALERT_WORDS):
        return "alert"
    return "fact"


def extract_requested_n(resolved_query: str) -> int | None:
    match = _REQUESTED_N_PATTERN.search(resolved_query)
    return int(match.group(1)) if match else None


def check_data_sufficiency(
    sub_queries: list[SubQuery], report_type: str, requested_n: int | None = None
) -> bool:
    """Reasons over the whole sub_queries list, not a single result. See spec §3.8."""
    done = [sq for sq in sub_queries if sq.status == "done" and sq.result is not None]

    if report_type == "trend":
        total_rows = sum(sq.result.row_count for sq in done)
        return total_rows >= 3
    if report_type == "comparison":
        return len(done) >= 2
    if report_type == "ranking":
        if not done:
            return False
        return done[0].result.row_count >= (requested_n or 1)
    return len(done) == len(sub_queries)


def _insufficiency_reason(
    report_type: str, sub_queries: list[SubQuery], requested_n: int | None
) -> str:
    if report_type == "trend":
        return "Need at least 3 data points to identify a trend; got fewer."
    if report_type == "comparison":
        done = sum(1 for sq in sub_queries if sq.status == "done")
        return f"Need at least 2 successful sub-queries to compare; only {done} succeeded."
    if report_type == "ranking":
        return f"Asked for top {requested_n or 1}, but got fewer rows than that."
    failed = [sq.intent for sq in sub_queries if sq.status != "done"]
    return f"One or more sub-queries failed to return usable data: {failed}"


def extract_filters(resolved_query: str) -> dict:
    filters = {}
    region_match = _REGION_PATTERN.search(resolved_query)
    if region_match:
        filters["region"] = region_match.group(1).title()
    period_match = _PERIOD_PATTERN.search(resolved_query)
    if period_match:
        filters["period"] = period_match.group(1)
    return filters


def extract_metric(resolved_query: str) -> str | None:
    lowered = resolved_query.lower()
    for word in _METRIC_WORDS:
        if word in lowered:
            return word
    return None


def _build_data_summary(sub_queries: list[SubQuery]) -> str:
    parts = []
    for i, sq in enumerate(sub_queries):
        if sq.status == "done" and sq.result is not None:
            table = summarize_table(sq.result.rows, sq.result.columns)
            parts.append(
                f"Sub-query {i} ({sq.intent}): succeeded, {sq.result.row_count} row(s)\n{table}"
            )
        else:
            last_error = sq.error_history[-1] if sq.error_history else "unknown error"
            parts.append(f"Sub-query {i} ({sq.intent}): FAILED -- {last_error}")
    return "\n\n".join(parts)


_ANALYST_PROMPT = """You are a data analyst explaining query results to a non-technical business user.

Rules:
- Never use technical terms (no "SQL", "rows", "NULL", "JOIN")
- Round numbers to 2 decimal places maximum
- Always give a one-sentence interpretation, not just the number
- If the data shows a trend, name the direction explicitly
- If the data is insufficient to draw a conclusion, say so clearly
- Do not invent numbers not present in the data
- If any part of the question couldn't be answered, say plainly which part,
  and still report on the parts that did succeed

Report type: {report_type}
User's original question: {resolved_query}

Data returned:
{data_summary}

Write the report:
"""


def generate_explanation(state: AgentState, report_type: str) -> str:
    llm = get_llm()
    prompt = _ANALYST_PROMPT.format(
        report_type=report_type,
        resolved_query=state.get("resolved_query") or state["raw_query"],
        data_summary=_build_data_summary(state["sub_queries"]),
    )
    response = llm.invoke(prompt)
    return response.content.strip()


def _append_turn_history(state: AgentState) -> None:
    turn_history = state.get("turn_history") or []
    turn = {
        "turn_id": len(turn_history) + 1,
        "raw_query": state["raw_query"],
        "resolved_query": state.get("resolved_query"),
        "assumptions": [state["assumption_note"]] if state.get("assumption_note") else [],
        "sql_executed": "; ".join(sq.sql for sq in state["sub_queries"] if sq.sql),
        "result_summary": (state.get("final_report") or "")[:200],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    state["turn_history"] = turn_history + [turn]


def analyst_node(state: AgentState) -> AgentState:
    resolved_query = state.get("resolved_query") or state["raw_query"]
    sub_queries = state["sub_queries"]

    report_type = classify_report_type(resolved_query, sub_queries)
    requested_n = extract_requested_n(resolved_query)
    state["report_type"] = report_type

    sufficient = check_data_sufficiency(sub_queries, report_type, requested_n)
    state["data_sufficient"] = sufficient
    logger.info("analyst: report_type=%s sufficient=%s", report_type, sufficient)

    if not sufficient and state.get("refine_count", 0) < config.MAX_REFINE_COUNT:
        reason = _insufficiency_reason(report_type, sub_queries, requested_n)
        state["refine_count"] = state.get("refine_count", 0) + 1
        state["refine_request"] = reason
        state["status"] = "running"
        logger.info(
            "analyst: requesting refine (refine_count -> %d): %s",
            state["refine_count"], reason,
        )
        return state

    if not sufficient:
        logger.warning("analyst: still insufficient at refine cap, reporting best-effort with a caveat")

    report = generate_explanation(state, report_type)
    state["final_report"] = report
    state["status"] = "done"
    logger.info("analyst: final report generated (%d chars)", len(report))

    filters = extract_filters(resolved_query)
    if filters:
        state["active_filters"] = {**(state.get("active_filters") or {}), **filters}
    metric = extract_metric(resolved_query)
    if metric:
        state["last_metric"] = metric

    _append_turn_history(state)
    return state
