"""Tools bound to the SQL agent's tool-calling loop (agent/nodes/sql_agent.py).

See docs/text_to_sql_agent_design_spec.md §3.3-3.6 and §6. These are called by
the model itself via function-calling -- nothing here is invoked by node code
ahead of time.
"""

import re

from langchain_core.tools import tool
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

from agent.state import ExecutionResult
from db.loader import get_engine

_FORBIDDEN_KEYWORDS = (
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "ALTER",
    "CREATE",
    "ATTACH",
    "DETACH",
    "PRAGMA",
    "REPLACE",
    "TRUNCATE",
    "VACUUM",
)

_ERROR_PATTERNS = {
    "SYNTAX_ERROR": ["syntax error", "unexpected token", "incomplete input"],
    "UNKNOWN_COLUMN": ["no such column", "unknown column"],
    "UNKNOWN_TABLE": ["no such table", "relation does not exist"],
    "TYPE_MISMATCH": ["type mismatch", "invalid input syntax", "datatype mismatch"],
    "AMBIGUOUS_COLUMN": ["ambiguous column"],
    "TIMEOUT": ["timeout", "statement timeout"],
}


def is_select_query(sql: str) -> bool:
    """Allowlist check: single, read-only SELECT/CTE statement only.

    Deliberately conservative -- rejects anything with a leftover semicolon
    (stacked statements) even if the second statement would've been benign,
    and rejects forbidden keywords appearing anywhere, including inside
    comments, since a comment is not a safe place to hide a keyword either.
    """
    stripped = sql.strip()
    if not stripped:
        return False

    # Strip one trailing semicolon; anything left after that is a second statement.
    body = stripped[:-1] if stripped.endswith(";") else stripped
    if ";" in body:
        return False

    upper = body.upper()
    for keyword in _FORBIDDEN_KEYWORDS:
        if re.search(rf"\b{keyword}\b", upper):
            return False

    first_token = re.match(r"\s*(\w+)", upper)
    if not first_token or first_token.group(1) not in ("SELECT", "WITH"):
        return False

    return True


def classify_sql_error(error_message: str) -> str:
    """Categorizes a failed execute_sql error message. See spec §3.6."""
    lowered = error_message.lower()
    for error_type, signals in _ERROR_PATTERNS.items():
        if any(signal in lowered for signal in signals):
            return error_type
    return "UNKNOWN"


def _get_sample_values(table: str, n: int = 3) -> dict[str, list]:
    """Distinct sample values per column, used to catch case-mismatch filters."""
    engine = get_engine()
    inspector = inspect(engine)
    samples: dict[str, list] = {}
    with engine.connect() as conn:
        for column in inspector.get_columns(table):
            col_name = column["name"]
            try:
                result = conn.execute(
                    text(f'SELECT DISTINCT "{col_name}" FROM "{table}" LIMIT :n'),
                    {"n": n},
                )
                samples[col_name] = [row[0] for row in result.fetchall()]
            except SQLAlchemyError:
                samples[col_name] = []
    return samples


@tool
def explore_schema(table_hint: str | None = None) -> dict:
    """Returns table names, column names, data types, foreign keys, and sample values.

    Call this first when you don't already know the exact table/column names
    or the exact casing of string values you'll need to filter on.

    Args:
        table_hint: If given, only this table's details are returned (cheaper
            than fetching the whole schema). Omit to get every table.
    """
    engine = get_engine()
    inspector = inspect(engine)
    tables = [table_hint] if table_hint else inspector.get_table_names()

    schema = {}
    for table in tables:
        if table not in inspector.get_table_names():
            continue
        columns = inspector.get_columns(table)
        fk = inspector.get_foreign_keys(table)
        schema[table] = {
            "columns": [{"name": c["name"], "type": str(c["type"])} for c in columns],
            "foreign_keys": fk,
            "sample_values": _get_sample_values(table),
        }
    return schema


@tool
def execute_sql(sql: str) -> dict:
    """Executes a single read-only SQL query and returns rows or a structured error.

    SELECT (and read-only WITH/CTE) only -- any other statement, or a stacked
    second statement, is rejected before it reaches the database. On failure
    the result includes an error_type and a corrective hint; read it and
    adjust your next query instead of repeating the same one.
    """
    if not is_select_query(sql):
        return ExecutionResult(
            success=False,
            error="Only a single read-only SELECT statement is permitted.",
            error_type="FORBIDDEN_STATEMENT",
        ).__dict__

    engine = get_engine()
    try:
        with engine.connect() as conn:
            result = conn.execute(text(sql))
            rows = result.fetchall()
            columns = list(result.keys())
            return ExecutionResult(
                success=True,
                rows=[tuple(row) for row in rows],
                columns=columns,
                row_count=len(rows),
            ).__dict__
    except SQLAlchemyError as e:
        message = str(e.orig) if getattr(e, "orig", None) else str(e)
        return ExecutionResult(
            success=False,
            error=message,
            error_type=classify_sql_error(message),
        ).__dict__


@tool
def get_sample_rows(table: str, n: int = 5) -> dict:
    """Fetches N full sample rows from a table (not just column names/types).

    Useful when explore_schema's per-column sample values aren't enough
    context -- e.g. to see how columns relate to each other within a row.
    """
    engine = get_engine()
    try:
        with engine.connect() as conn:
            result = conn.execute(text(f'SELECT * FROM "{table}" LIMIT :n'), {"n": n})
            rows = result.fetchall()
            return {
                "success": True,
                "columns": list(result.keys()),
                "rows": [tuple(row) for row in rows],
            }
    except SQLAlchemyError as e:
        return {"success": False, "error": str(e.orig) if getattr(e, "orig", None) else str(e)}


@tool
def get_column_stats(table: str, column: str) -> dict:
    """Returns min, max, distinct count, and null count for one column.

    Use this to sanity-check a filter value's plausible range (e.g. before
    filtering a date column, or picking a numeric threshold) without pulling
    full rows.
    """
    engine = get_engine()
    try:
        with engine.connect() as conn:
            result = conn.execute(
                text(
                    f'SELECT MIN("{column}"), MAX("{column}"), '
                    f'COUNT(DISTINCT "{column}"), '
                    f'SUM(CASE WHEN "{column}" IS NULL THEN 1 ELSE 0 END) '
                    f'FROM "{table}"'
                )
            )
            min_val, max_val, distinct_count, null_count = result.fetchone()
            return {
                "success": True,
                "min": min_val,
                "max": max_val,
                "distinct_count": distinct_count,
                "null_count": null_count,
            }
    except SQLAlchemyError as e:
        return {"success": False, "error": str(e.orig) if getattr(e, "orig", None) else str(e)}


@tool
def check_table_exists(table: str) -> bool:
    """Boolean check for whether a table exists, before writing a query against it."""
    engine = get_engine()
    inspector = inspect(engine)
    return table in inspector.get_table_names()


tools_sql_agent = [
    explore_schema,
    execute_sql,
    get_sample_rows,
    get_column_stats,
    check_table_exists,
]
