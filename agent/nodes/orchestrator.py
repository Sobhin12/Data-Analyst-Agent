"""Orchestrator node: ambiguity gate, sub-query planning, and analyst-driven refinement.

Ambiguity is decided here rather than in a separate upfront classifier
(agent/nodes/clarification.py) because the two questions are really one
question: "can I turn this into a concrete plan?" A standalone classifier
scoring "does this lack a filter" in the abstract flags queries that don't
need one at all (e.g. "total number of artists") and, once a filter shows
up in memory, tends to demand it be re-stated on every later turn. Tying
the ask to an actual failed planning attempt grounds it in whether the
information is really needed.

See docs/text_to_sql_agent_design_spec.md §3.1, §3.2.
"""

import logging

import config
from agent.llm import get_llm, parse_json_response
from agent.nodes.clarification import build_single_question
from agent.state import AgentState, SubQuery

logger = logging.getLogger(__name__)

_PLAN_PROMPT = """You are a query planner for a SQL agent system.

First, decide whether you have enough information to plan this question.
A plain aggregate like "total number of artists" needs no filter at all --
don't ask for one just because it wasn't mentioned. Only ask for
clarification when:
- a filter or metric is referenced but never given a concrete value (e.g.
  "this region", "that same period") and no value for it appears below in
  "known filters", or
- the metric/intent is genuinely ambiguous between multiple distinct readings

If you can plan: decide whether the question needs one SQL query or several
genuinely independent sub-queries. SQL is expressive (GROUP BY, CASE WHEN,
window functions) -- most "compare A vs B" and "trend over time" questions
collapse into a single query. Only split into multiple sub-queries when:
- the pieces need different metrics/tables that can't share one aggregation, or
- a later piece depends on values only knowable after an earlier one runs

Never plan more than {max_sub_queries} sub-queries.

Respond in JSON only, no other text:
{{
  "needs_clarification": false,
  "clarification_type": "missing_filter",
  "missing_param": "",
  "clarification_question": "",
  "interpretations": [],
  "sub_queries": ["<intent for sub-query 1>"],
  "aggregation_strategy": "single",
  "reasoning": "<why this many sub-queries, or why clarification is needed, one sentence>"
}}

User's question: {resolved_query}
Known filters already in play (from prior turns, may not apply here): {active_filters}
"""

_REFINE_PROMPT = """The analyst determined the current results are insufficient to
answer the user's question and requested more data.

Reason given: {refine_request}

Current sub-queries and their intents:
{sub_query_summary}

Decide whether to PATCH one existing sub-query's intent (broaden or adjust it)
or ADD a new sub-query -- only ADD if there is room (max {max_sub_queries} total).

Respond in JSON only, no other text:
{{
  "action": "patch",
  "target_index": 0,
  "new_intent": "<intent text>"
}}
"""


def plan_initial(state: AgentState) -> AgentState:
    logger.info("orchestrator: planning sub-queries for %r", state["resolved_query"])
    llm = get_llm(json_mode=True)
    prompt = _PLAN_PROMPT.format(
        resolved_query=state["resolved_query"],
        max_sub_queries=config.MAX_SUB_QUERIES,
        active_filters=state.get("active_filters") or {},
    )
    response = llm.invoke(prompt)
    plan = parse_json_response(response.content)

    if plan.get("needs_clarification"):
        clarification_type = plan.get("clarification_type") or "vague_intent"
        logger.info(
            "orchestrator: needs clarification (%s): %s",
            clarification_type, plan.get("reasoning"),
        )
        state["ambiguity_type"] = clarification_type
        if clarification_type == "missing_filter":
            state["clarification_request"] = build_single_question(plan.get("missing_param", ""))
        else:
            interpretations = plan.get("interpretations") or []
            state["option_cards"] = [{"label": opt} for opt in interpretations]
        state["status"] = "awaiting_user"
        return state

    intents = plan.get("sub_queries") or [state["resolved_query"]]
    if len(intents) > config.MAX_SUB_QUERIES:
        logger.warning(
            "orchestrator: plan requested %d sub-queries, clipping to cap of %d",
            len(intents), config.MAX_SUB_QUERIES,
        )
    intents = intents[: config.MAX_SUB_QUERIES]  # clip defensively, never crash on a bad plan

    logger.info(
        "orchestrator: planned %d sub-quer%s (strategy=%s): %s",
        len(intents), "y" if len(intents) == 1 else "ies",
        plan.get("aggregation_strategy"), intents,
    )
    logger.debug("orchestrator: reasoning=%s", plan.get("reasoning"))

    state["execution_plan"] = plan
    state["sub_queries"] = [SubQuery(intent=intent) for intent in intents]
    state["current_sub_query_idx"] = 0
    state["status"] = "running"
    return state


def plan_refine(state: AgentState) -> AgentState:
    logger.info("orchestrator: refine requested: %s", state.get("refine_request"))
    llm = get_llm(json_mode=True)
    sub_queries = state["sub_queries"]
    summary = "\n".join(
        f"{i}: {sq.intent} (status={sq.status})" for i, sq in enumerate(sub_queries)
    )
    prompt = _REFINE_PROMPT.format(
        refine_request=state.get("refine_request", ""),
        sub_query_summary=summary,
        max_sub_queries=config.MAX_SUB_QUERIES,
    )
    response = llm.invoke(prompt)
    decision = parse_json_response(response.content)

    action = decision.get("action", "patch")
    new_intent = decision.get("new_intent", "")

    if action == "add" and len(sub_queries) < config.MAX_SUB_QUERIES:
        sub_queries.append(SubQuery(intent=new_intent))
        target_index = len(sub_queries) - 1
    else:
        target_index = decision.get("target_index", len(sub_queries) - 1)
        target_index = max(0, min(target_index, len(sub_queries) - 1))
        if new_intent:
            sub_queries[target_index].intent = new_intent

    logger.info(
        "orchestrator: refine action=%s target_index=%d new_intent=%r",
        action, target_index, sub_queries[target_index].intent,
    )

    # Fresh budget for the affected sub-query -- a different query, its own chance to fail. See spec §8.
    sub_queries[target_index].tool_call_count = 0
    sub_queries[target_index].sql_retry_count = 0
    sub_queries[target_index].status = "pending"

    state["sub_queries"] = sub_queries
    state["current_sub_query_idx"] = target_index
    state["refine_request"] = None
    state["status"] = "running"
    return state


def orchestrator_node(state: AgentState) -> AgentState:
    if state.get("refine_request"):
        return plan_refine(state)
    return plan_initial(state)
