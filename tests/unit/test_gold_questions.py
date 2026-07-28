"""Verifies GOLD_QUESTIONS' gold_sql actually produces gold_answer right now.

Catches drift: if db/chinook.db is ever replaced/regenerated with different
data, this fails loudly instead of the eval suite silently grading against
stale numbers.
"""

import pytest

from db.loader import get_engine
from eval.gold_questions import GOLD_QUESTIONS
from sqlalchemy import text


def _run(sql: str) -> list[tuple]:
    with get_engine().connect() as conn:
        return [tuple(row) for row in conn.execute(text(sql)).fetchall()]


@pytest.mark.parametrize("gold", GOLD_QUESTIONS, ids=[g["question"] for g in GOLD_QUESTIONS])
def test_gold_sql_matches_gold_answer(gold):
    rows = _run(gold["gold_sql"])

    if gold["type"] == "trend":
        assert len(rows) >= gold["min_rows"]
        return

    if "gold_answer" not in gold:
        return

    if isinstance(gold["gold_answer"], list):
        assert rows == gold["gold_answer"]
        return

    # Scalar answer -- single row, single column.
    actual = rows[0][0]
    tolerance = gold.get("tolerance")
    if tolerance is not None:
        assert actual == pytest.approx(gold["gold_answer"], abs=tolerance)
    else:
        assert actual == gold["gold_answer"]
