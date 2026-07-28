from agent.tools.analyst_tools import (
    calculate_percentage_change,
    detect_trend_direction,
    format_currency,
    format_large_number,
    summarize_table,
)


def test_calculate_percentage_change_matches_spec_example():
    assert calculate_percentage_change(240000, 284500) == "+18.5%"


def test_calculate_percentage_change_handles_zero_baseline():
    assert calculate_percentage_change(0, 100) == "N/A (no prior value to compare against)"


def test_calculate_percentage_change_negative():
    assert calculate_percentage_change(100, 80) == "-20.0%"


def test_format_currency():
    assert format_currency(284500) == "$284,500.00"


def test_format_large_number_millions():
    assert format_large_number(1200000) == "1.2M"


def test_format_large_number_thousands():
    assert format_large_number(45000) == "45.0K"


def test_format_large_number_small_integer():
    assert format_large_number(42) == "42"


def test_detect_trend_direction_upward():
    assert detect_trend_direction([180000, 190000, 210000, 250000, 270000, 284000]) == "upward"


def test_detect_trend_direction_downward():
    assert detect_trend_direction([100, 90, 60]) == "downward"


def test_detect_trend_direction_flat_for_small_change():
    assert detect_trend_direction([100, 100, 101]) == "flat"


def test_detect_trend_direction_needs_two_points():
    assert detect_trend_direction([100]) == "flat"


def test_summarize_table_empty():
    assert summarize_table([], ["a"]) == "No rows returned."


def test_summarize_table_truncates_long_results():
    rows = [(i,) for i in range(20)]
    summary = summarize_table(rows, ["id"])
    assert "more row(s)" in summary
