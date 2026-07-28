"""Deliberate error injection for Layer 2 integration testing.
See docs/text_to_sql_agent_design_spec.md §11.
"""

import re

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine


class FaultInjector:
    def inject_syntax_error(self, sql: str) -> str:
        """Corrupts SQL to trigger a syntax error retry."""
        return sql.replace("SELECT", "SLECT", 1)

    def inject_unknown_column(self, sql: str, real_columns: list[str]) -> str:
        """Replaces the first real column name found in sql with a fake one."""
        for col in real_columns:
            if re.search(rf"\b{col}\b", sql):
                return re.sub(rf"\b{col}\b", "fake_column", sql, count=1)
        return sql

    def inject_empty_db_engine(self) -> Engine:
        """An in-memory SQLite engine with no tables -- simulates a DB with no data."""
        return create_engine("sqlite:///:memory:")

    def inject_schema_rename(self, schema: dict, table: str) -> dict:
        """Renames a table in a schema snapshot dict to simulate schema drift."""
        renamed = dict(schema)
        if table in renamed:
            renamed[f"{table}_OLD"] = renamed.pop(table)
        return renamed
