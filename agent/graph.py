"""LangGraph wiring. See docs/text_to_sql_agent_design_spec.md §2 for the node map."""

import logging

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from agent.nodes.analyst import analyst_node
from agent.nodes.clarification import clarification_node
from agent.nodes.orchestrator import orchestrator_node
from agent.nodes.sql_agent import sql_agent_node
from agent.state import AgentState

logger = logging.getLogger(__name__)


def advance_sub_query_node(state: AgentState) -> AgentState:
    state["current_sub_query_idx"] += 1
    return state


def route_after_clarification(state: AgentState) -> str:
    # "awaiting_user" ends this turn's graph run -- the CLI surfaces the
    # clarification_request/option_cards and starts a fresh invoke() on the
    # same thread_id once the user answers. See README for why this simpler
    # pattern was used instead of LangGraph's interrupt()/resume machinery.
    destination = END if state.get("status") == "awaiting_user" else "orchestrator"
    logger.debug("route: clarification -> %s", destination)
    return destination


def route_after_sql_agent(state: AgentState) -> str:
    idx = state["current_sub_query_idx"]
    destination = "advance_sub_query" if idx + 1 < len(state["sub_queries"]) else "analyst"
    logger.debug("route: sql_agent -> %s (sub-query %d/%d)", destination, idx + 1, len(state["sub_queries"]))
    return destination


def route_after_analyst(state: AgentState) -> str:
    # analyst_node sets status back to "running" when it issues a refine
    # request (§9) -- otherwise the turn is done (success or graceful failure).
    destination = "orchestrator" if state.get("status") == "running" else END
    logger.debug("route: analyst -> %s", destination)
    return destination


def build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("clarification", clarification_node)
    graph.add_node("orchestrator", orchestrator_node)
    graph.add_node("sql_agent", sql_agent_node)
    graph.add_node("advance_sub_query", advance_sub_query_node)
    graph.add_node("analyst", analyst_node)

    graph.add_edge(START, "clarification")
    graph.add_conditional_edges(
        "clarification", route_after_clarification, {"orchestrator": "orchestrator", END: END}
    )
    graph.add_edge("orchestrator", "sql_agent")
    graph.add_conditional_edges(
        "sql_agent",
        route_after_sql_agent,
        {"advance_sub_query": "advance_sub_query", "analyst": "analyst"},
    )
    graph.add_edge("advance_sub_query", "sql_agent")
    graph.add_conditional_edges(
        "analyst", route_after_analyst, {"orchestrator": "orchestrator", END: END}
    )

    checkpointer = InMemorySaver()
    return graph.compile(checkpointer=checkpointer)
