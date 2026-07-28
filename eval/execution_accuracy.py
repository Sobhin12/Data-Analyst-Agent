"""Primary eval metric: does the agent's SQL return the same rows as the gold SQL?
See docs/text_to_sql_agent_design_spec.md §11.
"""

from sqlalchemy import text
from sqlalchemy.engine import Engine


def execution_accuracy(agent_sql: str, gold_sql: str, engine: Engine) -> bool:
    """True if agent_sql returns the same result set as gold_sql.

    Does not require identical SQL -- only identical output.
    """
    with engine.connect() as conn:
        agent_result = {tuple(row) for row in conn.execute(text(agent_sql)).fetchall()}
        gold_result = {tuple(row) for row in conn.execute(text(gold_sql)).fetchall()}
    return agent_result == gold_result
