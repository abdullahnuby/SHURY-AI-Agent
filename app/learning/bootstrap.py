from __future__ import annotations

import csv
import gzip
import json
import sqlite3
from pathlib import Path
from typing import Iterable

from app.runtime.registry import load_tools
from app.knowledge.seed_scenarios import DEFAULT_PATH as SEED_DB
from app.knowledge.seed_policy import SEED_SOURCE, SEED_VERSION, seed_prior_metadata, validate_seed_payload
from .brain_store import BrainKnowledgeStore, DEFAULT_PATH as LEARNING_DB


def _seed_records(path: str | Path, *, batch_size: int = 2000) -> Iterable[dict]:
    conn = sqlite3.connect(path)
    try:
        cursor = conn.execute(
            "SELECT goal,domain,capability,interaction_shape,required_tools,forbidden_tools,tool_order,constraints,failure_modes,success_invariants,support_level,approval_required FROM scenarios ORDER BY id"
        )
        while True:
            rows = cursor.fetchmany(batch_size)
            if not rows:
                break
            for row in rows:
                yield {
                    "goal": row[0], "domain": row[1], "capability": row[2], "interaction_shape": row[3],
                    "required_tools": json.loads(row[4] or "[]"), "forbidden_tools": json.loads(row[5] or "[]"),
                    "tool_order": json.loads(row[6] or "[]"), "constraints": json.loads(row[7] or "[]"),
                    "failure_modes": json.loads(row[8] or "[]"), "success_invariants": json.loads(row[9] or "[]"),
                    "support_level": row[10], "approval_required": bool(row[11]),
                    "source": SEED_SOURCE, "provenance": {"seed_version": SEED_VERSION, "generation_method": "seed_scenarios_sqlite"},
                    "not_user_memory": True, "not_execution_evidence": True,
                }
    finally:
        conn.close()


def _file_records(path: Path) -> Iterable[dict]:
    suffix = ''.join(path.suffixes).lower()
    if suffix.endswith('.jsonl.gz') or suffix.endswith('.ndjson.gz'):
        with gzip.open(path, 'rt', encoding='utf-8') as f:
            for line in f:
                line=line.strip()
                if line: yield json.loads(line)
        return
    if path.suffix.lower() in {'.jsonl', '.ndjson'}:
        with path.open('r', encoding='utf-8') as f:
            for line in f:
                line=line.strip()
                if line: yield json.loads(line)
        return
    if path.suffix.lower() == '.json':
        payload=json.loads(path.read_text(encoding='utf-8'))
        if isinstance(payload, dict): payload=[payload]
        for item in payload: yield item
        return
    if path.suffix.lower() == '.csv':
        with path.open('r', encoding='utf-8-sig', newline='') as f:
            yield from csv.DictReader(f)
        return
    raise ValueError('supported formats: .jsonl, .ndjson, .json, .csv, .jsonl.gz')


def bootstrap_seed(*, seed_path: str | Path = SEED_DB, brain_path: str | Path = LEARNING_DB) -> dict:
    registry = load_tools()
    store = BrainKnowledgeStore(brain_path)
    return store.ingest_records(_seed_records(seed_path), source=SEED_SOURCE, registry=registry)


def ingest_file(path: str | Path, *, brain_path: str | Path = LEARNING_DB,
                source: str | None = None, require_tool_compatibility: bool = True) -> dict:
    registry = load_tools() if require_tool_compatibility else {}
    file_path = Path(path)
    store = BrainKnowledgeStore(brain_path)
    return store.ingest_records(_file_records(file_path), source=source or file_path.name, registry=registry)


__all__ = ['bootstrap_seed', 'ingest_file']
