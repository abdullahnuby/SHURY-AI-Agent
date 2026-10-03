#!/usr/bin/env python3
"""Explicit Phase-14 legacy-memory migration entry point.

Examples:
    python scripts/migrate_legacy_memory.py --db app/data/memory.db
    python scripts/migrate_legacy_memory.py --db app/data/memory.db --dry-run
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.knowledge.memory import Memory  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate legacy SHURY facts/notes into scoped canonical memory safely.")
    parser.add_argument("--db", default="app/data/memory.db", help="SQLite memory database path")
    parser.add_argument("--backup", default=None, help="Backup SQLite path; default is a timestamped sibling")
    parser.add_argument("--dry-run", action="store_true", help="Classify only; do not modify legacy or canonical memory rows")
    args = parser.parse_args()

    memory = Memory(args.db)
    report = memory.migrate_legacy_memory(backup_path=args.backup, dry_run=args.dry_run)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
