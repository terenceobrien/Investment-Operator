"""
Repo-root import shim for the backend src package.

The backend package root is `backend/`, where `backend/src` is imported as
`src`. This shim lets developer commands such as
`python -m src.agent_system...` also work from the repository root.
"""
from __future__ import annotations

from pathlib import Path

_BACKEND_SRC = Path(__file__).resolve().parents[1] / "backend" / "src"
if _BACKEND_SRC.exists():
    __path__.append(str(_BACKEND_SRC))
