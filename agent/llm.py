"""Shared model factory and JSON-parsing helper for the LLM-calling nodes.

Provider is chosen by config.LLM_PROVIDER ("anthropic" or "groq"). Both
langchain-anthropic and langchain-groq implement the same .bind_tools() /
.tool_calls interface, so agent/nodes/sql_agent.py's tool-calling loop works
unmodified regardless of which one is active.
"""

import json
import re

import config

_llm_cache: dict[tuple, object] = {}


def get_llm(temperature: float = 0, json_mode: bool = False):
    """Returns a shared chat model client for the configured provider.

    json_mode=True asks the provider's own structured-output mode to enforce
    valid JSON, used by the clarification/orchestrator nodes' "respond in
    JSON only" prompts. Claude has no equivalent flag -- prompt instructions
    plus parse_json_response() below are enough for it -- but open models
    served through Groq are looser about following that instruction on their
    own, so their real JSON mode is worth turning on rather than trusting
    the prompt alone.
    """
    cache_key = (config.LLM_PROVIDER, config.MODEL_NAME, temperature, json_mode)
    if cache_key in _llm_cache:
        return _llm_cache[cache_key]

    if config.LLM_PROVIDER == "groq":
        if not config.GROQ_API_KEY:
            raise RuntimeError(
                "GROQ_API_KEY is not set. Copy .env.example to .env and fill it in."
            )
        from langchain_groq import ChatGroq

        kwargs = {}
        if json_mode:
            kwargs["model_kwargs"] = {"response_format": {"type": "json_object"}}
        llm = ChatGroq(model=config.MODEL_NAME, temperature=temperature, **kwargs)

    elif config.LLM_PROVIDER == "anthropic":
        if not config.ANTHROPIC_API_KEY:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and fill it in."
            )
        from langchain_anthropic import ChatAnthropic

        llm = ChatAnthropic(model=config.MODEL_NAME, temperature=temperature)

    else:
        raise RuntimeError(
            f"Unknown LLM_PROVIDER: {config.LLM_PROVIDER!r}. Use 'anthropic' or 'groq'."
        )

    _llm_cache[cache_key] = llm
    return llm


def record_usage(state: dict, response) -> None:
    """Accumulates one LLM call's token usage onto state's whole-turn totals.

    Both langchain-anthropic and langchain-groq populate the standard
    AIMessage.usage_metadata field, so there's no provider branching needed
    here despite this being the provider-abstraction file.
    """
    usage = getattr(response, "usage_metadata", None)
    if not usage:
        return
    state["total_input_tokens"] = state.get("total_input_tokens", 0) + usage.get("input_tokens", 0)
    state["total_output_tokens"] = state.get("total_output_tokens", 0) + usage.get("output_tokens", 0)


def parse_json_response(text: str) -> dict:
    """Extracts a JSON object from a model response, tolerating ```json fences."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else text.strip()
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        # Fall back to the first {...} block in the text.
        brace_match = re.search(r"\{.*\}", text, re.DOTALL)
        if brace_match:
            return json.loads(brace_match.group(0))
        raise
