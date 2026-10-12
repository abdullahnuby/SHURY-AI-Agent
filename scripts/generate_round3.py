#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.evaluation.round3_generalization_generator import (  # noqa: E402
    ROUND3_SEED,
    generate_round3_dialogues,
    validate_round3,
    write_round3,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate SHURY Phase 18 Round 3 generalization dialogues")
    parser.add_argument("--count", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=ROUND3_SEED)
    parser.add_argument("--round1", default="benchmarks/dialogues/dialogues_phase10_seed_20261002.jsonl")
    parser.add_argument("--round2", default="benchmarks/dialogues/round2/dialogues_round_02_seed_20261017.jsonl")
    parser.add_argument("--output-dir", default="benchmarks/dialogues/round3")
    args = parser.parse_args()

    dialogues = generate_round3_dialogues(args.count, args.seed)
    validation = validate_round3(dialogues, [args.round1, args.round2])
    if not validation["gate_ready"]:
        raise SystemExit(json.dumps(validation, ensure_ascii=False, indent=2))
    paths = write_round3(dialogues, args.output_dir)
    print(json.dumps({**validation, "jsonl": str(paths[0]), "manifest": str(paths[1])}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
