from eval.fault_injector import FaultInjector


def test_inject_syntax_error():
    injector = FaultInjector()
    corrupted = injector.inject_syntax_error("SELECT SUM(Total) FROM Invoice")
    assert corrupted == "SLECT SUM(Total) FROM Invoice"


def test_inject_unknown_column_replaces_a_real_column():
    injector = FaultInjector()
    corrupted = injector.inject_unknown_column(
        "SELECT Total, InvoiceDate FROM Invoice", ["Total", "InvoiceDate"]
    )
    assert "fake_column" in corrupted
    assert "Total" not in corrupted or corrupted.count("Total") == 0


def test_inject_unknown_column_leaves_sql_untouched_if_no_match():
    injector = FaultInjector()
    sql = "SELECT COUNT(*) FROM Genre"
    assert injector.inject_unknown_column(sql, ["Total"]) == sql


def test_inject_empty_db_engine_has_no_tables():
    injector = FaultInjector()
    from sqlalchemy import inspect

    engine = injector.inject_empty_db_engine()
    assert inspect(engine).get_table_names() == []


def test_inject_schema_rename():
    injector = FaultInjector()
    schema = {"Invoice": {"columns": []}, "Customer": {"columns": []}}
    renamed = injector.inject_schema_rename(schema, "Invoice")
    assert "Invoice" not in renamed
    assert "Invoice_OLD" in renamed
    assert "Customer" in renamed
