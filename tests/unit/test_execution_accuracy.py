from db.loader import get_engine
from eval.execution_accuracy import execution_accuracy


def test_identical_queries_are_accurate():
    engine = get_engine()
    assert execution_accuracy(
        "SELECT SUM(Total) FROM Invoice", "SELECT SUM(Total) FROM Invoice", engine
    )


def test_differently_worded_but_equivalent_queries_are_accurate():
    engine = get_engine()
    assert execution_accuracy(
        "SELECT COUNT(*) FROM Genre",
        "SELECT COUNT(GenreId) FROM Genre",
        engine,
    )


def test_wrong_query_is_not_accurate():
    engine = get_engine()
    assert not execution_accuracy(
        "SELECT COUNT(*) FROM Employee", "SELECT COUNT(*) FROM Genre", engine
    )


def test_row_order_does_not_matter():
    engine = get_engine()
    assert execution_accuracy(
        "SELECT Name FROM Genre ORDER BY Name ASC",
        "SELECT Name FROM Genre ORDER BY Name DESC",
        engine,
    )
