from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.evaluation.adversarial_generator import (
    PHASE19_SEED,
    generate_adversarial_dialogues,
    validate_adversarial_dialogues,
    write_adversarial,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=500)
    parser.add_argument("--seed", type=int, default=PHASE19_SEED)
    parser.add_argument("--output-dir", default="benchmarks/dialogues/phase19")
    args = parser.parse_args()
    root = ROOT
    previous = [
        root / "benchmarks/dialogues/dialogues_phase10_seed_20261002.jsonl",
        root / "benchmarks/dialogues/round2/dialogues_round_02_seed_20261017.jsonl",
        root / "benchmarks/dialogues/round3/dialogues_round_03_seed_20261018.jsonl",
    ]
    dialogues = generate_adversarial_dialogues(args.count, args.seed)
    validation = validate_adversarial_dialogues(dialogues, previous)
    if not validation["gate_ready"]:
        print(json.dumps(validation, ensure_ascii=False, indent=2))
        raise SystemExit(2)
    paths = write_adversarial(dialogues, root / args.output_dir)
    print(json.dumps({**validation, "jsonl": str(paths[0]), "manifest": str(paths[1])}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
