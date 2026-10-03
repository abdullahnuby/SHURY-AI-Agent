from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any


def load(path: str | Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def transcript(row: dict[str, Any]) -> str:
    return "\n".join(str(turn["text"]) for turn in row["turns"])


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Compare SHURY Round 1 and Round 2 dialogue sets")
    parser.add_argument("round1")
    parser.add_argument("round2")
    parser.add_argument("--output", default="reports/phase17/round_comparison.json")
    args = parser.parse_args()

    r1 = load(args.round1)
    r2 = load(args.round2)
    ids1, ids2 = {r["conversation_id"] for r in r1}, {r["conversation_id"] for r in r2}
    tx1, tx2 = {transcript(r) for r in r1}, {transcript(r) for r in r2}
    categories = lambda rows: Counter(r["category"] for r in rows)
    modes = lambda rows: Counter(r["language_metadata"]["mode"] for r in rows)
    dimensions = lambda rows: Counter(k for r in rows for k, v in r["generation_dimensions"].items() if v is True)
    result = {
        "round1": {"count": len(r1), "unique_ids": len(ids1), "unique_transcripts": len(tx1), "categories": categories(r1), "language_modes": modes(r1), "true_dimensions": dimensions(r1)},
        "round2": {"count": len(r2), "unique_ids": len(ids2), "unique_transcripts": len(tx2), "categories": categories(r2), "language_modes": modes(r2), "true_dimensions": dimensions(r2)},
        "overlap": {"conversation_ids": len(ids1 & ids2), "exact_transcripts": len(tx1 & tx2)},
        "new_seed": sorted({r["seed"] for r in r2}),
        "round1_seed": sorted({r["seed"] for r in r1}),
    }
    # JSON-friendly counters.
    result["round1"]["categories"] = dict(result["round1"]["categories"])
    result["round1"]["language_modes"] = dict(result["round1"]["language_modes"])
    result["round1"]["true_dimensions"] = dict(result["round1"]["true_dimensions"])
    result["round2"]["categories"] = dict(result["round2"]["categories"])
    result["round2"]["language_modes"] = dict(result["round2"]["language_modes"])
    result["round2"]["true_dimensions"] = dict(result["round2"]["true_dimensions"])
    result["comparable"] = bool(
        result["round1"]["count"] == result["round2"]["count"] == 1000
        and result["overlap"]["conversation_ids"] == 0
        and result["overlap"]["exact_transcripts"] == 0
        and result["round1_seed"] != result["new_seed"]
    )
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["comparable"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
