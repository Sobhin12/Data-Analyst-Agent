"""Model names, budget caps, and thresholds for the text-to-SQL agent.

See docs/text_to_sql_agent_design_spec.md §8 for why these specific caps exist.
"""

import os

from dotenv import load_dotenv

load_dotenv()

# --- Model provider ---
# "anthropic" (default) or "groq". Both implement the same LangChain tool-calling
# interface, so agent/nodes/sql_agent.py doesn't need to know which one is active.
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "anthropic").lower()

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

_DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-5",
    # Must support tool-calling on Groq -- not every hosted model does.
    "groq": "llama-3.3-70b-versatile",
}

MODEL_NAME = os.environ.get("AGENT_MODEL") or _DEFAULT_MODELS.get(
    LLM_PROVIDER, _DEFAULT_MODELS["anthropic"]
)

# --- Orchestrator ---
MAX_SUB_QUERIES = 3

# --- SQL agent tool-calling loop (per sub-query) ---
MAX_TOOL_CALLS = 6
MAX_SQL_RETRIES = 2

# --- Whole-turn backstop across every sub-query and refine round ---
MAX_TOTAL_TOOL_CALLS = 24

# --- Analyst refine loop (whole turn) ---
MAX_REFINE_COUNT = 2

# --- Result validator ---
LARGE_RESULT_ROW_THRESHOLD = 10_000
DEFAULT_ROW_LIMIT = 1000

# --- API backend (api.py) ---
# Base URL streamlit_app.py talks to -- api.py must be running separately
# (uvicorn api:app) for the Streamlit UI to work.
API_BASE_URL = os.environ.get("API_BASE_URL", "http://127.0.0.1:8000")

# --- Eval suite pacing (eval/run_eval.py) ---
# run_eval.py fires many LLM calls back to back (agent-internal + judge, x16
# questions), always sequentially -- never concurrently, since a provider's
# per-minute request/token limits apply across the whole run regardless of
# how the calls are shaped. Groq's lower tiers enforce tight RPM/TPM limits;
# this adds a deliberate gap in front of every call. 0 (default) is a no-op
# for providers without tight limits.
EVAL_CALL_DELAY_SECONDS = float(os.environ.get("EVAL_CALL_DELAY_SECONDS", "0"))
