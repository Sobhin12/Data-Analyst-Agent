"""Clarification node: ambiguity classification + resolution.

See docs/text_to_sql_agent_design_spec.md §3.1, §7, §10.
"""

import re

import config
from agent.llm import get_llm, parse_json_response
from agent.state import AgentState

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
    """Fast heuristic path, tried before the LLM classifier (§10).

    Deliberately narrow: it only fills a simple missing categorical filter
    from active_filters. Richer cases ("same as last week but for Q2") are
    left to the LLM classifier's own memory_resolves field below, since
    faking that with regex would be more fragile than just asking the model.
    """
    active_filters = state.get("active_filters") or {}
    if not active_filters or not state.get("turn_history"):
        return False, ""

    missing_filter = detect_missing_filter(query, active_filters)
    if missing_filter:
        value = active_filters[missing_filter]
        return True, f"Using {missing_filter}: {value} from prior context"

    return False, ""


_CLASSIFIER_PROMPT = """You are an ambiguity classifier for a SQL agent system.

Given the user query below, score it on two dimensions from 0 to 1:
- missing_filter: Does the query lack a required filter (time, region, product, etc.)?
- vague_intent: Is it unclear which metric or KPI the user wants?

Also check the conversation memory to see if any ambiguity is resolvable
from prior context (e.g. "same as last week but for Q2", "now break it down by region").

Respond in JSON only, no other text:
{{
  "missing_filter": 0.0,
  "vague_intent": 0.0,
  "memory_resolves": false,
  "memory_resolution": "",
  "missing_param": "",
  "interpretations": []
}}

Query: {query}
Memory (recent turns and active filters): {memory}
Known filters already in play: {available_filters}
"""


def score_ambiguity(query: str, state: AgentState) -> dict:
    llm = get_llm(json_mode=True)
    memory_context = {
        "active_filters": state.get("active_filters") or {},
        "recent_turns": (state.get("turn_history") or [])[-3:],
    }
    prompt = _CLASSIFIER_PROMPT.format(
        query=query,
        memory=memory_context,
        available_filters=list((state.get("active_filters") or {}).keys()),
    )
    response = llm.invoke(prompt)
    return parse_json_response(response.content)


def build_single_question(missing_param: str) -> str:
    """Rule: offer choices, not open text; never ask more than one thing at once."""
    template = _QUESTION_TEMPLATES.get(missing_param)
    if template:
        return template[0]
    return f"Could you clarify the {missing_param or 'missing detail'} for this question?"


def clarification_node(state: AgentState) -> AgentState:
    query = state["raw_query"]

    can_resolve, resolution = memory_can_resolve(query, state)
    if can_resolve:
        state["resolved_query"] = query
        state["assumption_note"] = resolution
        state["ambiguity_type"] = "clear"
        return state

    scores = score_ambiguity(query, state)
    state["ambiguity_score"] = {
        "missing_filter": scores.get("missing_filter", 0.0),
        "vague_intent": scores.get("vague_intent", 0.0),
    }

    if scores.get("memory_resolves"):
        state["resolved_query"] = query
        state["assumption_note"] = scores.get("memory_resolution") or "Resolved from prior context."
        state["ambiguity_type"] = "clear"
        return state

    if scores.get("missing_filter", 0.0) > config.AMBIGUITY_THRESHOLD:
        state["ambiguity_type"] = "missing_filter"
        state["clarification_request"] = build_single_question(scores.get("missing_param", ""))
        state["status"] = "awaiting_user"
        return state

    if scores.get("vague_intent", 0.0) > config.AMBIGUITY_THRESHOLD:
        state["ambiguity_type"] = "vague_intent"
        state["option_cards"] = [{"label": opt} for opt in scores.get("interpretations", [])]
        state["status"] = "awaiting_user"
        return state

    state["ambiguity_type"] = "clear"
    state["resolved_query"] = query
    return state
