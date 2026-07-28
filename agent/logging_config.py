"""Central logging setup.

Call configure_logging() once per process entry point (main.py,
streamlit_app.py, eval/run_eval.py). Importing agent modules alone does not
attach handlers, so pytest runs stay quiet unless a test opts in.

Every module logs via logging.getLogger(__name__) and relies on propagation
to the root logger's handlers -- nothing in agent/ configures its own
handlers, so there's exactly one place (here) that decides format and
destination.
"""

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_FILE = LOG_DIR / "agent.log"

# These log at INFO by default and are almost pure noise for this project
# (one line per HTTP request to the model provider) -- keep them at WARNING
# regardless of our own configured level.
_NOISY_THIRD_PARTY_LOGGERS = ["httpx", "httpcore", "urllib3", "anthropic", "groq", "langsmith"]

_configured = False


def configure_logging(level: str | None = None) -> None:
    global _configured
    if _configured:
        return

    log_level = getattr(logging, (level or os.environ.get("LOG_LEVEL", "INFO")).upper(), logging.INFO)

    root = logging.getLogger()
    root.setLevel(log_level)

    fmt = logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    LOG_DIR.mkdir(exist_ok=True)
    file_handler = RotatingFileHandler(LOG_FILE, maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    for name in _NOISY_THIRD_PARTY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    _configured = True
