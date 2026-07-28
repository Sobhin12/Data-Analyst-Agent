from agent.tools.db_tools import (
    check_table_exists,
    classify_sql_error,
    execute_sql,
    explore_schema,
    get_column_stats,
    get_sample_rows,
    is_select_query,
)


class TestIsSelectQuery:
    def test_accepts_plain_select(self):
        assert is_select_query("SELECT 1")

    def test_accepts_select_with_trailing_semicolon(self):
        assert is_select_query("SELECT * FROM Invoice;")

    def test_accepts_cte(self):
        assert is_select_query("WITH t AS (SELECT 1) SELECT * FROM t")

    def test_rejects_stacked_statements(self):
        assert not is_select_query("SELECT 1; DROP TABLE Invoice")

    def test_rejects_drop(self):
        assert not is_select_query("DROP TABLE Invoice")

    def test_rejects_insert(self):
        assert not is_select_query("INSERT INTO Invoice VALUES (1)")

    def test_rejects_pragma(self):
        assert not is_select_query("PRAGMA table_info(Invoice)")

    def test_rejects_empty_string(self):
        assert not is_select_query("")


class TestClassifySqlError:
    def test_unknown_column(self):
        assert classify_sql_error("no such column: revenue") == "UNKNOWN_COLUMN"

    def test_unknown_table(self):
        assert classify_sql_error("no such table: Invoices") == "UNKNOWN_TABLE"

    def test_syntax_error(self):
        assert classify_sql_error("syntax error near SLECT") == "SYNTAX_ERROR"

    def test_unrecognized_falls_back_to_unknown(self):
        assert classify_sql_error("some brand new sqlite error") == "UNKNOWN"


class TestExecuteSql:
    def test_success_returns_rows(self):
        result = execute_sql.invoke({"sql": "SELECT SUM(Total) FROM Invoice"})
        assert result["success"] is True
        assert result["rows"] == [(2328.6,)]

    def test_failure_classifies_error(self):
        result = execute_sql.invoke({"sql": "SELECT SUM(revenue) FROM Invoice"})
        assert result["success"] is False
        assert result["error_type"] == "UNKNOWN_COLUMN"

    def test_write_is_blocked_before_reaching_the_database(self):
        result = execute_sql.invoke({"sql": "DROP TABLE Invoice"})
        assert result["success"] is False
        assert result["error_type"] == "FORBIDDEN_STATEMENT"

    def test_zero_rows_is_a_successful_empty_result_not_an_error(self):
        result = execute_sql.invoke(
            {"sql": "SELECT * FROM Invoice WHERE InvoiceId = -1"}
        )
        assert result["success"] is True
        assert result["row_count"] == 0


class TestSchemaExplorer:
    def test_table_hint_filters_to_one_table(self):
        schema = explore_schema.invoke({"table_hint": "Invoice"})
        assert list(schema.keys()) == ["Invoice"]

    def test_no_hint_returns_all_tables(self):
        schema = explore_schema.invoke({"table_hint": None})
        assert "Invoice" in schema
        assert "Customer" in schema
        assert len(schema) > 5

    def test_sample_values_present_for_columns(self):
        schema = explore_schema.invoke({"table_hint": "Customer"})
        assert schema["Customer"]["sample_values"]


class TestOtherTools:
    def test_check_table_exists_true(self):
        assert check_table_exists.invoke({"table": "Invoice"}) is True

    def test_check_table_exists_false(self):
        assert check_table_exists.invoke({"table": "NotARealTable"}) is False

    def test_get_column_stats(self):
        stats = get_column_stats.invoke({"table": "Invoice", "column": "Total"})
        assert stats["success"] is True
        assert stats["min"] is not None
        assert stats["max"] is not None

    def test_get_sample_rows(self):
        rows = get_sample_rows.invoke({"table": "Customer", "n": 3})
        assert rows["success"] is True
        assert len(rows["rows"]) == 3
