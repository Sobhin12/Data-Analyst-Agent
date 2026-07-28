"""SQLite engine factory for the text-to-SQL agent."""

from pathlib import Path

from sqlalchemy import Engine, create_engine

DB_DIR = Path(__file__).parent
DEFAULT_DB_PATH = DB_DIR / "chinook.db"

_engine: Engine | None = None


def get_engine(db_path: Path | str = DEFAULT_DB_PATH) -> Engine:
    """Returns a shared, read-only SQLAlchemy engine for the given SQLite file.

    Opened via SQLite's URI mode=ro so the connection itself refuses writes at
    the driver level -- a backstop in case the app-layer SELECT-only check in
    execute_sql (agent/tools/db_tools.py) is ever bypassed.
    """
    global _engine
    if _engine is None:
        abs_path = Path(db_path).resolve()
        _engine = create_engine(f"sqlite:///file:{abs_path}?mode=ro&uri=true")
    return _engine
