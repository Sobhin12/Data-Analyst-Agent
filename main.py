"""Interactive CLI for the text-to-SQL agent.

Usage:
    python main.py                  # interactive REPL
    python main.py "your question"  # single-shot mode, prints the report and exits
"""

import sys
import uuid

from agent.graph import build_graph
from agent.state import new_state

# Per-turn fields reset on every new question; active_filters/last_metric/
# last_entity/turn_history are deliberately omitted so they persist from the
# checkpoint across turns -- that's the whole memory design (spec §10).
_RESET_KEYS = [
    "resolved_query", "assumption_note", "clarification_request", "option_cards",
    "execution_plan", "schema_snapshot", "sub_queries", "current_sub_query_idx",
    "total_tool_calls", "report_type", "data_sufficient", "refine_request",
    "refine_count", "final_report", "status", "error", "ambiguity_score", "ambiguity_type",
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
    try:
        result = graph.invoke(_fresh_turn_input(query), thread_config)
    except Exception as e:
        print(f"agent> Sorry, something went wrong: {e}")
        return
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

        try:
            result = graph.invoke(_fresh_turn_input(raw_query), thread_config)
        except Exception as e:
            print(f"agent> Sorry, something went wrong: {e}")
            awaiting_answer_to = None
            continue

        waiting = _print_result(result)
        awaiting_answer_to = raw_query if waiting else None


if __name__ == "__main__":
    if len(sys.argv) > 1:
        run_single(" ".join(sys.argv[1:]))
    else:
        run_repl()
