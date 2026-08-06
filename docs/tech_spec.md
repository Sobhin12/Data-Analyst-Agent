# Data Analyst Agentic System — Technical Design Specification

**Version:** 1.0  
**Framework:** LangGraph + LangChain  
**Database:** SQLite (Chinook / Northwind)  

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [System Architecture](#2-system-architecture)
3. [Agent Nodes — Detailed Design](#3-agent-nodes--detailed-design)
4. [Flow Diagrams](#4-flow-diagrams)
5. [State Schema](#5-state-schema)
6. [Tool Definitions](#6-tool-definitions)
7. [Ambiguity Handling Logic](#7-ambiguity-handling-logic)
8. [SQL Agent Retry Loop](#8-sql-agent-retry-loop)
9. [Analyst Agent Logic](#9-analyst-agent-logic)
10. [Memory Design](#10-memory-design)
11. [Evaluation Framework](#11-evaluation-framework)
12. [KPIs and Metrics](#12-kpis-and-metrics)
13. [Project Structure](#13-project-structure)
14. [Tech Stack](#14-tech-stack)

---

## 1. Project Overview

### Problem Statement

Non-technical users — product managers, operations teams, business analysts — need to query databases to make decisions. They cannot write SQL. They are blocked by the engineering team's availability or forced to use rigid pre-built dashboards that don't answer their actual questions.

### Solution

An agentic system that accepts natural language queries, resolves ambiguity intelligently, generates and self-corrects SQL, and returns a plain-English report with the data — without the user ever seeing a SQL query.

### What Makes This Genuinely Agentic

This is not a single-shot text-to-SQL pipeline. It is agentic because:

- The SQL agent has **genuine function-calling access** to schema exploration and execution tools — it decides which tool to call, in what order, and when it has enough information to commit to a query, rather than following a fixed explore-then-generate pipeline
- The SQL agent **observes execution errors** and **changes its approach** based on what it sees
- The orchestrator **decides how many sub-queries a question actually requires** — most comparisons and trends collapse into one query, but it splits when the pieces are genuinely independent
- The analyst agent **requests more data** if what it receives is insufficient to answer the question
- The clarification node **decides whether to ask, resolve from memory, or guess** based on confidence scoring
- The system **maintains state across turns** so follow-up questions work naturally
- Every loop has a **termination condition** and **max iteration guard** — including a hard global cap on total tool calls per turn, since sub-query count, tool-calling freedom, and analyst refinement now compound each other

---

## 2. System Architecture

### High-Level Component Map

```
User (plain English)
        │
        ▼
┌─────────────────────┐
│  Clarification Node │  ◄── LangGraph Checkpointer
│  (ambiguity scorer) │      (session memory)
└────────┬────────────┘
         │ resolved query + intent
         ▼
┌─────────────────────┐
│    Orchestrator     │
│  (plans 1-3 sub-     │
│   queries)           │
└────────┬────────────┘
         │ execution plan
         ▼
┌─────────────────────────────────────────────┐
│     SQL Agent (tool-calling loop, per        │
│                sub-query)                    │
│  Bound tools: explore_schema · execute_sql · │
│  get_sample_rows · get_column_stats ·        │
│  check_table_exists                          │
│  The LLM itself picks which tool to call,    │
│  in what order, until it has a result or     │
│  its budget (tool_call_count, sql_retry_     │
│  count) runs out.                            │
│                          ┌────────────────┐  │
│                          │Result Validator│  │
│                          └───────┬────────┘  │
└──────────────────────────────────┼───────────┘
                     more sub-queries in plan? │
                     ├──── yes ────────────────┘ (next sub-query)
                     └──── no                     │
                                     data + metadata│
                                                    ▼
┌─────────────────────────────────────────────┐
│             Analyst Agent                    │
│  ┌──────────────┐    ┌────────────────────┐ │
│  │ Report Type  │    │ Explanation        │ │
│  │ Classifier   │    │ Generator          │ │
│  └──────────────┘    └────────────────────┘ │
│         │ need more data?                    │
│         └──────────────────► Orchestrator   │
│                                (refine)       │
└─────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────┐
│ LangGraph Checkpoint │  (saves context for follow-ups)
└─────────────────────┘
         │
         ▼
   Response to User
```

### LangGraph Node Map

```
START
  └──► clarification_node
            ├──► [ambiguous, no memory] ──► ask_clarification ──► WAIT
            ├──► [ambiguous, memory resolves] ──► resolve_silent
            ├──► [vague intent] ──► show_options ──► WAIT
            └──► [clear] ──► orchestrator
                                  └──► sql_agent_loop(sub_query[i])
                                            │ internal tool-calling loop (§3.3):
                                            │   the LLM itself chooses among explore_schema,
                                            │   get_sample_rows, get_column_stats,
                                            │   check_table_exists, execute_sql
                                            │   bounded by tool_call_count (max 6) and
                                            │   sql_retry_count (max 2 failed execute_sql)
                                            ▼
                                       result_validator
                                            ├──► [invalid, sql_retry_count < 2] ──► sql_agent_loop (same sub_query)
                                            └──► [valid] ──► more sub_queries in plan?
                                                                  ├──► [yes] ──► sql_agent_loop (next sub_query, i += 1)
                                                                  └──► [no]  ──► analyst_agent
                                                                                      ├──► [insufficient, refine_count < 2] ──► orchestrator (refine)
                                                                                      └──► [sufficient] ──► checkpoint (auto) ──► END

Global backstop, checked before every tool invocation regardless of the above: total_tool_calls < 24 for the whole turn. Exceeding it forces an immediate graceful failure (§8).
```

---

## 3. Agent Nodes — Detailed Design

### 3.1 Clarification Node

**Responsibility:** Classify incoming query by ambiguity type. Route to the correct resolution strategy.

**Input:** Raw user query string + conversation memory  
**Output:** Resolved query intent OR clarification request to user

**Ambiguity scoring (0–1 per dimension):**

| Dimension | Score > 0.7 triggers |
|-----------|----------------------|
| Missing filter (time, region, product) | Single targeted question |
| Vague metric intent | Option cards (2–3 choices) |
| Resolvable from memory | Silent resolution |
| Genuinely clear | Pass through immediately |

**Decision logic (pseudo-code):**

```python
def clarification_node(state: AgentState) -> AgentState:
    scores = ambiguity_classifier.score(state.query)
    
    # Check memory first — cheapest resolution
    if memory_can_resolve(state.query, state.memory):
        resolved = memory.resolve(state.query)
        state.resolved_query = resolved
        state.assumption_note = f"Assuming {resolved.assumption} based on prior context."
        return route_to("orchestrator", state)
    
    # Missing filter — ask one thing only
    if scores.missing_filter > 0.7:
        missing_param = identify_most_critical_missing(state.query)
        state.clarification_request = build_single_question(missing_param)
        return route_to("await_user", state)
    
    # Vague intent — show options
    if scores.vague_intent > 0.7:
        options = generate_interpretations(state.query, n=3)
        state.option_cards = options
        return route_to("await_user", state)
    
    # Clear enough — proceed
    state.resolved_query = state.query
    return route_to("orchestrator", state)
```

**Rule:** Never ask two questions at once. If multiple parameters are missing, ask the one that changes the answer most dramatically and default the rest with a stated assumption.

---

### 3.2 Orchestrator

**Responsibility:** Decide whether the resolved query needs one SQL query or several genuinely independent sub-analyses, and define each sub-query's intent.

**Rule:** SQL is expressive enough (`GROUP BY`, `CASE WHEN`, window functions) that most "compare A vs B" and "trend over time" questions collapse into a *single* query. Only split into multiple sub-queries when:

- the pieces need different metrics or tables that can't share one aggregation (e.g., "compare signup rate vs. refund rate this month"), or
- a later sub-query depends on values only knowable after an earlier one runs (e.g., "who are the top 5 customers, and what's each one's average order size" if not expressible with a single window function)

**Cap:** 3 sub-queries per plan. A plan that wants more than that is a sign the question should be split into separate turns by the user, not decomposed further automatically.

```python
class ExecutionPlan:
    sub_queries: List[str]             # sub-query intents, 1-3 entries
    aggregation_strategy: str          # "single" | "compare" | "trend" | "sequential"
    reasoning: str                     # why single vs. split — kept for tracing/debugging
```

```python
def orchestrator_node(state: AgentState) -> AgentState:
    plan = planner_llm.plan(state.resolved_query, state.schema_snapshot)
    assert len(plan.sub_queries) <= 3, "Orchestrator exceeded sub-query cap"

    state.execution_plan = plan
    state.sub_queries = [SubQuery(intent=intent) for intent in plan.sub_queries]
    state.current_sub_query_idx = 0
    return route_to("sql_agent_loop", state)
```

On a `REFINE_QUERY` signal from the analyst (§9), the orchestrator re-enters here instead of the analyst calling the SQL agent directly — it decides whether the fix is to adjust an existing sub-query's intent or append a new one (still bounded by the 3-sub-query cap), then routes to `sql_agent_loop` for just the affected sub-query with a fresh `tool_call_count`/`sql_retry_count`.

---

### 3.3 SQL Agent (Tool-Calling Loop)

**Responsibility:** Given one sub-query's intent, autonomously use the bound tools to gather whatever schema/sample/stat information it needs, then execute a `SELECT` and self-correct on failure — as its own loop, not a graph-routed pipeline.

This replaces the old "schema explorer → SQL generator → DB executor" as three separate deterministic nodes. There is exactly one node here (`sql_agent_loop`); internally it runs a bounded while-loop that calls the model with tools bound, executes whatever it asks for, and feeds results back — the model decides when it has enough information and when it's done.

**Bound tools** (see §6): `explore_schema`, `get_sample_rows`, `get_column_stats`, `check_table_exists`, `execute_sql`.

**System prompt** (governs the whole loop, not a single completion):

```
You are a SQL agent working against a SQLite database. You have tools to explore
the schema, inspect sample values and column stats, and execute SQL.

Rules:
- Use tools as needed before writing SQL — don't guess table or column names.
- Match string filter values exactly as they appear in sample_values.
- SELECT only. Never write INSERT/UPDATE/DELETE/DROP/CREATE/ALTER.
- Prefer explicit JOINs. Add LIMIT 1000 unless the query is an aggregate.
- If execute_sql returns an error, read the corrective_hint and adjust — don't
  repeat the same failing query.
- Once execute_sql succeeds with a result you're confident answers the intent,
  stop calling tools and return the final SQL.

Sub-query intent: {intent}
Overall question (for context): {resolved_query}
```

**Loop (pseudo-code):**

```python
def sql_agent_loop(sub_query: SubQuery, state: AgentState) -> SubQuery:
    messages = [system_prompt(sub_query.intent, state.resolved_query)]

    while sub_query.tool_call_count < MAX_TOOL_CALLS:            # 6
        if state.total_tool_calls >= MAX_TOTAL_TOOL_CALLS:        # 24, whole-turn backstop
            sub_query.status = "failed"
            return sub_query

        response = llm.invoke(messages, tools=tools_sql_agent)
        if not response.tool_calls:
            sub_query.sql = response.final_sql                    # model is done
            break

        for call in response.tool_calls:
            sub_query.tool_call_count += 1
            state.total_tool_calls += 1
            result = execute_tool(call)

            if call.name == "execute_sql":
                if result.success:
                    sub_query.result = result
                else:
                    sub_query.sql_retry_count += 1
                    result = attach_corrective_hint(result)        # error classifier, §3.5
                    if sub_query.sql_retry_count >= MAX_SQL_RETRIES:  # 2
                        sub_query.status = "failed"
                        return sub_query

            messages.append(tool_result_message(call, result))

    return sub_query
```

`tool_call_count` (max 6) is the outer safety valve — it bounds total tool use, including pure exploration calls the model makes on its own initiative. `sql_retry_count` (max 2) specifically tracks *failed* `execute_sql` attempts and forces a hard stop even if `tool_call_count` hasn't been reached. Both reset to 0 at the start of every `sql_agent_loop` invocation, including a fresh sub-query and a refine re-entry (see §8 for the full budget model).

**Why sample values matter:** the agent needs to know that a `region` column contains `"North"`, `"South"`, `"East"` — not `"north"` or `"NORTH"`. Case mismatches are a top cause of zero-row results, which is why `explore_schema` returns sample values rather than just column names and types.

---

### 3.4 Schema Explorer (Tool)

**Responsibility:** Introspect the database and return a structured schema summary. Called by the SQL agent itself (§3.3), at its own discretion, via function-calling — not invoked automatically by node code.

**Tool call:**

```python
@tool
def explore_schema(table_hint: str = None) -> SchemaSnapshot:
    """
    Returns table names, column names, data types, and sample values.
    If table_hint provided, returns detailed info for that table only.
    """
    inspector = inspect(engine)
    tables = [table_hint] if table_hint else inspector.get_table_names()
    schema = {}
    for table in tables:
        columns = inspector.get_columns(table)
        fk = inspector.get_foreign_keys(table)
        schema[table] = {
            "columns": [{"name": c["name"], "type": str(c["type"])} for c in columns],
            "foreign_keys": fk,
            "sample_values": get_sample_values(table, n=3)
        }
    return schema
```

---

### 3.5 DB Executor (Tool)

**Responsibility:** Execute the SQL query safely. Return results or a structured error.

```python
@tool
def execute_sql(sql: str) -> ExecutionResult:
    """
    Executes SQL against the database.
    Returns rows on success, structured error on failure.
    Never allows DDL or DML — SELECT only.
    """
    if not is_select_query(sql):
        return ExecutionResult(error="Only SELECT queries are permitted.")
    
    try:
        with engine.connect() as conn:
            result = conn.execute(text(sql))
            rows = result.fetchall()
            columns = result.keys()
            return ExecutionResult(
                success=True,
                rows=rows,
                columns=list(columns),
                row_count=len(rows)
            )
    except SQLAlchemyError as e:
        return ExecutionResult(
            success=False,
            error=str(e),
            error_type=classify_sql_error(e)
        )
```

**Safety guardrail:** Allowlist `SELECT` only. Reject any query containing `INSERT`, `UPDATE`, `DELETE`, `DROP`, `CREATE`, `ALTER`.

---

### 3.6 Error Classifier

**Responsibility:** Categorize why the SQL failed and attach a corrective hint to the `execute_sql` tool result *before* it's appended to the agent loop's message history. This no longer routes graph edges — the SQL agent (§3.3) reads the hint and decides for itself how to react, the same way it decides everything else in its loop.

| Error Type | Signal | Hint Given to the Agent |
|------------|--------|--------------------------|
| `SYNTAX_ERROR` | Malformed SQL | Fix syntax, same schema |
| `UNKNOWN_COLUMN` | Column doesn't exist | Re-explore schema, find correct column |
| `UNKNOWN_TABLE` | Table doesn't exist | Re-explore schema, find correct table |
| `TYPE_MISMATCH` | Comparing wrong types | Cast or change filter value |
| `AMBIGUOUS_COLUMN` | Column exists in multiple tables | Qualify with table name |
| `TIMEOUT` | Query too slow | Add index hint or simplify |
| `UNKNOWN` | Catch-all | Suggest re-exploring the schema |

```python
def classify_sql_error(error: str) -> ErrorType:
    patterns = {
        ErrorType.SYNTAX_ERROR: ["syntax error", "unexpected token"],
        ErrorType.UNKNOWN_COLUMN: ["no such column", "unknown column"],
        ErrorType.UNKNOWN_TABLE: ["no such table", "relation does not exist"],
        ErrorType.TYPE_MISMATCH: ["type mismatch", "invalid input syntax"],
        ErrorType.AMBIGUOUS_COLUMN: ["ambiguous column"],
        ErrorType.TIMEOUT: ["timeout", "statement timeout"],
    }
    for error_type, signals in patterns.items():
        if any(s in error.lower() for s in signals):
            return error_type
    return ErrorType.UNKNOWN
```

---

### 3.7 Result Validator

**Responsibility:** Decide if the result is genuinely valid or suspiciously wrong before passing to the analyst.

**Checks:**

```python
def validate_result(result: ExecutionResult, intent: QueryIntent) -> ValidationVerdict:
    
    # Zero rows — is this plausible?
    if result.row_count == 0:
        if intent.type == "aggregate":
            return ValidationVerdict.VALID, "Zero is a valid aggregate result (e.g. no matching rows)"
        if intent.expects_data:  # "show me sales" should never return 0
            return ValidationVerdict.REQUERY_NEEDED, "Zero rows returned for a data fetch query"
        else:  # "does X exist?" — zero rows is a valid answer
            return ValidationVerdict.VALID, "Zero rows is a valid answer for existence check"
    
    # Result is far larger than expected
    if result.row_count > 10000 and not intent.expects_large_result:
        return ValidationVerdict.REQUERY_NEEDED, "Result set too large — query may be missing a filter"
    
    return ValidationVerdict.VALID, "Result looks plausible"
```

This runs after the SQL agent's own loop concludes — an independent, deterministic sanity check, on purpose separate from the LLM's own judgment about whether its result "looks right." Defense in depth against a tool-calling agent that's confidently wrong.

---

### 3.8 Analyst Agent

**Responsibility:** Classify what kind of report to write, generate a plain-English explanation, and decide if more data is needed.

**Report type classification:**

| Query Intent | Report Type | Format |
|---|---|---|
| Single metric lookup | Fact answer | One sentence + value |
| Comparison (A vs B) | Comparison report | Table + summary |
| Trend over time | Trend report | Narrative + direction |
| Ranking (top N) | Ranked list | Numbered list + commentary |
| Anomaly detection | Alert report | Finding + context |

**Insufficient data check:** reasons over the whole `sub_queries` list, not a single result — a comparison needs at least 2 *successful* sub-queries, not just row count within one.

```python
def check_data_sufficiency(sub_queries: List[SubQuery], intent: QueryIntent) -> bool:
    done = [sq for sq in sub_queries if sq.status == "done"]

    if intent.type == "trend":
        total_rows = sum(sq.result.row_count for sq in done)
        return total_rows >= 3       # Can't identify a trend from 2 data points
    if intent.type == "comparison":
        return len(done) >= 2        # Can't compare one thing
    if intent.type == "ranking":
        return done and done[0].result.row_count >= intent.requested_n  # Asked for top 10 but got 3
    return len(done) == len(sub_queries)   # everything in the plan actually succeeded
```

If insufficient and `refine_count < 2`, the analyst sends a `REFINE_QUERY` signal to the **orchestrator** (§3.2), incrementing `refine_count`, describing what additional data is needed. The orchestrator decides whether to patch an existing sub-query's intent or add a new one (still bounded by the 3-sub-query cap), then re-enters the SQL agent loop for the affected sub-query with a fresh `tool_call_count`/`sql_retry_count`. If `refine_count` is already at its cap, the analyst reports on the best available data instead, stating clearly that the result may be incomplete (see §8 for the full budget model).

---

## 4. Flow Diagrams

### 4.1 Overall System Flow

```
┌──────────────────────────────────────────────────────────────────┐
│  User: "show me sales"                                           │
└────────────────────────────┬─────────────────────────────────────┘
                             │
                             ▼
              ┌──────────────────────────┐
              │    Clarification Node    │
              │  ambiguity score: 0.82   │
              │  type: missing_filter    │
              └──────────┬───────────────┘
                         │
              asks: "Which time period?"
              [Last 30 days] [This quarter] [This year]
                         │
              user picks: "This quarter"
                         │
                         ▼
              ┌──────────────────────────┐
              │      Orchestrator        │
              │  plan: 1 sub-query       │
              │  (single aggregate —     │
              │   no split needed)       │
              └──────────┬───────────────┘
                         │
                         ▼
              ┌──────────────────────────┐
              │  SQL Agent (tool loop)   │
              │  model calls: explore_   │
              │  schema, execute_sql     │
              └──────────┬───────────────┘
                         │
                   rows: 1, value: $284,500
                         │
                         ▼
              ┌──────────────────────────┐
              │      Analyst Agent       │
              │  type: fact_answer       │
              │  sufficient: yes         │
              └──────────┬───────────────┘
                         │
                         ▼
  "Total sales this quarter: $284,500 — up 12% from last quarter."
```

### 4.2 SQL Agent Tool-Calling Loop Detail

```
sql_agent_loop (one sub-query)
     │
     │ model decides: explore_schema? get_sample_rows? execute_sql?
     ▼
execute_sql ──► SUCCESS ──────────────────────► result_validator
     │
     │ FAILURE
     ▼
error_classifier attaches corrective_hint to the tool result
     │
     ▼
tool result appended to the agent's own message history
     │
     ▼
model reads the hint and decides its own next move:
     ├──► re-call explore_schema (e.g. on UNKNOWN_COLUMN/TABLE)
     ├──► re-call execute_sql with fixed SQL (e.g. on SYNTAX_ERROR)
     └──► any other tool it judges useful

sql_retry_count < 2? ──► YES → loop continues
                     └──► NO  → State: FAILED (graceful failure to analyst)

tool_call_count < 6? (separate, outer safety valve on total tool use)
                     └──► NO  → State: FAILED regardless of sql_retry_count
```

Unlike the old design, there is no graph-level routing table mapping error type → next node — the classifier only annotates the tool result; the model's own next action is its choice, the same as every other step in its loop.

### 4.3 Ambiguity Decision Tree

```
incoming query
      │
      ▼
ambiguity_classifier
      │
      ├──► check checkpointed session memory first
      │         │
      │         ├──► RESOLVES ──► silent resolution
      │         │                  └──► state assumption in response
      │         │
      │         └──► DOES NOT RESOLVE
      │                   │
      │                   ▼
      │              classify type
      │                   │
      │         ┌─────────┴──────────┐
      │         │                    │
      │    MISSING_FILTER       VAGUE_INTENT
      │         │                    │
      │    ask ONE question    show 2-3 option cards
      │    (targeted param)    (interpretations)
      │         │                    │
      │         └─────────┬──────────┘
      │                   │
      │              user responds
      │                   │
      └──► CLEAR ─────────┴──► orchestrator
```

### 4.4 Analyst Feedback Loop

```
all sub-queries in the plan have run
          │
          ▼
analyst_agent
          │
          ├──► check_data_sufficiency()
          │         │
          │    INSUFFICIENT, refine_count < 2 ─────────────┐
          │         │                                      │
          │         │  reason: "need 6 months for trend"   │
          │         │  refine_count += 1                   ▼
          │         │                    orchestrator (patches or adds a sub-query)
          │         │                          │
          │         │                          ▼
          │         │         sql_agent_loop (affected sub-query, fresh tool_call_count/sql_retry_count)
          │         │                                      │
          │         │◄─────────────────────────────────────┘
          │
          │    SUFFICIENT (or refine_count == 2, best-effort)
          │         │
          ▼         ▼
   classify_report_type()
          │
          ▼
   generate_explanation()
          │
          ▼
   state auto-persisted by LangGraph checkpointer
          │
          ▼
   response to user
```

---

## 5. State Schema

The LangGraph state object carries all information across nodes. Every node reads from and writes to this shared state. The whole object is persisted automatically by LangGraph's checkpointer, keyed by `session_id` as the thread ID — that's what makes it resumable across turns without a hand-rolled memory store (see §10).

The orchestrator (§3.2) can plan up to 3 independent sub-queries per turn, so the SQL agent's per-query fields live in a `SubQuery` list rather than flat on `AgentState`. Each sub-query gets its own tool-calling loop (§3.3) with its own budget.

```python
from typing import TypedDict, Optional, List, Literal
from dataclasses import dataclass, field

@dataclass
class SubQuery:
    intent: str
    sql: Optional[str] = None
    result: Optional[ExecutionResult] = None
    tool_call_count: int = 0             # Total tool invocations this sub-query. Max: 6
    sql_retry_count: int = 0             # Failed execute_sql attempts this sub-query. Max: 2
    error_history: List[str] = field(default_factory=list)
    status: str = "pending"              # "pending" | "done" | "failed"

class AgentState(TypedDict):
    # Input
    raw_query: str
    session_id: str                     # LangGraph thread_id
    
    # Clarification
    ambiguity_score: dict                # {missing_filter: 0.8, vague_intent: 0.2}
    ambiguity_type: str                  # "missing_filter" | "vague_intent" | "clear"
    resolved_query: Optional[str]
    assumption_note: Optional[str]       # "Assuming North region based on prior context"
    clarification_request: Optional[str]
    option_cards: Optional[List[dict]]
    
    # Planning
    execution_plan: Optional[dict]       # ExecutionPlan — sub-query intents, cap 3 (§3.2)
    
    # SQL Agent
    schema_snapshot: Optional[dict]
    sub_queries: List[SubQuery]
    current_sub_query_idx: int
    total_tool_calls: int                # Whole-turn backstop across all sub-queries. Max: 24
    
    # Analyst
    report_type: Optional[str]           # "fact" | "comparison" | "trend" | "ranking"
    data_sufficient: Optional[bool]
    refine_request: Optional[str]        # Sent to orchestrator if insufficient
    refine_count: int                    # Analyst-driven refine round trips this turn. Max: 2
    final_report: Optional[str]
    
    # Memory — persisted automatically via the checkpointer, no separate store
    active_filters: dict                 # {"region": "North", "period": "Q2 2026"}
    last_metric: Optional[str]           # "revenue"
    last_entity: Optional[str]           # "products"
    turn_history: List[dict]             # Prior turns: raw_query, resolved_query, assumptions, sql, result_summary
    
    # Control
    status: str                          # "running" | "awaiting_user" | "done" | "failed"
    error: Optional[str]
```

---

## 6. Tool Definitions

Full list of tools available to each agent:

### SQL Agent Tools

These are bound to the SQL agent's model call via function-calling (§3.3) — the model itself chooses which to call and when, inside its own loop. None of them are invoked by node code ahead of time.

```python
tools_sql_agent = [
    explore_schema,        # List tables, columns, types, sample values
    execute_sql,           # Run SELECT query, return rows or error
    get_sample_rows,       # Fetch N sample rows from a table
    get_column_stats,      # Min, max, distinct count for a column
    check_table_exists,    # Boolean check before querying
]
```

### Analyst Agent Tools

```python
tools_analyst_agent = [
    calculate_percentage_change,   # (old, new) → formatted string
    format_currency,               # 284500 → "$284,500"
    format_large_number,           # 1200000 → "1.2M"
    detect_trend_direction,        # List of values → "upward" | "downward" | "flat"
    summarize_table,               # DataFrame → prose summary
]
```

### Clarification Node Tools

```python
tools_clarification = [
    fetch_memory,                  # Get prior turns for this session
    list_available_filters,        # What filters does the schema support?
    generate_interpretation_cards, # Build 2-3 option cards from vague query
]
```

---

## 7. Ambiguity Handling Logic

### Ambiguity Classifier Prompt

```
You are an ambiguity classifier for a SQL agent system.

Given the user query below, score it on two dimensions from 0 to 1:
- missing_filter: Does the query lack a required filter (time, region, product, etc.)?
- vague_intent: Is it unclear which metric or KPI the user wants?

Also check the conversation memory to see if any ambiguity is resolvable
from prior context.

Respond in JSON only:
{
  "missing_filter": 0.0–1.0,
  "vague_intent": 0.0–1.0,
  "memory_resolves": true/false,
  "memory_resolution": "resolved value if applicable",
  "missing_param": "the most critical missing parameter",
  "interpretations": ["option 1", "option 2", "option 3"]
}

Query: {query}
Memory: {memory}
Schema filters available: {available_filters}
```

### Clarification Question Rules

1. **One question maximum per turn.** If multiple parameters are missing, ask the most critical one only.
2. **Offer choices, not open text.** "Which period: Last 30 days / This quarter / This year?" not "Which time period?"
3. **State defaults.** "I'll show all regions unless you specify one."
4. **Never ask for something you can default safely.** If `region` is missing but the data has only one region, don't ask.

### Silent Resolution Rules

1. Always state the assumption in the response footer: *"Showing North region — same as your last question."*
2. Offer a correction path: *"Reply with a different region to change this."*
3. Never silently resolve the core metric. Only resolve filter parameters silently.

---

## 8. SQL Agent Retry Loop

With multi-query planning and a real tool-calling loop both in play, there are now **three nested budgets** instead of one, because each layer can multiply the cost of the layer below it. Getting the caps and reset semantics right here is what keeps "agentic" from becoming "runs until the API bill notices."

### The Three Budgets

| | `sql_retry_count` | `tool_call_count` | `refine_count` |
|---|---|---|---|
| Scope | Per sub-query | Per sub-query | Whole turn |
| Triggered by | A failed `execute_sql` call | Any tool call the model makes | Analyst's `check_data_sufficiency` (§9) |
| Fixes | A broken query — bad syntax, wrong column, invalid result | Nothing directly — it's the outer safety valve bounding total tool use, including pure exploration | A query that ran fine but didn't return enough data for the intent |
| Cap | 2 | 6 | 2 |
| Reset | Start of every `sql_agent_loop` invocation | Start of every `sql_agent_loop` invocation | Never reset within a turn |

Plus one global backstop that isn't reset at all within a turn:

```python
total_tool_calls: int   # incremented on every tool call, across every sub-query. Max: 24.
```

### Why the Global Backstop Is the One Doing the Real Work

The local caps alone don't bound worst-case cost once multi-query and tool-calling combine: 3 sub-queries (orchestrator cap, §3.2) × 6 tool calls each (`tool_call_count` cap) = **18 tool calls just for the initial plan**, before the analyst has even had a chance to request a refine. Add up to 2 refine rounds, each re-running one sub-query at up to 6 more tool calls, and the *local* caps alone would allow up to 30. `total_tool_calls < 24` is the actual ceiling — it can cut a refine attempt short before it exhausts its own local budget, and that's intentional: it's the last-resort backstop for the pathological case, not a number expected to bind in normal operation (most sub-queries resolve in 2-3 tool calls: explore, sample, execute).

### Sub-Query Loop — Termination

Each sub-query's `sql_agent_loop` (§3.3) ends one of three ways:

```
model returns a final SQL answer (no more tool_calls)   → status = "done"
sql_retry_count reaches 2 (failed execute_sql attempts)  → status = "failed"
tool_call_count reaches 6, OR total_tool_calls reaches 24 → status = "failed"
```

On `"failed"`, the sub-query does **not** crash the turn. It surfaces a structured failure to whatever asked for it:

```python
{
    "success": False,
    "message": "I wasn't able to retrieve the data for this part of the question. "
               "The most recent error was: {error}. "
               "You may want to rephrase your question or ask about a specific table.",
    "last_sql_attempted": sub_query.sql,
    "error_history": sub_query.error_history
}
```

If one sub-query in a multi-sub-query plan fails while the others succeed, the analyst still gets the successful ones — it decides whether a partial answer is usable or whether the whole turn should surface the failure (see §9).

### Refine Reset Semantics

When the analyst issues a `REFINE_QUERY` signal, `refine_count` increments by 1 and the orchestrator (§3.2) routes back into `sql_agent_loop` for the affected sub-query with **both** `tool_call_count` and `sql_retry_count` reset to 0 — it's a different SQL query with its own independent chance of failing, so it gets its own full budget (bounded, as always, by the shared `total_tool_calls` backstop).

If `refine_count` hits its cap (2) first, the analyst stops asking for more data and reports on the best data it has, stating clearly that the result may be incomplete.

**Worst case per turn:** 3 sub-queries × 6 tool calls, capped overall by `total_tool_calls < 24`, plus up to 2 refine rounds subject to the same shared cap. This is the number to assert against in an integration test guarding against runaway loops — total tool invocations (and therefore roughly total LLM calls) in a single turn should never exceed 24 regardless of how sub-query count, retries, and refine rounds combine.

---

## 9. Analyst Agent Logic

### Report Type → Format Mapping

```python
REPORT_FORMATS = {
    "fact_answer": {
        "template": "{metric_name}: {value}\n\n{one_sentence_context}",
        "example": "Total revenue this quarter: $284,500\n\nThis is 12% higher than last quarter."
    },
    "comparison": {
        "template": "Comparison: {label_a} vs {label_b}\n\n{table}\n\n{summary}",
        "example": "Q1 vs Q2 Revenue\nQ1: $240,000 | Q2: $284,500\nQ2 is 18.5% higher."
    },
    "trend": {
        "template": "{metric} over {period}\n\n{narrative}\n\nDirection: {direction}",
        "example": "Monthly revenue over 6 months shows a steady upward trend, "
                   "growing from $180K in Jan to $284K in Jun. Direction: upward."
    },
    "ranking": {
        "template": "Top {n} {entity} by {metric}\n\n{ranked_list}\n\n{insight}",
        "example": "Top 5 Products by Revenue\n1. Product A — $84,000\n..."
    },
    "alert": {
        "template": "Finding: {finding}\n\nContext: {context}\n\nRecommended action: {action}",
        "example": "Finding: Sales in South region dropped 34% in June.\n..."
    }
}
```

### Analyst Prompt

```
You are a data analyst explaining query results to a non-technical business user.

Rules:
- Never use technical terms (no "SQL", "rows", "NULL", "JOIN")
- Round numbers to 2 decimal places maximum
- Always give a one-sentence interpretation, not just the number
- If the data shows a trend, name the direction explicitly
- If the data is insufficient to draw a conclusion, say so clearly
- Do not invent numbers not present in the data

Report type: {report_type}
User's original question: {resolved_query}
Data returned: {result_table}
Row count: {row_count}

Write the report:
```

### Handling Multiple Sub-Query Results

When the orchestrator (§3.2) split the question into more than one sub-query, the analyst receives the full `sub_queries` list, not a single result. `check_data_sufficiency` (§3.8) now reasons over that list — e.g. a `"comparison"` report needs at least 2 sub-queries with `status == "done"`, not just 2 rows in one result.

**Partial failure:** if one sub-query in the plan comes back `"failed"` (§8) while others succeeded, the analyst does not automatically fail the whole turn. It reports on the sub-queries that did succeed and states plainly which part it couldn't answer — e.g. "Q1 revenue was $240,000. I wasn't able to retrieve Q2 revenue due to a data error, so I can't complete the comparison." This is preferable to discarding a partial answer the user could still act on.

---

## 10. Memory Design

Session memory is not a separate store. It lives directly inside `AgentState` — `active_filters`, `last_metric`, `last_entity`, `turn_history` (see §5) — and is persisted automatically by LangGraph's checkpointer, keyed by `session_id` as the thread ID. Loading memory for a turn is just resuming the graph on the same thread ID; saving it is the checkpoint write LangGraph already does after every node. There is no read/write API to build and no separate dict-or-Redis store to keep in sync with graph state.

### Session Memory Structure

```python
class MemoryTurn(TypedDict):
    turn_id: int
    raw_query: str
    resolved_query: str
    assumptions: List[str]           # ["Region: North", "Period: Q2 2026"]
    sql_executed: str
    result_summary: str              # Short description of what was returned
    timestamp: str
```

`turn_history: List[MemoryTurn]` is the field on `AgentState` that accumulates these across a session.

### Memory Resolution Logic

```python
def memory_can_resolve(query: str, state: AgentState) -> tuple[bool, str]:
    """
    Checks if the query's ambiguity can be resolved from session memory.
    Returns (can_resolve: bool, resolved_value: str)
    """
    # "same as last week but for Q2" — resolve period from query, entity from memory
    if references_prior_context(query):
        prior = state["turn_history"][-1]
        resolved = substitute_context(query, prior)
        return True, resolved
    
    # "now break it down by region" — entity from memory, new dimension added
    if is_follow_up_drill_down(query):
        base = build_from_last_turn(state["turn_history"])
        resolved = add_dimension(base, extract_new_dimension(query))
        return True, resolved
    
    # Active filter can fill the gap
    if missing_filter := detect_missing_filter(query):
        if missing_filter in state["active_filters"]:
            value = state["active_filters"][missing_filter]
            return True, f"Using {missing_filter}: {value} from prior context"
    
    return False, ""
```

### Cross-Turn Example

```
Turn 1: "show me revenue for North region this quarter"
  → active_filters: {region: "North", period: "Q2 2026"}
  → last_metric: "revenue"

Turn 2: "how about the South region?"
  → ambiguity: missing period
  → memory resolves: period = "Q2 2026" from active_filters
  → resolved: "revenue for South region Q2 2026"
  → assumption_note: "Using Q2 2026 — same period as last question"

Turn 3: "what about last quarter?"
  → ambiguity: missing region
  → memory resolves: region = "South" from active_filters (last set)
  → resolved: "revenue for South region Q1 2026"
  → assumption_note: "Showing South region — same as your last question"
```

---

## 11. Evaluation Framework

### Databases for Testing

| Database | Tables | Best For | Setup |
|----------|--------|----------|-------|
| **Chinook** | 11 | Getting started, music domain | `pip install chinook-database` |
| **Northwind** | 13 | Business analytics queries | SQLite file, one import |
| **TPC-H** | 8 | Stress testing, complex joins | `dbgen` CLI tool |
| **BIRD** | 95 DBs | Industry benchmark | Download from bird-bench.github.io |

### Layer 1 — Unit Tests (Per Node)

Test each node in isolation with mocked inputs and outputs.

```python
# Example: SQL agent loop unit test — model self-corrects after a tool result
def test_sql_agent_loop_recovers_from_unknown_column():
    sub_query = SubQuery(intent="total revenue this quarter")
    stub_llm = StubLLM(responses=[
        ToolCall("execute_sql", {"sql": "SELECT SUM(revenue) FROM Invoice"}),   # wrong column
        ToolCall("execute_sql", {"sql": "SELECT SUM(Total) FROM Invoice"}),     # corrected after hint
    ])

    result = sql_agent_loop(sub_query, state=fresh_state(), llm=stub_llm)

    assert "Total" in result.sql          # Model used the corrective hint itself
    assert "revenue" not in result.sql    # Dropped the incorrect column name
    assert result.sql_retry_count == 1
    assert result.status == "done"

# Example: orchestrator unit test — prefers a single query when unifiable
def test_orchestrator_does_not_split_a_unifiable_trend():
    plan = orchestrator_node(AgentState(resolved_query="monthly revenue for the last 6 months"))

    assert len(plan.sub_queries) == 1   # GROUP BY month covers this in one query

# Example: Clarification node unit test  
def test_clarification_fires_for_missing_time_filter():
    state = AgentState(
        raw_query="show me sales",
        turn_history=[],
        active_filters={}
    )
    result = clarification_node(state)
    
    assert result.status == "awaiting_user"
    assert result.clarification_request is not None
    assert "?" in result.clarification_request   # Is a question
```

**Unit test checklist:**

- [ ] Schema explorer returns correct table list for Chinook, and `table_hint` actually filters
- [ ] SQL agent loop produces valid syntax for 20 query types across a range of tool-call sequences
- [ ] Error classifier correctly labels all 6 error types
- [ ] SQL agent loop self-corrects based on the attached corrective hint, without a graph-level retry edge
- [ ] Orchestrator keeps single-query-unifiable comparisons/trends as 1 sub-query
- [ ] Orchestrator splits genuinely independent analyses into 2-3 sub-queries, never more than 3
- [ ] Result validator catches zero-row false negatives (but not for aggregates — zero is valid there)
- [ ] Result validator catches implausibly large result sets
- [ ] Clarification node fires for missing time filter
- [ ] Clarification node fires for vague intent
- [ ] Memory resolver correctly uses active filters
- [ ] Analyst correctly classifies trend vs fact queries
- [ ] Analyst's `check_data_sufficiency` reasons over the whole sub_queries list, not one result
- [ ] Analyst reports partial results plainly when one sub-query in a plan failed

---

### Layer 2 — Integration Tests (Loop Behavior)

Test the full loop end-to-end on Chinook with injected faults.

```python
# Fault injection test harness
class FaultInjector:
    def inject_syntax_error(self, sql: str) -> str:
        """Corrupt the SQL to trigger syntax error retry"""
        return sql.replace("SELECT", "SLECT")
    
    def inject_unknown_column(self, sql: str) -> str:
        """Replace a valid column with a fake one"""
        return re.sub(r'\b(Total|InvoiceDate)\b', 'fake_column', sql, count=1)
    
    def inject_empty_result(self, engine) -> Engine:
        """Return engine connected to empty DB"""
        return create_empty_db_engine()
    
    def inject_schema_rename(self, schema: dict) -> dict:
        """Rename a table to simulate schema drift"""
        schema["Invoice_OLD"] = schema.pop("Invoice")
        return schema

# Integration test: retry loop recovers from syntax error
def test_retry_recovers_from_syntax_error():
    injector = FaultInjector()
    
    # Override executor to inject fault on first call only
    call_count = 0
    def patched_executor(sql):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return execute_sql(injector.inject_syntax_error(sql))
        return execute_sql(sql)
    
    result = run_agent(
        query="total invoice amount this year",
        executor=patched_executor
    )
    
    assert result.status == "done"
    assert result.sub_queries[0].sql_retry_count == 1
    assert result.final_report is not None

# Integration test: memory resolves follow-up
def test_memory_resolves_region_follow_up():
    session = new_session()   # thread_id passed to the LangGraph checkpointer
    
    run_agent("revenue for North region this quarter", session=session)
    result = run_agent("how about South region?", session=session)
    
    assert "Q2" in result.sub_queries[0].sql      # Period from memory
    assert "South" in result.sub_queries[0].sql   # New region from query
    assert result.assumption_note is not None

# Integration test: orchestrator splits an independent comparison into two sub-queries
def test_orchestrator_splits_comparison():
    result = run_agent(query="compare signup rate vs refund rate this month")

    assert len(result.sub_queries) == 2
    assert all(sq.status == "done" for sq in result.sub_queries)

# Integration test: global tool-call backstop stops a runaway sub-query
def test_total_tool_calls_backstop_halts_runaway_agent():
    result = run_agent(
        query="an intentionally hard question that never resolves",
        llm=StubLLM(always_calls_tool="explore_schema")  # never emits a final SQL
    )

    assert result.total_tool_calls <= 24
    assert result.status == "failed"
```

**Integration test checklist:**

- [ ] Agent retries on injected syntax error and succeeds within 2 attempts
- [ ] Agent retries on unknown column and re-explores schema on its own initiative
- [ ] Orchestrator keeps a unifiable comparison/trend as a single sub-query (doesn't over-split)
- [ ] Orchestrator splits a genuinely independent comparison into 2+ sub-queries, capped at 3
- [ ] Ambiguous query triggers clarification node, not silent guess
- [ ] Clear query passes through without asking anything
- [ ] Memory resolves follow-up query without re-asking
- [ ] Analyst feedback loop fires when a sub-query's result is insufficient for its report type
- [ ] Refined query from the orchestrator produces sufficient data
- [ ] A failed sub-query doesn't sink the whole turn if others in the plan succeeded
- [ ] Max retry limit (per sub-query) and the global total_tool_calls backstop both stop runaway loops and return graceful failure
- [ ] Multi-turn conversation maintains correct active_filters
- [ ] Session state doesn't bleed between different sessions

---

### Layer 3 — Answer Quality (LLM-as-Judge)

Evaluate the final response quality using a second LLM as a scorer.

#### Gold Standard Question Set (Chinook)

```python
GOLD_QUESTIONS = [
    {
        "question": "What is the total revenue from all invoices?",
        "gold_sql": "SELECT SUM(Total) FROM Invoice",
        "gold_answer": 2328.60,
        "tolerance": 0.01
    },
    {
        "question": "Who are the top 5 customers by total spending?",
        "gold_sql": """
            SELECT c.FirstName || ' ' || c.LastName, SUM(i.Total)
            FROM Customer c JOIN Invoice i ON c.CustomerId = i.CustomerId
            GROUP BY c.CustomerId ORDER BY SUM(i.Total) DESC LIMIT 5
        """,
        "gold_answer": ["Helena Holý", "Richard Cunningham", ...],
        "type": "ranking"
    },
    {
        "question": "Show me monthly revenue for 2013",
        "gold_sql": """
            SELECT strftime('%m', InvoiceDate) as month, SUM(Total)
            FROM Invoice WHERE strftime('%Y', InvoiceDate) = '2013'
            GROUP BY month ORDER BY month
        """,
        "type": "trend",
        "min_rows": 12
    },
    # ... 17 more gold questions covering all query types
]
```

#### LLM Judge Prompt

```
You are an evaluator for a text-to-SQL agent system.

Score the agent's response on the following criteria (1–5 each):

1. ACCURACY: Does the data in the response match the correct answer?
2. FAITHFULNESS: Does the explanation accurately reflect the data (no invented numbers)?
3. CLARITY: Is the explanation understandable to a non-technical user?
4. COMPLETENESS: Does the response fully answer the original question?
5. APPROPRIATE_REFUSAL: If data was unavailable, did the agent say so clearly?

Original question: {question}
Correct answer: {gold_answer}
Agent response: {agent_response}
Data returned by SQL: {raw_data}

Respond in JSON:
{
  "accuracy": 1–5,
  "faithfulness": 1–5,
  "clarity": 1–5,
  "completeness": 1–5,
  "appropriate_refusal": 1–5,
  "overall": 1–5,
  "reasoning": "one sentence explanation"
}
```

#### Execution Accuracy (Primary Metric)

```python
def execution_accuracy(agent_sql: str, gold_sql: str, engine) -> bool:
    """
    True if agent SQL returns the same result as gold SQL.
    Does not require identical SQL — only identical output.
    """
    agent_result = set(map(tuple, execute_sql(agent_sql).rows))
    gold_result = set(map(tuple, execute_sql(gold_sql).rows))
    return agent_result == gold_result
```

#### Running the Eval Suite

```python
def run_full_eval(agent, questions=GOLD_QUESTIONS, judge_model="claude-sonnet-4-6"):
    results = []
    for q in questions:
        response = agent.run(q["question"])
        
        # Execution accuracy — GOLD_QUESTIONS are single-query, so compare against
        # sub_queries[0]. A gold question that genuinely needs multiple sub-queries
        # would compare the full set instead.
        exec_acc = execution_accuracy(
            response.sub_queries[0].sql,
            q["gold_sql"],
            engine
        )
        
        # LLM judge scores
        judge_scores = llm_judge(
            question=q["question"],
            gold_answer=q["gold_answer"],
            agent_response=response.final_report,
            raw_data=response.sub_queries[0].result,
            model=judge_model
        )
        
        results.append({
            "question": q["question"],
            "execution_accurate": exec_acc,
            "sub_query_count": len(response.sub_queries),
            "sql_retry_count": response.sub_queries[0].sql_retry_count,
            "total_tool_calls": response.total_tool_calls,
            "clarification_fired": response.ambiguity_type != "clear",
            **judge_scores
        })
    
    return EvalReport(results)
```

---

### Eval Tools

| Tool | Purpose | When to Use |
|------|---------|-------------|
| **LangSmith** | Node-level tracing, token usage, dataset evals | Throughout development |
| **DeepEval** | Hallucination, answer relevancy, faithfulness scores | Layer 3 quality eval |
| **BIRD benchmark** | Industry-standard NL-to-SQL benchmark (95 DBs) | Final performance validation |
| **Fault injector** | Deliberate error injection for retry testing | Layer 2 integration testing |
| **Custom LLM judge** | Scores answer quality with rubric | Layer 3 subjective quality |

---

## 12. KPIs and Metrics

### Primary KPIs

| KPI | Definition | Target | How to Measure |
|-----|-----------|--------|----------------|
| **Execution accuracy** | % of queries returning same rows as gold SQL | > 60% on the Chinook gold set (> 70% stretch); > 50% on BIRD (harder, held-out — see below) | Compare agent SQL vs gold SQL output |
| **First-attempt success rate** | % of sub-queries that succeed without a failed `execute_sql` call | > 70% | Count `sub_query.sql_retry_count == 0` |
| **Orchestrator split precision** | % of multi-sub-query plans where the split was actually necessary (not unifiable in one query) | > 85% | Human label on a sample of plans with `len(sub_queries) > 1` |
| **Clarification precision** | % of clarification requests that were genuinely needed | > 85% | Human label: was the question necessary? |
| **Hallucination rate** | % of reports containing numbers not in the data | < 5% | DeepEval faithfulness metric |
| **Memory resolution rate** | % of follow-up queries resolved without re-asking | > 80% | Count memory_resolves == True |

### Secondary KPIs

| KPI | Definition | Target |
|-----|-----------|--------|
| **Retry convergence rate** | % of retried queries that eventually succeed | > 80% |
| **Loop termination rate** | % of sessions that complete without hitting max retry | > 95% |
| **End-to-end latency** | Time from query to response | < 10s simple, < 30s complex |
| **LLM judge clarity score** | Average non-technical clarity score (1–5) | > 4.0 |
| **Answer completeness** | LLM judge completeness score | > 4.0 |

### BIRD Benchmark Baseline

Current published results for reference:

| System | BIRD Execution Accuracy |
|--------|------------------------|
| GPT-4 + simple prompt | ~55% |
| GPT-4 + chain-of-thought | ~60% |
| Fine-tuned specialist models | ~65–70% |
| **Your target (LangGraph agent)** | **> 50%** |

Hitting 50%+ on BIRD with a LangGraph agent using the retry loop and schema re-exploration is a strong result.

---

## 13. Project Structure

```
text_to_sql_agent/
│
├── agent/
│   ├── __init__.py
│   ├── graph.py              # LangGraph graph definition, node wiring
│   ├── state.py              # AgentState TypedDict definition
│   ├── nodes/
│   │   ├── clarification.py  # Ambiguity classifier + resolution
│   │   ├── orchestrator.py   # Sub-query planner (1-3 per turn)
│   │   ├── sql_agent.py      # Tool-calling loop + result validator
│   │   └── analyst.py        # Report classifier + explanation generator
│   └── tools/
│       ├── db_tools.py       # explore_schema, execute_sql, get_sample_rows
│       └── analyst_tools.py  # format_currency, detect_trend, summarize_table
│
├── eval/
│   ├── gold_questions.py     # GOLD_QUESTIONS list for Chinook
│   ├── fault_injector.py     # FaultInjector class
│   ├── llm_judge.py          # LLM-as-judge scorer
│   ├── execution_accuracy.py # Compare agent SQL vs gold SQL output
│   └── run_eval.py           # Full eval suite runner
│
├── db/
│   ├── chinook.db            # Chinook SQLite database
│   ├── northwind.db          # Northwind SQLite database
│   └── loader.py             # DB connection factory
│
├── tests/
│   ├── unit/
│   │   ├── test_clarification.py
│   │   ├── test_orchestrator.py
│   │   ├── test_sql_agent_loop.py
│   │   ├── test_error_classifier.py
│   │   ├── test_result_validator.py
│   │   └── test_analyst.py
│   └── integration/
│       ├── test_sql_agent_budgets.py   # sql_retry_count, tool_call_count, total_tool_calls
│       ├── test_multi_query.py         # orchestrator split/no-split, partial sub-query failure
│       ├── test_memory_resolution.py
│       ├── test_analyst_feedback.py
│       └── test_full_flow.py
│
├── config.py                 # Model names, max retries, thresholds
├── requirements.txt
└── README.md
```

---

## 14. Tech Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| Agent framework | **LangGraph** | Stateful graph, explicit loops, HITL support |
| LLM | **Claude Sonnet (claude-sonnet-4-6)** | Strong SQL generation, instruction following |
| Database | **SQLite (Chinook / Northwind)** | Zero setup, realistic schema |
| DB interface | **SQLAlchemy** | Safe parameterized queries |
| Tracing | **LangSmith** | Node-level traces, token cost per node |
| Eval framework | **DeepEval** | Built-in hallucination + faithfulness metrics |
| Benchmark | **BIRD** | Industry-standard NL-to-SQL test set |
| Testing | **pytest** | Unit + integration tests |
| Memory | **LangGraph checkpointer** (`MemorySaver` dev, `SqliteSaver` for persistence) | Session state across turns, keyed by `session_id` |

### Key Dependencies

```txt
langgraph>=0.2.0
langchain>=0.3.0
langchain-anthropic>=0.2.0
sqlalchemy>=2.0.0
deepeval>=1.0.0
langsmith>=0.1.0
pytest>=8.0.0
pydantic>=2.0.0
```

---


*End of specification.*
