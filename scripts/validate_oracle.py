from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.evaluation.oracle import DeterministicEvaluationOracle


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate SHURY dialogue expectations with the deterministic oracle.")
    parser.add_argument("corpus", type=Path)
    args = parser.parse_args()
    dialogues = load_jsonl(args.corpus)
    result = DeterministicEvaluationOracle().validate_dialogues(dialogues)
    result["corpus"] = str(args.corpus)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
