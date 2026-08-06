# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Behavioral guidelines

Biases toward caution over speed. For trivial tasks, use judgment.

**1. Think before coding.** Don't assume, don't hide confusion, surface
tradeoffs. State assumptions explicitly; if uncertain, ask. If multiple
interpretations exist, present them rather than picking silently. If a
simpler approach exists, say so -- push back when warranted. If something is
unclear, stop, name what's confusing, and ask.

**2. Simplicity first.** Minimum code that solves the problem, nothing
speculative: no features beyond what was asked, no abstractions for
single-use code, no unrequested flexibility/configurability, no error
handling for impossible scenarios. If it could be a quarter of the size,
rewrite it. Ask: would a senior engineer call this overcomplicated?

**3. Surgical changes.** Touch only what you must; clean up only your own
mess. Don't "improve" adjacent code, comments, or formatting; don't refactor
things that aren't broken; match existing style even if you'd do it
differently. Remove imports/variables/functions your own changes made
unused, but mention (don't delete) pre-existing dead code you notice. Every
changed line should trace directly to the user's request.

**4. Goal-driven execution.** Turn tasks into verifiable goals ("fix the
bug" -> "write a test that reproduces it, then make it pass") so you can loop
independently instead of needing constant clarification. For multi-step
work, state a brief plan with a verification check per step.

## What this is

A LangGraph implementation of a text-to-SQL agent: natural-language questions
in, plain-English answers out, against the Chinook SQLite database (`db/chinook.db`)
-- no SQL is ever shown to the user. The full design rationale lives in
`docs/text_to_sql_agent_design_spec.md`; the code follows that document's
structure section-by-section, and node/module docstrings cite the specific
section (e.g. "See spec §3.7") instead of re-explaining the reasoning inline.
Read the cited section when a docstring's "why" isn't obvious from the code.

## Commands

```bash
# Setup
python -m venv .venv
.venv/Scripts/activate                        # source .venv/bin/activate on macOS/Linux
pip install -r requirements.txt
cp .env.example .env                          # then set ANTHROPIC_API_KEY=sk-ant-...

# Run
streamlit run streamlit_app.py                # chat UI
python main.py                                # interactive REPL
python main.py "total revenue this quarter"   # single-shot mode

# Test
pytest                                         # full suite, no API key needed
pytest tests/unit/test_sql_agent.py            # single file
pytest tests/unit/test_sql_agent.py::test_name # single test
python -m eval.run_eval                        # gold-question eval suite -- needs a real API key
```

There's no lint/format command configured in this repo (no pyproject.toml,
ruff/black config, or pre-commit hook) -- don't invent one.

## Architecture

```
START -> orchestrator -> sql_agent -> [advance_sub_query -> sql_agent]* -> analyst -> END
              |                                                              |
              +---(awaiting_user, ends turn)          (insufficient, refine_count<2) -> orchestrator
```

Four LangGraph nodes (`agent/nodes/`), wired in `agent/graph.py`:

1. **`orchestrator_node`** -- the ambiguity gate *and* the planner in one LLM
   call: given the question plus recent `turn_history` as free-text context
   (not a pre-extracted filter), it either produces 1-3 independent
   sub-queries (`MAX_SUB_QUERIES`) or, if it genuinely can't form a plan,
   sets `status="awaiting_user"` and the graph run ends for this turn. On a
   refine loop it instead patches/adds one sub-query based on the analyst's
   feedback. (There used to be a separate upfront `clarification_node`
   scoring ambiguity before planning -- removed because scoring "does this
   lack a filter" in the abstract, decoupled from whether planning actually
   needs it, flagged queries that didn't need a filter at all, e.g. "total
   number of artists", and got worse the longer a session ran.)
2. **`sql_agent_node`** -- for one sub-query: a genuinely agentic tool-calling
   loop (the model itself decides which of the five bound tools to call, in
   what order, and when it has enough to commit to SQL -- not a fixed
   explore-then-generate pipeline), followed by `result_validator`, a
   separate deterministic sanity check that runs after the model is done
   (defense in depth against a confidently-wrong agent). Loops back to itself
   via `advance_sub_query` until every sub-query is processed.
3. **`analyst_node`** -- classifies report type (fact/ranking/trend/comparison/alert),
   checks whether the data is sufficient to answer that report type, and
   either requests a refine (back to orchestrator) or writes the final
   plain-English explanation.

Bound tools (`agent/tools/db_tools.py`, called by the model itself, not by
node code ahead of time): `explore_schema`, `execute_sql`, `get_sample_rows`,
`get_column_stats`, `check_table_exists`.

**Three nested budgets** keep the graph bounded, since sub-query count,
tool-calling freedom, and analyst refinement all multiply each other
(`config.py`, spec §8):
- `sql_retry_count` (max 2, per sub-query, failed `execute_sql` calls only)
- `tool_call_count` (max 6, per sub-query, every tool call)
- `total_tool_calls` (max 24, whole turn -- the real backstop)

**Session memory** (`turn_history`, a list of `{raw_query, resolved_query,
sql_executed, result_summary, timestamp}` per turn) lives directly in
`AgentState` (`agent/state.py`) and is persisted automatically by LangGraph's
own checkpointer (`InMemorySaver`, wired in `agent/graph.py`), keyed by
`thread_id`/`session_id` -- there is no separate memory store to keep in
sync. `main.py` and `streamlit_app.py` each generate their own
`thread_id`/`session_id` per session for isolation. `orchestrator_node`
reads the last few `turn_history` entries as free-text context in its
planning prompt and judges relevance itself; there is deliberately no
separate `active_filters`-style key-value cache mechanically reapplied to
later turns -- an earlier version had one, and it silently mis-scoped
unrelated follow-up questions to whichever period/region the *first*
comparison-style query happened to mention first.

**Provider abstraction**: `agent/llm.py` is the only file that knows about
provider differences (Anthropic vs. Groq, via `config.LLM_PROVIDER`).
Everything else uses the same LangChain `.bind_tools()`/`.tool_calls`
interface regardless of which provider is active. Not every Groq-hosted
model supports tool-calling -- the SQL agent's loop depends on it.

**Known simplification vs. the spec**: the "ask and wait" clarification flow
doesn't use LangGraph's `interrupt()`/resume machinery. When a turn ends with
`status == "awaiting_user"`, the caller prints the question, and the *next*
user message is concatenated onto the original query
(`"<original> -- <answer>"`) and run through `orchestrator_node` again from
scratch (see `main.py`'s `run_repl`). Simpler to reason about for a CLI/simple
chat UI; a real multi-turn UI would want the proper interrupt/resume flow.

## Testing notes

- Everything under `tests/unit/` and most of `tests/integration/` runs
  against the real `db/chinook.db` but with LLM calls stubbed out --
  see `tests/integration/test_sql_agent_budgets.py` and
  `test_multi_query_graph.py` for the pattern used to test the tool-calling
  loop and the multi-sub-query graph without hitting a real model.
- `eval/run_eval.py` is the one thing that genuinely needs a configured
  provider, since it drives the actual agent end-to-end against
  `eval/gold_questions.py` and scores with both `execution_accuracy`
  (objective, compares generated SQL results to gold SQL) and `llm_judge`
  (subjective).
- `conftest.py` exists solely to make the repo root importable as the
  top-level package namespace for pytest.

## Logging

Call `configure_logging()` (`agent/logging_config.py`) once per process entry
point (`main.py`, `streamlit_app.py`, `eval/run_eval.py`) -- it's
deliberately not called at import time, since `streamlit_app.py` and the test
suite both import `_fresh_turn_input` from `main.py` and neither should get
the side effect of configuring global logging just from that import. Every
module logs via `logging.getLogger(__name__)` and relies on propagation to
the root logger; nothing under `agent/` configures its own handlers.
`LOG_LEVEL=DEBUG` (in `.env`) shows every tool call's full args/results;
`INFO` (default) shows only the high-level decision trail.

## Security

`db/loader.py` opens the SQLite connection in `mode=ro` (read-only at the
driver level) as a backstop behind the app-layer check. `is_select_query`
(`agent/tools/db_tools.py`) is the app-layer allowlist: single read-only
SELECT/CTE only, rejects a second stacked statement (even a trailing
semicolon), and rejects forbidden keywords anywhere in the string including
inside comments. Keep both layers in sync if you touch either.
