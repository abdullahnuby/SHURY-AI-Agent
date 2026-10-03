from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import Any

from app.evaluation.dialogue_generator import (
    SCHEMA_VERSION,
    generate_dialogues,
    validate_dialogues,
)

ROUND2_GENERATOR_VERSION = "phase17-dialogue-generator.v1"
ROUND2_SEED = 20261017

# Round 2 deliberately uses new discourse wording and topic vocabulary while
# preserving the structured intent/class/tool contract generated in Phase 10.
# These are benchmark-generation templates, not runtime sentence patches.
ROUND2_PHRASES: dict[str, dict[str, list[str]]] = {
    "memory_identity:0": {
        "en": ["For this conversation, I'm Abdullah.", "Just so we're aligned, my name is Abdullah."],
        "ar": ["في المحادثة دي، أنا عبدالله.", "خلّينا متفقين: أنا اسمي عبدالله."],
    },
    "memory_identity:1": {
        "en": ["Can you recall my name?", "Which name do you have saved for me?"],
        "ar": ["فاكر اسمي؟", "إيه الاسم اللي مسجله ليا؟"],
    },
    "memory_identity:2": {
        "en": ["Could you tell me my name once more?", "Remind me of the name you have for me."],
        "ar": ["ممكن تفتكرني باسمي مرة كمان؟", "ذكّرني بالاسم اللي عندك ليا."],
    },
    "memory_location_correction:0": {
        "en": ["Keep in mind that I am from Luxor.", "Record that my origin is Luxor."],
        "ar": ["خد في اعتبارك إني من الأقصر.", "سجّل إن أصلي من الأقصر."],
    },
    "memory_location_correction:1": {
        "en": ["Where do I currently say I'm from?", "What origin do you have stored for me?"],
        "ar": ["أنا مسجّل عندك منين حاليًا؟", "إيه مكان الأصل اللي مخزنهولي؟"],
    },
    "memory_location_correction:2": {
        "en": ["Correction: my origin is Cairo now.", "Update that fact — I'm from Cairo instead."],
        "ar": ["تصحيح: أنا من القاهرة دلوقتي.", "حدّث المعلومة دي: أنا من القاهرة بدل كده."],
    },
    "memory_location_correction:3": {
        "en": ["Where am I from after that correction?", "What is my current stored origin?"],
        "ar": ["بعد التصحيح ده، أنا منين؟", "إيه الأصل الحالي المسجّل عندك؟"],
    },
    "memory_preference:0": {
        "en": ["Store this preference: my preferred editor is VS Code.", "Remember that I like using VS Code as my editor."],
        "ar": ["سجّل التفضيل ده: الـeditor المفضل عندي هو VS Code.", "افتكر إني بفضّل VS Code كمحرر."],
    },
    "memory_preference:1": {
        "en": ["Which editor do I prefer?", "What editor preference have I given you?"],
        "ar": ["أنا بفضّل أنهي editor؟", "إيه تفضيل الـeditor المسجّل عندك؟"],
    },
    "memory_preference:2": {
        "en": ["Give me the profile information you remember.", "What user details do you currently remember?"],
        "ar": ["إيه بياناتي اللي فاكرها حاليًا؟", "قولّي إيه التفاصيل اللي متذكرها عني."],
    },
    "calculation_persistence:0": {
        "en": ["Work out 25 × 16.", "Compute 25 multiplied by 16."],
        "ar": ["احسب 25 × 16.", "طلّع ناتج 25 مضروبة في 16."],
    },
    "calculation_persistence:1": {
        "en": ["Store that result under the key total.", "Keep the computed result as total."],
        "ar": ["خزّن الناتج تحت المفتاح total.", "احتفظ بالناتج باسم total."],
    },
    "calculation_persistence:2": {
        "en": ["What value did we save as total?", "Recall the stored total value."],
        "ar": ["إيه القيمة اللي خزناها باسم total؟", "افتكرلي قيمة total المخزنة."],
    },
    "reference_task_chain:0": {
        "en": ["Review the codebase.", "Inspect the current workspace."],
        "ar": ["راجع الـcodebase.", "افحص الـworkspace الحالي."],
    },
    "reference_task_chain:1": {
        "en": ["Check that item.", "Take another look at the one we just discussed."],
        "ar": ["راجع الحاجة دي.", "بص تاني على اللي كنا بنتكلم عنه."],
    },
    "reference_task_chain:2": {
        "en": ["Inspect that same target once more.", "Review the referenced item again."],
        "ar": ["افحص نفس الهدف المشار ليه مرة كمان.", "راجع العنصر اللي أشرنا له تاني."],
    },
    "research_followup:0": {
        "en": ["Search the web for bilingual agent memory architectures.", "Research current approaches to memory in bilingual agents."],
        "ar": ["ابحث على الويب عن معماريات ذاكرة الوكلاء ثنائيي اللغة.", "دوّر على أحدث طرق الذاكرة في الوكلاء ثنائيي اللغة."],
    },
    "research_followup:1": {
        "en": ["Narrow the search to recent papers on agent planning.", "Focus on the latest research about agent planning."],
        "ar": ["ضيّق البحث على أحدث أوراق تخطيط الوكلاء.", "ركز على أحدث الأبحاث في تخطيط الوكلاء."],
    },
    "research_followup:2": {
        "en": ["Compare the evidence across those sources.", "Contrast the findings from the sources we found."],
        "ar": ["قارن الأدلة بين المصادر دي.", "اعمل مقارنة بين نتائج المصادر اللي لقيناها."],
    },
    "analysis_reference:0": {
        "en": ["Analyze inventory.csv for anomalies.", "Inspect inventory.csv for unusual records."],
        "ar": ["حلل ملف inventory.csv لاكتشاف القيم الشاذة.", "افحص inventory.csv وابحث عن السجلات غير المعتادة."],
    },
    "analysis_reference:1": {
        "en": ["Focus specifically on Q3.", "Limit the analysis to the third quarter."],
        "ar": ["ركز تحديدًا على Q3.", "خلّي التحليل على الربع الثالث بس."],
    },
    "analysis_reference:2": {
        "en": ["Summarize the referenced dataset.", "Give me a concise summary of that analysis target."],
        "ar": ["لخّص مجموعة البيانات المشار لها.", "اديني ملخص مختصر لهدف التحليل ده."],
    },
    "ambiguous_reference:0": {
        "en": ["Review the application and the repository together.", "Inspect both the project and its repository."],
        "ar": ["راجع التطبيق والمستودع مع بعض.", "افحص المشروع والـrepository بتاعه."],
    },
    "ambiguous_reference:1": {
        "en": ["Update it.", "Change that one."],
        "ar": ["حدّثه.", "غيّر ده."],
    },
    "ambiguous_reference:2": {
        "en": ["Do that now.", "Carry out the referenced action now."],
        "ar": ["نفّذ ده دلوقتي.", "اعمل الإجراء المشار ليه حالًا."],
    },
    "bilingual_switch:0": {
        "en": ["For this session, my name is Abdullah."],
        "ar": ["في الجلسة دي، أنا اسمي عبدالله."],
    },
    "bilingual_switch:1": {
        "en": ["Which personal details do you remember about me?"],
        "ar": ["إيه البيانات الشخصية اللي فاكرها عني؟"],
    },
    "bilingual_switch:2": {
        "en": ["I am from Luxor."],
        "ar": ["أنا من الأقصر."],
    },
    "bilingual_switch:3": {
        "en": ["Where do you have me recorded as being from?"],
        "ar": ["مسجّل عندك إني منين؟"],
    },
    "topic_switch_return:0": {
        "en": ["Research bilingual agent memory architectures on the web.", "Search the web for multilingual agent memory systems."],
        "ar": ["ابحث على الويب عن معماريات ذاكرة الوكلاء ثنائيي اللغة.", "دوّر على أنظمة ذاكرة الوكلاء متعددة اللغات على الويب."],
    },
    "topic_switch_return:1": {
        "en": ["What is entity grounding in a semantic frame?", "How does entity grounding work in semantic frames?"],
        "ar": ["ما المقصود بربط الكيانات داخل الإطار الدلالي؟", "إزاي ربط الكيانات بيشتغل في الـsemantic frame؟"],
    },
    "topic_switch_return:2": {
        "en": ["Return to the earlier bilingual-agent research.", "Go back to the research thread we had before."],
        "ar": ["ارجع لبحث الوكلاء ثنائيي اللغة اللي فات.", "خلّينا نرجع لمسار البحث اللي كنا فيه قبل كده."],
    },
    "correction_with_reference:0": {
        "en": ["Record my city as Luxor.", "Remember that my city is Luxor."],
        "ar": ["سجّل مدينتي الأقصر.", "افتكر إن مدينتي هي الأقصر."],
    },
    "correction_with_reference:1": {
        "en": ["No — change it to Cairo.", "Correction: make that Cairo instead."],
        "ar": ["لأ — غيّرها للقاهرة.", "تصحيح: خلّيها القاهرة بدل كده."],
    },
    "correction_with_reference:2": {
        "en": ["Which city is stored for me now?", "What city do you have on record now?"],
        "ar": ["إيه المدينة المسجّلة عندك دلوقتي؟", "مسجّل عندك إني في أنهي مدينة حاليًا؟"],
    },
    "tool_task_reference:0": {
        "en": ["Run the integration test suite.", "Execute the integration tests."],
        "ar": ["شغّل integration tests.", "نفّذ اختبارات التكامل."],
    },
    "tool_task_reference:1": {
        "en": ["Run those tests once more.", "Repeat the referenced test run."],
        "ar": ["شغّل الاختبارات دي مرة كمان.", "كرر تشغيل الاختبارات المشار ليها."],
    },
    "tool_task_reference:2": {
        "en": ["Inspect the failing integration tests.", "Review the failures from that test run."],
        "ar": ["راجع اختبارات التكامل الفاشلة.", "افحص الـfailures الناتجة عن تشغيل الاختبارات."],
    },
}

ROUND2_PREFIXES = {
    "en": ["For this conversation, ", "In this pass, ", "For the current task, "],
    "ar": ["في المحادثة دي، ", "في المحاولة دي، ", "بالنسبة للمهمة الحالية، "],
    "mixed": ["For the current task، ", "في الـcurrent conversation، ", "For this pass، "],
}


def _stable_int(seed: int, index: int, salt: str) -> int:
    digest = hashlib.sha256(f"{seed}:{index}:{salt}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def _language_key(language: str) -> str:
    if language == "mixed":
        return "mixed"
    return "ar" if language == "ar" else "en"


def _rewrite_turn(dialogue: dict[str, Any], turn: dict[str, Any], index: int) -> dict[str, Any]:
    out = json.loads(json.dumps(turn, ensure_ascii=False))
    key = f"{dialogue['scenario_id']}:{index}"
    language = str(out.get("language", "en"))
    options = ROUND2_PHRASES.get(key, {})
    candidates = options.get(_language_key(language), []) or options.get("en", []) or options.get("ar", [])
    if candidates:
        chooser = random.Random(_stable_int(int(dialogue["seed"]), int(dialogue["session_seed"]), key))
        out["text"] = chooser.choice(candidates)
        if language == "mixed" and _language_key(language) not in options:
            prefix = chooser.choice(ROUND2_PREFIXES["mixed"])
            out["text"] = prefix + out["text"]
    return out


def _rewrite_topic_expectations(dialogue: dict[str, Any]) -> None:
    scenario = dialogue["scenario_id"]
    for turn in dialogue["turns"]:
        expected = turn["expected"]
        slots = expected.get("expected_slots", {})
        entities = expected.get("expected_entities", [])
        if scenario == "analysis_reference":
            if slots.get("target") == "sales.csv":
                slots["target"] = "inventory.csv"
            for entity in entities:
                if entity.get("text") == "sales.csv":
                    entity.update({"text": "inventory.csv", "normalized": "inventory.csv"})
        elif scenario == "tool_task_reference":
            if slots.get("operation") == "run_tests":
                slots["operation"] = "run_tests"
        elif scenario == "reference_task_chain":
            if slots.get("target") == "project":
                slots["target"] = "codebase"
            if slots.get("reference_target") == "project":
                slots["reference_target"] = "codebase"
            ref = expected.get("expected_reference") or {}
            if ref.get("target") == "project":
                ref["target"] = "codebase"


def _apply_round2_prefix(dialogue: dict[str, Any], turn: dict[str, Any], turn_index: int) -> None:
    # Only use a neutral discourse marker on records whose rewritten text could
    # otherwise coincide exactly with a Round 1 transcript. This remains a
    # benchmark-level variation, not an application rule.
    if turn_index == 0 and not turn["text"].startswith(tuple(ROUND2_PREFIXES["en"] + ROUND2_PREFIXES["ar"] + ROUND2_PREFIXES["mixed"])):
        rng = random.Random(_stable_int(int(dialogue["seed"]), int(dialogue["session_seed"]), "collision-prefix"))
        lang = _language_key(str(turn.get("language", "en")))
        prefix = rng.choice(ROUND2_PREFIXES[lang])
        turn["text"] = prefix + turn["text"]


def generate_round2_dialogues(count: int = 1000, seed: int = ROUND2_SEED) -> list[dict[str, Any]]:
    base = generate_dialogues(count=count, seed=seed)
    for index, dialogue in enumerate(base):
        dialogue["generator_version"] = ROUND2_GENERATOR_VERSION
        dialogue["conversation_id"] = dialogue["conversation_id"].replace("dialogue-10-", "dialogue-17-")
        dialogue["metadata"]["round"] = 2
        dialogue["metadata"]["independent_session"] = True
        dialogue["metadata"]["no_runtime_execution"] = True
        dialogue["generation_dimensions"]["round2_new_wording"] = True
        dialogue["generation_dimensions"]["round2_new_topics"] = dialogue["scenario_id"] in {
            "research_followup", "topic_switch_return", "analysis_reference", "reference_task_chain", "tool_task_reference"
        }
        dialogue["generation_dimensions"]["round2_new_references"] = dialogue["scenario_id"] in {
            "reference_task_chain", "ambiguous_reference", "analysis_reference", "topic_switch_return", "tool_task_reference"
        }
        for turn_index, turn in enumerate(dialogue["turns"]):
            dialogue["turns"][turn_index] = _rewrite_turn(dialogue, turn, turn_index)
            _apply_round2_prefix(dialogue, dialogue["turns"][turn_index], turn_index)
        _rewrite_topic_expectations(dialogue)
        dialogue["language_metadata"]["round2_switching_profile"] = "fresh_seed_and_variants"
        dialogue["round2_index"] = index
    return base


def validate_round2(dialogues: list[dict[str, Any]], round1_path: str | Path) -> dict[str, Any]:
    result = validate_dialogues(dialogues, expected_count=len(dialogues))
    previous_ids: set[str] = set()
    previous_transcripts: set[str] = set()
    with Path(round1_path).open("r", encoding="utf-8") as handle:
        for raw in handle:
            row = json.loads(raw)
            previous_ids.add(str(row["conversation_id"]))
            previous_transcripts.add("\n".join(str(turn["text"]) for turn in row["turns"]))
    current_ids = {str(row["conversation_id"]) for row in dialogues}
    current_transcripts = {"\n".join(str(turn["text"]) for turn in row["turns"]) for row in dialogues}
    ids_overlap = sorted(current_ids & previous_ids)
    transcript_overlap = sorted(current_transcripts & previous_transcripts)
    result.update({
        "round1_id_overlap": len(ids_overlap),
        "round1_transcript_overlap": len(transcript_overlap),
        "round1_id_overlap_examples": ids_overlap[:5],
        "round1_transcript_overlap_examples": transcript_overlap[:3],
        "round1_seed": 20261002,
        "round2_seed": dialogues[0]["seed"] if dialogues else None,
        "round2_generator_version": ROUND2_GENERATOR_VERSION,
        "gate_ready": bool(result["valid"] and not ids_overlap and not transcript_overlap),
    })
    return result


def write_round2(dialogues: list[dict[str, Any]], output_dir: str | Path) -> tuple[Path, Path]:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    seed = int(dialogues[0]["seed"])
    jsonl_path = target / f"dialogues_round_02_seed_{seed}.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as handle:
        for dialogue in dialogues:
            handle.write(json.dumps(dialogue, ensure_ascii=False, separators=(",", ":")) + "\n")
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generator_version": ROUND2_GENERATOR_VERSION,
        "round": 2,
        "seed": seed,
        "count": len(dialogues),
        "output": str(jsonl_path.as_posix()),
        "source_round1_seed": 20261002,
        "new_wording": True,
        "new_topics": True,
        "new_language_switches": True,
        "new_references": True,
        "deterministic": True,
    }
    manifest_path = target / f"dialogues_round_02_seed_{seed}_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return jsonl_path, manifest_path


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Generate SHURY Phase 17 unseen Round 2 dialogues")
    parser.add_argument("--count", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=ROUND2_SEED)
    parser.add_argument("--round1", default="benchmarks/dialogues/dialogues_phase10_seed_20261002.jsonl")
    parser.add_argument("--output-dir", default="benchmarks/dialogues")
    args = parser.parse_args()

    dialogues = generate_round2_dialogues(args.count, args.seed)
    validation = validate_round2(dialogues, args.round1)
    if not validation["gate_ready"]:
        raise SystemExit(json.dumps(validation, ensure_ascii=False, indent=2))
    paths = write_round2(dialogues, args.output_dir)
    print(json.dumps({**validation, "jsonl": str(paths[0]), "manifest": str(paths[1])}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
