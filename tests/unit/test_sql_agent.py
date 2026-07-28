from agent.nodes.sql_agent import _invoke_tool, infer_intent, validate_result
from agent.state import ExecutionResult


class TestInferIntent:
    def test_aggregate_keywords(self):
        assert infer_intent("total revenue this quarter").type == "aggregate"

    def test_fetch_keywords(self):
        intent = infer_intent("show me sales")
        assert intent.type == "fetch"
        assert intent.expects_data is True

    def test_existence_keywords(self):
        intent = infer_intent("does customer X exist")
        assert intent.type == "existence"
        assert intent.expects_data is False

    def test_plain_fetch_does_not_expect_a_large_result(self):
        assert infer_intent("show me sales").expects_large_result is False

    def test_explicit_all_signals_a_large_result_is_expected(self):
        assert infer_intent("list every transaction").expects_large_result is True


class TestValidateResult:
    def test_zero_row_aggregate_is_valid_not_a_bug(self):
        """This is the exact bug the design spec review caught and fixed:
        a SUM/COUNT returning 0 is a real answer, not a sign of a broken query."""
        result = ExecutionResult(success=True, rows=[(0,)], columns=["total"], row_count=1)
        verdict, _ = validate_result(result, infer_intent("total revenue for an empty region"))
        assert verdict == "VALID"

    def test_zero_rows_on_fetch_query_needs_requery(self):
        result = ExecutionResult(success=True, rows=[], columns=[], row_count=0)
        verdict, _ = validate_result(result, infer_intent("show me sales"))
        assert verdict == "REQUERY_NEEDED"

    def test_zero_rows_on_existence_query_is_valid(self):
        result = ExecutionResult(success=True, rows=[], columns=[], row_count=0)
        verdict, _ = validate_result(result, infer_intent("does customer X exist"))
        assert verdict == "VALID"

    def test_oversized_result_needs_requery(self):
        result = ExecutionResult(
            success=True, rows=[(i,) for i in range(10)], columns=["id"], row_count=10001
        )
        verdict, _ = validate_result(result, infer_intent("show me sales"))
        assert verdict == "REQUERY_NEEDED"

    def test_plausible_result_is_valid(self):
        result = ExecutionResult(success=True, rows=[(2328.6,)], columns=["total"], row_count=1)
        verdict, _ = validate_result(result, infer_intent("total revenue"))
        assert verdict == "VALID"


class TestInvokeTool:
    def test_real_tool_call_against_database(self):
        call = {"name": "execute_sql", "args": {"sql": "SELECT COUNT(*) FROM Customer"}, "id": "1"}
        result = _invoke_tool(call)
        assert result["success"] is True

    def test_unknown_tool_name_fails_gracefully_instead_of_crashing(self):
        call = {"name": "not_a_real_tool", "args": {}, "id": "1"}
        result = _invoke_tool(call)
        assert result["success"] is False
