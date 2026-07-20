"""Import helper for running bench tools from the project tree."""

from __future__ import annotations

import sys
from pathlib import Path


def add_project_src_to_path() -> None:
    project_root = Path(__file__).resolve().parents[1]
    pi_src = project_root / "pi" / "src"
    if str(pi_src) not in sys.path:
        sys.path.insert(0, str(pi_src))
