"""Interactive CLI for the text-to-SQL agent.

Usage:
    python main.py                  # interactive REPL
    python main.py "your question"  # single-shot mode, prints the report and exits
"""

import logging
import sys
import uuid

from agent.graph import build_graph
from agent.logging_config import configure_logging
from agent.state import new_state

# Deliberately not called at import time: streamlit_app.py and the test suite
# both import _fresh_turn_input from this module, and neither should have the
# side effect of configuring global logging / writing to logs/agent.log just
# from that import. Only the __main__ guard below calls it, since that's the
# only path where this file is genuinely the process entry point.
logger = logging.getLogger(__name__)

# Per-turn fields reset on every new question; active_filters/last_metric/
# last_entity/turn_history are deliberately omitted so they persist from the
# checkpoint across turns -- that's the whole memory design (spec §10).
_RESET_KEYS = [
    "resolved_query", "assumption_note", "clarification_request", "option_cards",
    "execution_plan", "schema_snapshot", "sub_queries", "current_sub_query_idx",
    "total_tool_calls", "report_type", "data_sufficient", "refine_request",
    "refine_count", "final_report", "status", "error", "ambiguity_type",
]


def _fresh_turn_input(raw_query: str) -> dict:
    defaults = new_state(raw_query, session_id="")
    turn_input = {key: defaults[key] for key in _RESET_KEYS}
    turn_input["raw_query"] = raw_query
    return turn_input


def _print_result(result: dict) -> str | None:
    """Prints the agent's response for one turn. Returns the clarification
    question text if the turn is waiting on the user, else None."""
    status = result.get("status")

    if status == "awaiting_user":
        if result.get("clarification_request"):
            print(f"agent> {result['clarification_request']}")
        elif result.get("option_cards"):
            options = ", ".join(o.get("label", "") for o in result["option_cards"])
            print(f"agent> Which do you mean? {options}")
        return "waiting"

    if result.get("final_report"):
        print(f"agent> {result['final_report']}")
        if result.get("assumption_note"):
            print(f"        ({result['assumption_note']})")
        return None

    print(f"agent> Sorry, I couldn't complete that. ({result.get('error') or 'unknown error'})")
    return None


def run_single(query: str) -> None:
    graph = build_graph()
    thread_config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    logger.info("turn start: %r", query)
    try:
        result = graph.invoke(_fresh_turn_input(query), thread_config)
    except Exception:
        logger.exception("turn failed with an unhandled exception")
        print(f"agent> Sorry, something went wrong: {sys.exc_info()[1]}")
        return
    logger.info("turn end: status=%s", result.get("status"))
    _print_result(result)


def run_repl() -> None:
    graph = build_graph()
    session_id = str(uuid.uuid4())
    thread_config = {"configurable": {"thread_id": session_id}}

    print("Text-to-SQL Agent (Chinook). Type 'exit' to quit.")
    print(f"Session: {session_id}\n")

    awaiting_answer_to: str | None = None

    while True:
        try:
            user_input = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if user_input.lower() in ("exit", "quit"):
            break
        if not user_input:
            continue

        if awaiting_answer_to:
            raw_query = f"{awaiting_answer_to} -- {user_input}"
        else:
            raw_query = user_input

        logger.info("turn start: %r", raw_query)
        try:
            result = graph.invoke(_fresh_turn_input(raw_query), thread_config)
        except Exception:
            logger.exception("turn failed with an unhandled exception")
            print(f"agent> Sorry, something went wrong: {sys.exc_info()[1]}")
            awaiting_answer_to = None
            continue

        logger.info("turn end: status=%s", result.get("status"))
        waiting = _print_result(result)
        awaiting_answer_to = raw_query if waiting else None


if __name__ == "__main__":
    configure_logging()
    if len(sys.argv) > 1:
        run_single(" ".join(sys.argv[1:]))
    else:
        run_repl()
