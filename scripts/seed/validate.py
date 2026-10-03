from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def validate(root: Path = ROOT) -> dict:
    seed_dir = root / "data" / "seed"
    db = seed_dir / "agent_scenarios_100k.db"
    gz = seed_dir / "agent_scenarios_100k.jsonl.gz"
    manifest_path = seed_dir / "SEED_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    conn = sqlite3.connect(db)
    try:
        count = int(conn.execute("SELECT COUNT(*) FROM scenarios").fetchone()[0])
        unique_ids = int(conn.execute("SELECT COUNT(DISTINCT id) FROM scenarios").fetchone()[0])
        fts_exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='scenarios_fts'").fetchone() is not None
    finally:
        conn.close()
    with gzip.open(gz, "rt", encoding="utf-8") as f:
        jsonl_count = sum(1 for _ in f)
    result = {
        "count": count,
        "unique_ids": unique_ids,
        "jsonl_count": jsonl_count,
        "fts": fts_exists,
        "manifest_count": manifest.get("count"),
        "sha256_db": sha256(db),
        "sha256_jsonl_gz": sha256(gz),
        "ok": (
            count == 100_000
            and unique_ids == 100_000
            and jsonl_count == 100_000
            and manifest.get("count") == 100_000
            and fts_exists
        ),
    }
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    print(json.dumps(validate(args.root), ensure_ascii=False, indent=2))
