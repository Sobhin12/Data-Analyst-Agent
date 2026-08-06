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
