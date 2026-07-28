"""Orchestrator node: sub-query planning and analyst-driven refinement.

See docs/text_to_sql_agent_design_spec.md §3.2.
"""

import config
from agent.llm import get_llm, parse_json_response
from agent.state import AgentState, SubQuery

_PLAN_PROMPT = """You are a query planner for a SQL agent system.

Decide whether the user's question needs one SQL query or several genuinely
independent sub-queries. SQL is expressive (GROUP BY, CASE WHEN, window
functions) -- most "compare A vs B" and "trend over time" questions collapse
into a single query. Only split into multiple sub-queries when:
- the pieces need different metrics/tables that can't share one aggregation, or
- a later piece depends on values only knowable after an earlier one runs

Never plan more than {max_sub_queries} sub-queries.

Respond in JSON only, no other text:
{{
  "sub_queries": ["<intent for sub-query 1>"],
  "aggregation_strategy": "single",
  "reasoning": "<why this many, one sentence>"
}}

User's question: {resolved_query}
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
    llm = get_llm(json_mode=True)
    prompt = _PLAN_PROMPT.format(
        resolved_query=state["resolved_query"],
        max_sub_queries=config.MAX_SUB_QUERIES,
    )
    response = llm.invoke(prompt)
    plan = parse_json_response(response.content)

    intents = plan.get("sub_queries") or [state["resolved_query"]]
    intents = intents[: config.MAX_SUB_QUERIES]  # clip defensively, never crash on a bad plan

    state["execution_plan"] = plan
    state["sub_queries"] = [SubQuery(intent=intent) for intent in intents]
    state["current_sub_query_idx"] = 0
    state["status"] = "running"
    return state


def plan_refine(state: AgentState) -> AgentState:
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
