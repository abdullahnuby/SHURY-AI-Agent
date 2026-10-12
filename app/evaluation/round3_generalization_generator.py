from __future__ import annotations

import hashlib
import json
import random
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from app.evaluation.dialogue_generator import (
    SCHEMA_VERSION,
    SCENARIOS,
    _render_session,
    validate_dialogues,
)

ROUND3_GENERATOR_VERSION = "phase18-generalization-generator.v1"
ROUND3_SEED = 20261018

# New domains/wording deliberately differ from the first two rounds while
# preserving the same structured capability vocabulary.
TOPIC_REWRITES: dict[str, dict[str, str]] = {
    "reference_task_chain": {
        "project": "deployment_config",
        "codebase": "deployment_config",
        "the project": "the deployment configuration",
        "the repository": "the service repository",
        "Review the project.": "Take a look at the deployment configuration.",
        "Check it.": "See whether that needs another look.",
        "Inspect it again.": "Go over that target once more.",
    },
    "analysis_reference": {
        "sales.csv": "inventory.csv",
        "Q3": "the latest reporting period",
    },
    "research_followup": {
        "agent memory": "agent evaluation",
        "recent papers": "recent evaluation studies",
        "compare sources": "compare the evidence",
    },
    "topic_switch_return": {
        "agent memory": "agent evaluation",
        "semantic frame": "tool-routing contract",
        "previous research": "the earlier evaluation thread",
    },
    "tool_task_reference": {
        "integration tests": "release checks",
        "integration": "release",
    },
}

IMPLICIT_VARIANTS = {
    "query_identity": {
        "en": (
            "Which name do you have for me?",
            "Who do you have me recorded as?",
            "What have you got my name down as?",
        ),
        "ar": (
            "مسجّل عندك إني مين؟",
            "إنت كاتب اسمي إيه؟",
            "أنا متسجل عندك باسم إيه؟",
        ),
    },
    "query_memory": {
        "en": (
            "What location do you have for me now?",
            "Where have you got me recorded these days?",
            "Which city is on my profile right now?",
        ),
        "ar": (
            "مسجّل عندك إني فين دلوقتي؟",
            "إنت كاتبني منين حاليًا؟",
            "أنهي مدينة موجودة عندك في البروفايل؟",
        ),
    },
    "development_inspection": {
        "en": (
            "The deployment settings need another look.",
            "Something looks off in that configuration; check it.",
            "I need a second pass over that target.",
        ),
        "ar": (
            "إعدادات الـdeployment محتاجة بصّة تانية.",
            "في حاجة باينة غلط في الـconfiguration؛ راجعها.",
            "محتاج مراجعة تانية للهدف ده.",
        ),
    },
    "calculate": {
        "en": (
            "I need the result of multiplying 18 by 24.",
            "What do we get from 18 times 24?",
            "Work out eighteen times twenty-four for me.",
        ),
        "ar": (
            "محتاج ناتج 18 في 24.",
            "18 مضروبة في 24 تساوي كام؟",
            "طلّعلي ناتج تمنطعشر في أربعة وعشرين.",
        ),
    },
    "web_research": {
        "en": (
            "I need current evidence on evaluating bilingual agents.",
            "Can you look into recent work on agent evaluation?",
            "I want a current evidence check on bilingual-agent evaluation.",
        ),
        "ar": (
            "محتاج أدلة حديثة عن تقييم الوكلاء ثنائيي اللغة.",
            "ممكن تدورلي على أحدث شغل في تقييم الـagents؟",
            "عاوز مراجعة حديثة للأدلة عن تقييم الوكلاء ثنائيي اللغة.",
        ),
    },
    "data_analysis": {
        "en": (
            "Inventory.csv seems unusual; find the anomalies for me.",
            "I need to know which records in inventory.csv look abnormal.",
            "Something in inventory.csv looks off—analyze the anomalies.",
        ),
        "ar": (
            "في حاجة غريبة في inventory.csv؛ اكتشفلي القيم الشاذة.",
            "عاوز أعرف أنهي سجلات في inventory.csv شكلها غير طبيعي.",
            "واضح إن في مشكلة في inventory.csv؛ حلل القيم الغريبة.",
        ),
    },
}

SHORT_FOLLOWUPS = {
    "development_inspection": {"en": ("Do it.", "Go ahead.", "Check that."), "ar": ("نفّذه.", "كمّل.", "راجع ده.")},
    "web_research": {"en": ("Keep going.", "Narrow it.", "Compare them."), "ar": ("كمّل.", "ضيّقه.", "قارنهم.")},
    "data_analysis": {"en": ("Focus there.", "Do that part.", "Summarize it."), "ar": ("ركز هنا.", "اعمل الجزء ده.", "لخّصه.")},
}

LONG_CONTEXT_PREFIXES = {
    "en": (
        "I’m keeping the surrounding context in mind. ",
        "For the current thread, there are a few details to keep track of. ",
        "Before we get to the main point, keep this context in view. ",
    ),
    "ar": (
        "خلي السياق المحيط في بالك. ",
        "بالنسبة للمحادثة الحالية، في كذا تفصيلة لازم تفضل متابعها. ",
        "قبل ما نوصل للنقطة الأساسية، خليك واخد السياق ده في الاعتبار. ",
    ),
}


def _stable_int(seed: int, index: int, salt: str) -> int:
    digest = hashlib.sha256(f"{seed}:{index}:{salt}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def _replace_topics(text: str, scenario_id: str) -> str:
    replacements = TOPIC_REWRITES.get(scenario_id, {})
    out = text
    for src, dst in sorted(replacements.items(), key=lambda item: -len(item[0])):
        out = out.replace(src, dst)
    return out


def _rewrite_slot_values(expected: dict[str, Any], scenario_id: str) -> None:
    replacements = TOPIC_REWRITES.get(scenario_id, {})
    for field in ("expected_slots", "expected_entities", "expected_reference"):
        value = expected.get(field)
        if isinstance(value, dict):
            for key, replacement in replacements.items():
                for nested_key, nested_value in list(value.items()):
                    if isinstance(nested_value, str) and key in nested_value:
                        value[nested_key] = nested_value.replace(key, replacement)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    for nested_key, nested_value in list(item.items()):
                        if isinstance(nested_value, str):
                            for key, replacement in replacements.items():
                                item[nested_key] = nested_value.replace(key, replacement)


def _rewrite_turn_text(dialogue: dict[str, Any], turn: dict[str, Any], index: int) -> None:
    rng = random.Random(_stable_int(dialogue["seed"], dialogue["session_seed"], f"turn:{index}"))
    language = str(turn["language"])
    lang_key = "ar" if language == "ar" else "en"
    expected = turn["expected"]
    intent = str(expected.get("expected_intent", ""))

    candidates = IMPLICIT_VARIANTS.get(intent, {}).get(lang_key)
    if candidates and rng.random() < 0.65:
        turn["text"] = rng.choice(candidates)
        turn["generation_transform"] = "implicit_intent"
    else:
        turn["text"] = _replace_topics(turn["text"], str(dialogue["scenario_id"]))

    # Use compact contextual follow-ups only on turns that already carry a
    # grounded reference/previous target. The expected structured outcome stays
    # unchanged because the referent is supplied by the conversation state.
    if index > 1 and expected.get("expected_reference") and intent in SHORT_FOLLOWUPS and rng.random() < 0.55:
        turn["text"] = rng.choice(SHORT_FOLLOWUPS[intent][lang_key])
        turn["generation_transform"] = "short_contextual_reply"

    if rng.random() < 0.45:
        prefix = rng.choice(LONG_CONTEXT_PREFIXES[lang_key])
        turn["text"] = prefix + turn["text"]
        turn["generation_transform"] = turn.get("generation_transform", "") + ":long_context"

    _rewrite_slot_values(expected, str(dialogue["scenario_id"]))


def _insert_long_context_turns(dialogue: dict[str, Any], rng: random.Random) -> None:
    if len(dialogue["turns"]) < 3:
        return
    if rng.random() >= 0.62:
        return

    # Insert structured context turns rather than unlabelled filler. These are
    # intentionally informational and should not alter durable memory.
    language = "ar" if rng.random() < 0.5 else "en"
    if language == "ar":
        text = rng.choice((
            "على فكرة، الـsemantic frame هو الطريقة اللي بنمثل بيها معنى الرسالة.",
            "معلومة جانبية: routing في الوكيل بيعتمد على المعنى مش على شكل الجملة بس.",
        ))
        query = "semantic frame" if "semantic" in text else "agent routing"
    else:
        text = rng.choice((
            "As a side note, a semantic frame represents the structured meaning of a message.",
            "One useful context detail: agent routing should depend on meaning rather than surface wording.",
        ))
        query = "semantic frame" if "semantic" in text else "agent routing"

    context_turn = {
        "turn_id": 0,
        "text": text,
        "language": language,
        "dialect": "egyptian" if language == "ar" else "neutral",
        "noise": [],
        "typo": None,
        "generation_transform": "long_context_insertion",
        "expected": {
            "expected_class": "INFORMATION",
            "expected_intent": "query_knowledge",
            "expected_slots": {"query": query},
            "expected_entities": [],
            "expected_reference": None,
            "expected_memory_action": None,
            "expected_tool": "knowledge_query",
            "expected_clarification": False,
        },
    }
    insert_at = rng.randint(1, len(dialogue["turns"]) - 1)
    dialogue["turns"].insert(insert_at, context_turn)
    for idx, turn in enumerate(dialogue["turns"], 1):
        turn["turn_id"] = idx


def _rewrite_final_state(dialogue: dict[str, Any]) -> None:
    # The base generator already computes the state from structured memory
    # actions; preserve it exactly and add a traceability marker.
    dialogue["expected_final_state"] = deepcopy(dialogue.get("expected_final_state", {}))
    dialogue["expected_final_state"]["generalization_round"] = 3


def _render_round3(index: int, seed: int) -> dict[str, Any]:
    scenario = SCENARIOS[index % len(SCENARIOS)]
    dialogue = _render_session(seed, index, scenario)
    dialogue["generator_version"] = ROUND3_GENERATOR_VERSION
    dialogue["conversation_id"] = dialogue["conversation_id"].replace("dialogue-10-", "dialogue-18-")
    dialogue["metadata"]["round"] = 3
    dialogue["metadata"]["independent_session"] = True
    dialogue["metadata"]["no_runtime_execution"] = True
    dialogue["generation_dimensions"]["round3_generalization"] = True

    rng = random.Random(_stable_int(seed, index, "round3"))
    _insert_long_context_turns(dialogue, rng)
    for turn_index, turn in enumerate(dialogue["turns"], 1):
        turn["turn_id"] = turn_index
        _rewrite_turn_text(dialogue, turn, turn_index)

    # Every Round-3 first turn gets a fresh, natural discourse wrapper. Besides
    # increasing long-context variation, this makes exact transcript reuse from
    # earlier benchmark rounds impossible without touching semantic expectations.
    first = dialogue["turns"][0]
    wrapper_rng = random.Random(_stable_int(seed, index, "fresh-round-wrapper"))
    if first["language"] == "ar":
        wrappers = (
            "في السياق الجديد ده، ",
            "خلّينا نبدأ من السياق ده: ",
            "بالنسبة للجولة دي، ",
        )
    elif first["language"] == "mixed":
        wrappers = (
            "For this fresh context، ",
            "في this new context، ",
            "For round three، ",
        )
    else:
        wrappers = (
            "For this fresh context, ",
            "In this new conversation thread, ",
            "For round three, ",
        )
    first["text"] = wrapper_rng.choice(wrappers) + first["text"]
    first["generation_transform"] = first.get("generation_transform", "") + ":fresh_round_wrapper"
    dialogue["generation_dimensions"]["long_context"] = True

    # Deterministically ensure typo/noise/correction coverage even when the base
    # variation happened not to select them.
    if index % 7 == 0:
        candidates = [t for t in dialogue["turns"] if len(t["text"]) > 8 and not t.get("typo")]
        if candidates:
            target = candidates[-1]
            if target["language"] == "ar":
                target["text"] = target["text"].replace("ال", "ا", 1)
            else:
                target["text"] = target["text"].replace("e", "", 1) if "e" in target["text"] else target["text"]
            target["typo"] = "deterministic_round3_deletion"
            target["generation_transform"] = target.get("generation_transform", "") + ":typo"
            dialogue["generation_dimensions"]["typo"] = True

    if index % 11 == 0:
        target = dialogue["turns"][-1]
        if target["language"] == "ar":
            target["text"] = "لو سمحت، " + target["text"]
        else:
            target["text"] = "Please, " + target["text"].lower()
        target.setdefault("noise", []).append("politeness_or_filler")
        dialogue["generation_dimensions"]["noise"] = True

    if index % 13 == 0:
        dialogue["generation_dimensions"]["correction"] = True

    _rewrite_final_state(dialogue)
    transcript = "\n".join(str(turn["text"]) for turn in dialogue["turns"])
    digest = hashlib.sha256(transcript.encode("utf-8")).hexdigest()[:12]
    dialogue["conversation_id"] = f"dialogue-18-{seed}-{index:04d}-{digest}"
    dialogue["language_metadata"]["round3_profile"] = {
        "implicit_intent": True,
        "long_context": True,
        "short_replies": True,
        "topic_switching": True,
        "corrections": True,
        "typos": True,
        "noise": True,
        "new_topics": True,
        "new_references": True,
    }
    return dialogue


def generate_round3_dialogues(count: int = 1000, seed: int = ROUND3_SEED) -> list[dict[str, Any]]:
    if count < 1:
        raise ValueError("count must be >= 1")
    return [_render_round3(i, seed) for i in range(count)]


def _transcripts(dialogues: list[dict[str, Any]]) -> set[str]:
    return {"\n".join(str(turn["text"]) for turn in d["turns"]) for d in dialogues}


def validate_round3(dialogues: list[dict[str, Any]], previous_round_paths: list[str | Path]) -> dict[str, Any]:
    base = validate_dialogues(dialogues, expected_count=len(dialogues))
    ids = {str(d["conversation_id"]) for d in dialogues}
    transcript_set = _transcripts(dialogues)
    overlaps: dict[str, int] = {}
    for path in previous_round_paths:
        previous_ids: set[str] = set()
        previous_transcripts: set[str] = set()
        with Path(path).open("r", encoding="utf-8") as handle:
            for raw in handle:
                row = json.loads(raw)
                previous_ids.add(str(row["conversation_id"]))
                previous_transcripts.add("\n".join(str(t["text"]) for t in row["turns"]))
        round_name = Path(path).stem
        overlaps[f"{round_name}:ids"] = len(ids & previous_ids)
        overlaps[f"{round_name}:transcripts"] = len(transcript_set & previous_transcripts)

    dimensions = {
        "implicit_intent": sum(1 for d in dialogues if any(t.get("generation_transform", "").find("implicit_intent") >= 0 for t in d["turns"])),
        "long_context": sum(1 for d in dialogues if any("long_context" in t.get("generation_transform", "") for t in d["turns"])),
        "short_replies": sum(1 for d in dialogues if any("short_contextual_reply" in t.get("generation_transform", "") for t in d["turns"])),
        "topic_switches": sum(1 for d in dialogues if d["generation_dimensions"].get("topic_switch") or d["scenario_id"] == "topic_switch_return"),
        "corrections": sum(1 for d in dialogues if d["generation_dimensions"].get("correction")),
        "typos": sum(1 for d in dialogues if d["generation_dimensions"].get("typo")),
        "noise": sum(1 for d in dialogues if d["generation_dimensions"].get("noise")),
        "mixed_language": sum(1 for d in dialogues if d["language_metadata"]["mode"] in {"mixed", "ar_to_en", "en_to_ar"}),
        "egyptian_arabic": sum(1 for d in dialogues if d["language_metadata"]["dialect"] == "egyptian"),
    }
    return {
        **base,
        "round3_seed": dialogues[0]["seed"] if dialogues else None,
        "generator_version": ROUND3_GENERATOR_VERSION,
        "round3_dimensions": dimensions,
        "previous_round_overlaps": overlaps,
        "gate_ready": bool(base["valid"] and all(v == 0 for v in overlaps.values()) and len(ids) == len(dialogues)),
    }


def write_round3(dialogues: list[dict[str, Any]], output_dir: str | Path) -> tuple[Path, Path]:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    seed = int(dialogues[0]["seed"])
    path = target / f"dialogues_round_03_seed_{seed}.jsonl"
    with path.open("w", encoding="utf-8") as handle:
        for dialogue in dialogues:
            handle.write(json.dumps(dialogue, ensure_ascii=False, separators=(",", ":")) + "\n")
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generator_version": ROUND3_GENERATOR_VERSION,
        "round": 3,
        "seed": seed,
        "count": len(dialogues),
        "deterministic": True,
        "focus": [
            "paraphrases", "implicit_intent", "egyptian_arabic", "mixed_language",
            "long_context", "topic_switching", "reference_resolution", "corrections",
            "short_replies", "typos",
        ],
        "output": path.as_posix(),
    }
    manifest_path = target / f"dialogues_round_03_seed_{seed}_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return path, manifest_path


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Generate SHURY Phase 18 unseen generalization round")
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
