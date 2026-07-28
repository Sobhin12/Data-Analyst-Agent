"""Ensures the repo root is importable as the top-level package namespace."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
