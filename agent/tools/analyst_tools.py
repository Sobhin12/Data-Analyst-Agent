"""Deterministic formatting helpers used by the analyst node (agent/nodes/analyst.py).

See docs/text_to_sql_agent_design_spec.md §6, §9. Unlike the SQL agent's tools,
these are plain functions called directly by node code before/while building
the analyst's prompt -- arithmetic and formatting are more reliable done in
Python than left to the model, and the analyst doesn't need autonomy over
which of these to use.
"""


def calculate_percentage_change(old: float, new: float) -> str:
    """(old, new) -> a signed, human-readable percentage change string."""
    if old == 0:
        return "N/A (no prior value to compare against)"
    change = (new - old) / abs(old) * 100
    sign = "+" if change >= 0 else ""
    return f"{sign}{change:.1f}%"


def format_currency(value: float) -> str:
    """284500 -> "$284,500.00" """
    return f"${value:,.2f}"


def format_large_number(value: float) -> str:
    """1200000 -> "1.2M"; 45000 -> "45.0K"; 900 -> "900" """
    abs_value = abs(value)
    if abs_value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.1f}B"
    if abs_value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if abs_value >= 1_000:
        return f"{value / 1_000:.1f}K"
    return f"{value:.0f}" if float(value).is_integer() else f"{value:.2f}"


def detect_trend_direction(values: list[float]) -> str:
    """List of values in time order -> "upward" | "downward" | "flat" """
    if len(values) < 2:
        return "flat"
    first, last = values[0], values[-1]
    if first == 0:
        return "flat" if last == 0 else ("upward" if last > 0 else "downward")
    change_ratio = (last - first) / abs(first)
    if change_ratio > 0.05:
        return "upward"
    if change_ratio < -0.05:
        return "downward"
    return "flat"


def summarize_table(rows: list[tuple], columns: list[str]) -> str:
    """Rows + column names -> a short, plain-text description for the analyst prompt."""
    if not rows:
        return "No rows returned."
    preview_rows = rows[:10]
    lines = [", ".join(columns)]
    for row in preview_rows:
        lines.append(", ".join(str(v) for v in row))
    summary = "\n".join(lines)
    if len(rows) > len(preview_rows):
        summary += f"\n... and {len(rows) - len(preview_rows)} more row(s)"
    return summary
