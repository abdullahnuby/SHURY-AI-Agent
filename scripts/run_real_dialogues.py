from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.evaluation.real_dialogue_runner import Phase12EnvironmentBlocked, RealDialogueRunner


def main() -> int:
    parser = argparse.ArgumentParser(description="Execute SHURY Phase 12 real-runtime dialogue corpus")
    parser.add_argument("--corpus", default="benchmarks/dialogues/dialogues_phase10_seed_20261002.jsonl")
    parser.add_argument("--output", default="benchmarks/real_runtime/phase12")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    try:
        summary = RealDialogueRunner(args.corpus, args.output).run(limit=args.limit)
    except Phase12EnvironmentBlocked as exc:
        print(json.dumps({"status": "BLOCKED_BY_ENVIRONMENT", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary.get("gate12_execution_complete") else 1


if __name__ == "__main__":
    raise SystemExit(main())
