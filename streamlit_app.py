"""Streamlit chat UI for the Data Analyst Agent.

    uvicorn api:app          # in one terminal -- the agent backend
    streamlit run streamlit_app.py   # in another -- this UI

Talks to the FastAPI backend (api.py) over HTTP rather than invoking the
LangGraph agent in-process -- config.API_BASE_URL points at it. The agent
itself, turn-input construction, and session memory all live server-side;
this file is just a chat client around POST /query.

Answers are plain-English by default. The "Show SQL & data retrieved"
sidebar toggle opts into api.py's debug flag, which adds each sub-query's
SQL and returned rows to the response -- rendered per message as
intent -> query -> data rows.
"""

import logging
import uuid

import httpx
import streamlit as st

import config
from agent.logging_config import configure_logging

configure_logging()
logger = logging.getLogger(__name__)

st.set_page_config(page_title="Data Analyst Agent", page_icon="🗄️", layout="centered")


@st.cache_resource
def get_client() -> httpx.Client:
    return httpx.Client(base_url=config.API_BASE_URL, timeout=120.0)


def _init_session() -> None:
    st.session_state.setdefault("session_id", str(uuid.uuid4()))
    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("awaiting_answer_to", None)
    st.session_state.setdefault("pending_options", None)


def _new_session() -> None:
    st.session_state.session_id = str(uuid.uuid4())
    st.session_state.messages = []
    st.session_state.awaiting_answer_to = None
    st.session_state.pending_options = None


def _run_turn(user_text: str, show_sql: bool) -> None:
    if st.session_state.awaiting_answer_to:
        raw_query = f"{st.session_state.awaiting_answer_to} -- {user_text}"
    else:
        raw_query = user_text

    st.session_state.messages.append({"role": "user", "content": user_text})
    st.session_state.awaiting_answer_to = None
    st.session_state.pending_options = None

    logger.info("turn start: %r (session=%s)", raw_query, st.session_state.session_id[:8])
    try:
        with st.spinner("Thinking..."):
            response = get_client().post(
                "/query",
                json={
                    "query": raw_query,
                    "session_id": st.session_state.session_id,
                    "debug": show_sql,
                },
            )
            response.raise_for_status()
            result = response.json()
    except httpx.HTTPError as e:
        logger.exception("turn failed: could not reach the agent API")
        st.session_state.messages.append(
            {"role": "assistant", "content": f"Sorry, couldn't reach the agent API: {e}"}
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
                "sub_queries": result.get("sub_queries"),
            }
        )
    else:
        st.session_state.messages.append(
            {"role": "assistant", "content": "Sorry, I couldn't complete that."}
        )


def _render_sub_queries(sub_queries: list[dict]) -> None:
    with st.expander("SQL & data retrieved"):
        for i, sq in enumerate(sub_queries, start=1):
            st.markdown(f"**{i}. {sq['intent']}**")
            st.code(sq.get("sql") or "(no SQL executed)", language="sql")
            rows, columns = sq.get("rows"), sq.get("columns")
            if rows:
                st.dataframe([dict(zip(columns, row)) for row in rows], hide_index=True)


_init_session()

with st.sidebar:
    st.markdown("### Data Analyst Agent")
    st.caption("Chinook database. Plain-English answers by default.")
    st.write(f"**API:** {config.API_BASE_URL}")
    st.write(f"**Session:** `{st.session_state.session_id[:8]}`")
    show_sql = st.checkbox("Show SQL & data retrieved", value=False)
    if st.button("New session", use_container_width=True):
        _new_session()
        st.rerun()

st.title("Ask your data a question")

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg.get("caption"):
            st.caption(msg["caption"])
        if msg.get("sub_queries"):
            _render_sub_queries(msg["sub_queries"])

if st.session_state.pending_options:
    cols = st.columns(len(st.session_state.pending_options))
    for col, label in zip(cols, st.session_state.pending_options):
        button_key = f"option_{label}_{len(st.session_state.messages)}"
        if col.button(label, use_container_width=True, key=button_key):
            _run_turn(label, show_sql)
            st.rerun()

user_input = st.chat_input("Ask a question about the Chinook database...")
if user_input:
    _run_turn(user_input, show_sql)
    st.rerun()
