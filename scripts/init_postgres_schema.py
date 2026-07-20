"""Apply the Postgres schema to the database in DATABASE_URL.

Run once after provisioning the database. Idempotent and safe to re-run.

Usage:
    python -m scripts.init_postgres_schema
"""
from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

load_dotenv()
load_dotenv(REPO_ROOT / ".env.local")
load_dotenv(BACKEND_ROOT / ".env", override=True)

from src.agent_system.storage.postgres_backend import init_schema


def main() -> int:
    print("Applying Postgres schema...")
    init_schema()
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
