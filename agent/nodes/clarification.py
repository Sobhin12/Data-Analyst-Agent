"""Clarification node: deterministic memory-based resolution.

Ambiguity classification itself lives in the orchestrator now -- it's the
node that actually needs to know whether it can plan, so it's the one
that decides whether to ask. See docs/text_to_sql_agent_design_spec.md
§3.1, §7, §10 (note: §3.1's LLM classifier step is superseded by
orchestrator.plan_initial, see agent/nodes/orchestrator.py).
"""

import logging
import re

from agent.state import AgentState

logger = logging.getLogger(__name__)

_TIME_WORDS = re.compile(
    r"\b(today|yesterday|week|month|quarter|year|q[1-4]|ytd|"
    r"last\s+\d+\s+(day|week|month|year)s?|this\s+(week|month|quarter|year)|"
    r"\d{4})\b",
    re.IGNORECASE,
)
_REGION_WORDS = re.compile(r"\b(north|south|east|west|region)\b", re.IGNORECASE)

_QUESTION_TEMPLATES = {
    "period": (
        "Which time period? [Last 30 days] [This quarter] [This year]",
        ["Last 30 days", "This quarter", "This year"],
    ),
    "region": (
        "Which region? [North] [South] [East] [West] [All regions]",
        ["North", "South", "East", "West", "All regions"],
    ),
}


def detect_missing_filter(query: str, active_filters: dict) -> str | None:
    """Cheap, deterministic check: does memory already have a filter the query omits?"""
    if "period" in active_filters and not _TIME_WORDS.search(query):
        return "period"
    if "region" in active_filters and not _REGION_WORDS.search(query):
        return "region"
    return None


def memory_can_resolve(query: str, state: AgentState) -> tuple[bool, str]:
    """Fast, free heuristic path, tried before orchestrator.plan_initial's LLM call (§10).

    Deliberately narrow: it only fills a simple missing categorical filter
    from active_filters. Richer cases ("same as last week but for Q2") are
    left to the orchestrator's own planning judgment, since faking that with
    regex would be more fragile than just asking the model.
    """
    active_filters = state.get("active_filters") or {}
    if not active_filters or not state.get("turn_history"):
        return False, ""

    missing_filter = detect_missing_filter(query, active_filters)
    if missing_filter:
        value = active_filters[missing_filter]
        return True, f"Using {missing_filter}: {value} from prior context"

    return False, ""


def build_single_question(missing_param: str) -> str:
    """Rule: offer choices, not open text; never ask more than one thing at once."""
    template = _QUESTION_TEMPLATES.get(missing_param)
    if template:
        return template[0]
    return f"Could you clarify the {missing_param or 'missing detail'} for this question?"


def clarification_node(state: AgentState) -> AgentState:
    """Deterministic pre-check only. If a known filter was silently carried
    over from a prior turn, resolve here for free; otherwise pass the raw
    query through unchanged and let orchestrator.plan_initial decide whether
    it has enough to plan or needs to ask the user."""
    query = state["raw_query"]
    logger.info("clarification: query=%r", query)

    can_resolve, resolution = memory_can_resolve(query, state)
    if can_resolve:
        logger.info("clarification: resolved silently from memory (%s)", resolution)
        state["assumption_note"] = resolution
    else:
        logger.info("clarification: no memory shortcut, passing through to orchestrator")

    state["resolved_query"] = query
    state["ambiguity_type"] = "clear"
    return state
