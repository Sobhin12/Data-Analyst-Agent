from agent.nodes.analyst import (
    check_data_sufficiency,
    classify_report_type,
    extract_filters,
    extract_metric,
    extract_requested_n,
)
from agent.state import ExecutionResult, SubQuery


def _done(row_count: int) -> SubQuery:
    return SubQuery(
        intent="x",
        status="done",
        result=ExecutionResult(success=True, rows=[(1,)] * row_count, columns=["c"], row_count=row_count),
    )


def _failed() -> SubQuery:
    return SubQuery(intent="y", status="failed")


class TestClassifyReportType:
    def test_ranking(self):
        assert classify_report_type("top 5 customers by spending", []) == "ranking"

    def test_comparison_from_multiple_sub_queries(self):
        assert classify_report_type("anything", [SubQuery("a"), SubQuery("b")]) == "comparison"

    def test_comparison_from_keyword(self):
        assert classify_report_type("compare Q1 vs Q2 revenue", []) == "comparison"

    def test_trend(self):
        assert classify_report_type("monthly revenue trend", []) == "trend"

    def test_fact_is_the_default(self):
        assert classify_report_type("total revenue this quarter", []) == "fact"


class TestCheckDataSufficiency:
    def test_trend_needs_at_least_3_rows(self):
        assert check_data_sufficiency([_done(2)], "trend") is False
        assert check_data_sufficiency([_done(3)], "trend") is True

    def test_comparison_needs_2_successful_sub_queries(self):
        assert check_data_sufficiency([_done(1)], "comparison") is False
        assert check_data_sufficiency([_done(1), _done(1)], "comparison") is True

    def test_comparison_with_one_failed_sub_query_is_insufficient(self):
        assert check_data_sufficiency([_done(1), _failed()], "comparison") is False

    def test_ranking_needs_requested_row_count(self):
        assert check_data_sufficiency([_done(3)], "ranking", requested_n=5) is False
        assert check_data_sufficiency([_done(5)], "ranking", requested_n=5) is True

    def test_fact_needs_all_sub_queries_done(self):
        assert check_data_sufficiency([_done(1), _done(1)], "fact") is True
        assert check_data_sufficiency([_done(1), _failed()], "fact") is False


class TestExtractHelpers:
    def test_extract_requested_n(self):
        assert extract_requested_n("top 5 customers") == 5
        assert extract_requested_n("total revenue") is None

    def test_extract_filters(self):
        filters = extract_filters("revenue for North region this quarter")
        assert filters["region"] == "North"
        assert "quarter" in filters["period"]

    def test_extract_metric(self):
        assert extract_metric("how about South region revenue") == "revenue"
        assert extract_metric("nothing relevant here") is None
