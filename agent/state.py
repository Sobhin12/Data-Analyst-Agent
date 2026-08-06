"""Shared state for the text-to-SQL LangGraph agent.

See docs/text_to_sql_agent_design_spec.md §5 for the design rationale.
"""

from dataclasses import dataclass, field
from typing import Optional, TypedDict


@dataclass
class ExecutionResult:
    success: bool
    rows: list[tuple] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    row_count: int = 0
    error: Optional[str] = None
    error_type: Optional[str] = None


@dataclass
class SubQuery:
    intent: str
    sql: Optional[str] = None
    result: Optional[ExecutionResult] = None
    tool_call_count: int = 0
    sql_retry_count: int = 0
    error_history: list[str] = field(default_factory=list)
    status: str = "pending"  # "pending" | "done" | "failed"


class AgentState(TypedDict, total=False):
    # Input
    raw_query: str
    session_id: str

    # Orchestrator: ambiguity gate + planning
    ambiguity_type: str  # "missing_filter" | "vague_intent" | "clear"
    resolved_query: Optional[str]
    assumption_note: Optional[str]
    clarification_request: Optional[str]
    option_cards: Optional[list[dict]]
    execution_plan: Optional[dict]

    # SQL Agent
    schema_snapshot: Optional[dict]
    sub_queries: list[SubQuery]
    current_sub_query_idx: int
    total_tool_calls: int

    # Analyst
    report_type: Optional[str]
    data_sufficient: Optional[bool]
    refine_request: Optional[str]
    refine_count: int
    final_report: Optional[str]

    # Memory (persisted automatically by the LangGraph checkpointer). The
    # orchestrator reads recent entries as free-text context for planning --
    # see agent/nodes/orchestrator.py.
    turn_history: list[dict]

    # Control
    status: str  # "running" | "awaiting_user" | "done" | "failed"
    error: Optional[str]


def new_state(raw_query: str, session_id: str) -> AgentState:
    """Fresh state for a new turn, seeded with sane defaults for every counter."""
    return AgentState(
        raw_query=raw_query,
        session_id=session_id,
        ambiguity_type="clear",
        resolved_query=None,
        assumption_note=None,
        clarification_request=None,
        option_cards=None,
        execution_plan=None,
        schema_snapshot=None,
        sub_queries=[],
        current_sub_query_idx=0,
        total_tool_calls=0,
        report_type=None,
        data_sufficient=None,
        refine_request=None,
        refine_count=0,
        final_report=None,
        turn_history=[],
        status="running",
        error=None,
    )
