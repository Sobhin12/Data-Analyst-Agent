"""Streamlit chat UI for the text-to-SQL agent.

    streamlit run streamlit_app.py

Reuses the exact same turn-input construction as the CLI (main.py) so both
front ends share one definition of "what a fresh turn looks like" -- see
main.py's _fresh_turn_input for why certain state fields reset per turn and
others (active_filters, turn_history) deliberately don't.
"""

import logging
import uuid

import streamlit as st

import config
from agent.graph import build_graph
from agent.logging_config import configure_logging
from main import _fresh_turn_input

configure_logging()
logger = logging.getLogger(__name__)

st.set_page_config(page_title="Text-to-SQL Agent", page_icon="🗄️", layout="centered")


@st.cache_resource
def get_graph():
    return build_graph()


def _init_session() -> None:
    st.session_state.setdefault("thread_id", str(uuid.uuid4()))
    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("awaiting_answer_to", None)
    st.session_state.setdefault("pending_options", None)


def _new_session() -> None:
    st.session_state.thread_id = str(uuid.uuid4())
    st.session_state.messages = []
    st.session_state.awaiting_answer_to = None
    st.session_state.pending_options = None


def _run_turn(user_text: str) -> None:
    thread_config = {"configurable": {"thread_id": st.session_state.thread_id}}

    if st.session_state.awaiting_answer_to:
        raw_query = f"{st.session_state.awaiting_answer_to} -- {user_text}"
    else:
        raw_query = user_text

    st.session_state.messages.append({"role": "user", "content": user_text})
    st.session_state.awaiting_answer_to = None
    st.session_state.pending_options = None

    logger.info("turn start: %r (session=%s)", raw_query, st.session_state.thread_id[:8])
    try:
        with st.spinner("Thinking..."):
            result = get_graph().invoke(_fresh_turn_input(raw_query), thread_config)
    except Exception as e:
        logger.exception("turn failed with an unhandled exception")
        st.session_state.messages.append(
            {"role": "assistant", "content": f"Sorry, something went wrong: {e}"}
        )
        return

    logger.info("turn end: status=%s", result.get("status"))
    status = result.get("status")

    if status == "awaiting_user":
        st.session_state.awaiting_answer_to = raw_query
        if result.get("clarification_request"):
            st.session_state.messages.append(
                {"role": "assistant", "content": result["clarification_request"]}
            )
        elif result.get("option_cards"):
            labels = [o.get("label", "") for o in result["option_cards"] if o.get("label")]
            st.session_state.messages.append(
                {"role": "assistant", "content": "Which do you mean?"}
            )
            st.session_state.pending_options = labels
        return

    if result.get("final_report"):
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": result["final_report"],
                "caption": result.get("assumption_note"),
            }
        )
    else:
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": f"Sorry, I couldn't complete that. ({result.get('error') or 'unknown error'})",
            }
        )


_init_session()

with st.sidebar:
    st.markdown("### Text-to-SQL Agent")
    st.caption("Chinook database -- no SQL ever shown to you.")
    st.write(f"**Provider:** {config.LLM_PROVIDER}")
    st.write(f"**Model:** {config.MODEL_NAME}")
    st.write(f"**Session:** `{st.session_state.thread_id[:8]}`")
    if st.button("New session", use_container_width=True):
        _new_session()
        st.rerun()

st.title("Ask your data a question")

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg.get("caption"):
            st.caption(msg["caption"])

if st.session_state.pending_options:
    cols = st.columns(len(st.session_state.pending_options))
    for col, label in zip(cols, st.session_state.pending_options):
        button_key = f"option_{label}_{len(st.session_state.messages)}"
        if col.button(label, use_container_width=True, key=button_key):
            _run_turn(label)
            st.rerun()

user_input = st.chat_input("Ask a question about the Chinook database...")
if user_input:
    _run_turn(user_input)
    st.rerun()
