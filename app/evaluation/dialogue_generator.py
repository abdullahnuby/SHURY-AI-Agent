from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

GENERATOR_VERSION = "phase10-dialogue-generator.v1"
SCHEMA_VERSION = "shury.dialogue.v1"
DEFAULT_COUNT = 1000
DEFAULT_SEED = 20261002

LANGUAGES = ("en", "ar", "mixed")
DIALECTS = ("neutral", "egyptian", "msa")


@dataclass(frozen=True)
class TurnBlueprint:
    intent: str
    conversation_class: str
    tool: str | None
    text_en: str
    text_ar: tuple[str, ...]
    slots: dict[str, str]
    entities: tuple[dict[str, str], ...] = ()
    reference: dict[str, Any] | None = None
    memory_action: dict[str, Any] | None = None
    clarification: bool = False


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    family: str
    turns: tuple[TurnBlueprint, ...]


@dataclass(frozen=True)
class Variation:
    language_mode: str
    dialect: str
    typo_rate: float
    noise: bool
    correction: bool
    topic_switch: bool
    reference_mode: str


EN = {
    "name": "Abdullah",
    "city": "Luxor",
    "city2": "Cairo",
    "editor": "VS Code",
    "file": "sales.csv",
    "project": "the project",
    "repo": "the repository",
}

AR = {
    "name": "عبدالله",
    "city": "الأقصر",
    "city2": "القاهرة",
    "editor": "VS Code",
    "file": "sales.csv",
    "project": "المشروع",
    "repo": "المستودع",
}


def _scenario_catalog() -> tuple[Scenario, ...]:
    return (
        Scenario(
            "memory_identity",
            "memory",
            (
                TurnBlueprint(
                    "remember_fact", "MEMORY_WRITE", "remember_fact",
                    "My name is Abdullah.", ("اسمي عبدالله.", "أنا اسمي عبدالله."),
                    {"fact:name": "Abdullah", "key": "name", "value": "Abdullah"},
                    memory_action={"action": "write", "key": "name", "value": "Abdullah"},
                ),
                TurnBlueprint(
                    "query_identity", "MEMORY_READ", "recall_fact",
                    "What is my name?", ("ما اسمي؟", "إيه اسمي؟"),
                    {"recall:key": "name", "key": "name"},
                ),
                TurnBlueprint(
                    "query_identity", "MEMORY_READ", "recall_fact",
                    "Tell me my name again.", ("قولّي اسمي تاني.", "ذكّرني باسمي."),
                    {"recall:key": "name", "key": "name"},
                ),
            ),
        ),
        Scenario(
            "memory_location_correction",
            "memory",
            (
                TurnBlueprint(
                    "remember_fact", "MEMORY_WRITE", "remember_fact",
                    "I am from Luxor.", ("أنا من الأقصر.", "أنا من الأقصر."),
                    {"fact:origin": "Luxor", "key": "origin", "value": "Luxor"},
                    memory_action={"action": "write", "key": "origin", "value": "Luxor"},
                ),
                TurnBlueprint(
                    "query_memory", "MEMORY_READ", "recall_fact",
                    "Where am I from?", ("من أين أنا؟", "أنا منين؟"),
                    {"recall:key": "origin", "key": "origin"},
                ),
                TurnBlueprint(
                    "correction", "CLARIFICATION", "remember_fact",
                    "Actually, I am from Cairo.", ("تصحيح: أنا من القاهرة.", "لا، أنا من القاهرة."),
                    {"fact:origin": "Cairo", "key": "origin", "value": "Cairo"},
                    memory_action={"action": "update", "key": "origin", "value": "Cairo"},
                ),
                TurnBlueprint(
                    "query_memory", "MEMORY_READ", "recall_fact",
                    "Where am I from now?", ("من أين أنا الآن؟", "أنا منين دلوقتي؟"),
                    {"recall:key": "origin", "key": "origin"},
                ),
            ),
        ),
        Scenario(
            "memory_preference",
            "memory",
            (
                TurnBlueprint(
                    "remember_fact", "MEMORY_WRITE", "remember_fact",
                    "Remember that my favorite editor is VS Code.",
                    ("تذكر أن محرري المفضل هو VS Code.", "افتكر إن الـeditor المفضل عندي هو VS Code."),
                    {"fact:editor": "VS Code", "key": "editor", "value": "VS Code"},
                    memory_action={"action": "write", "key": "editor", "value": "VS Code"},
                ),
                TurnBlueprint(
                    "query_memory", "MEMORY_READ", "recall_fact",
                    "What editor do I prefer?", ("ما محرر النصوص الذي أفضله؟", "أنا بفضل أي editor؟"),
                    {"recall:key": "editor", "key": "editor"},
                ),
                TurnBlueprint(
                    "memory_profile", "MEMORY_READ", "memory_profile",
                    "What do you remember about me?", ("ماذا تتذكر عني؟", "فاكر عني إيه؟"),
                    {"key": "profile"},
                ),
            ),
        ),
        Scenario(
            "calculation_persistence",
            "task",
            (
                TurnBlueprint(
                    "calculate", "EXECUTION", "calculator",
                    "Calculate 25*16.", ("احسب 25*16.", "احسب 25 في 16."),
                    {"operation:expression": "25*16", "expression": "25*16"},
                ),
                TurnBlueprint(
                    "remember_result", "MEMORY_WRITE", "remember_result",
                    "Save the result as total.", ("احفظ النتيجة باسم total.", "سجّل الناتج باسم total."),
                    {"result:key": "total", "key": "total"},
                    memory_action={"action": "write_result", "key": "total"},
                ),
                TurnBlueprint(
                    "recall_fact", "MEMORY_READ", "recall_fact",
                    "What is total?", ("ما قيمة total؟", "total كام؟"),
                    {"recall:key": "total", "key": "total"},
                ),
            ),
        ),
        Scenario(
            "reference_task_chain",
            "reference",
            (
                TurnBlueprint(
                    "development_inspection", "EXECUTION", "inspect_project",
                    "Review the project.", ("راجع المشروع.", "بص على المشروع."),
                    {"target": "project", "operation": "development_inspection"},
                ),
                TurnBlueprint(
                    "development_inspection", "EXECUTION", "inspect_project",
                    "Check it.", ("راجعه.", "بص عليه."),
                    {"target": "project", "reference_target": "project"},
                    reference={"kind": "pronoun", "surface": "it/ـه", "target": "project"},
                ),
                TurnBlueprint(
                    "development_inspection", "EXECUTION", "inspect_project",
                    "Inspect it again.", ("افحصه تاني.", "راجعه مرة كمان."),
                    {"target": "project", "reference_target": "project"},
                    reference={"kind": "pronoun", "surface": "it/ـه", "target": "project"},
                ),
            ),
        ),
        Scenario(
            "research_followup",
            "research",
            (
                TurnBlueprint(
                    "web_research", "RESEARCH", "web_research",
                    "Search the web for agent memory.", ("ابحث في الويب عن ذاكرة الوكلاء.", "دوّر على الويب عن agent memory."),
                    {"query": "agent memory"},
                ),
                TurnBlueprint(
                    "scientific_research", "RESEARCH", "arxiv_research",
                    "Focus on recent papers.", ("ركز على الأوراق البحثية الحديثة.", "ركز على أحدث الأبحاث."),
                    {"query": "recent papers"},
                ),
                TurnBlueprint(
                    "rag_reasoning", "RESEARCH", "rag_query",
                    "Compare the sources.", ("قارن المصادر.", "قارن بين المصادر."),
                    {"query": "compare sources"},
                    reference={"kind": "context", "surface": "the sources", "target": "research_sources"},
                ),
            ),
        ),
        Scenario(
            "analysis_reference",
            "analysis",
            (
                TurnBlueprint(
                    "data_analysis", "ANALYSIS", "analyze_dataset",
                    "Analyze sales.csv for anomalies.", ("حلل ملف sales.csv لاكتشاف القيم الشاذة.", "حلل sales.csv وشوف القيم الغريبة."),
                    {"target": "sales.csv", "analysis": "anomalies"},
                    entities=({"text": "sales.csv", "type": "file", "normalized": "sales.csv"},),
                ),
                TurnBlueprint(
                    "data_analysis", "ANALYSIS", "analyze_dataset",
                    "Focus on Q3.", ("ركز على الربع الثالث.", "ركز على Q3."),
                    {"target": "sales.csv", "period": "Q3"},
                    reference={"kind": "context", "surface": "Q3", "target": "Q3"},
                ),
                TurnBlueprint(
                    "data_analysis", "ANALYSIS", "analyze_dataset",
                    "Summarize it.", ("لخصه.", "لخص النتائج دي."),
                    {"target": "sales.csv", "reference_target": "sales.csv"},
                    reference={"kind": "pronoun", "surface": "it/ـه", "target": "sales.csv"},
                ),
            ),
        ),
        Scenario(
            "ambiguous_reference",
            "clarification",
            (
                TurnBlueprint(
                    "development_inspection", "EXECUTION", "inspect_project",
                    "Review the project and the repository.", ("راجع المشروع والمستودع.", "بص على المشروع والـrepo."),
                    {"targets": "project,repository"},
                ),
                TurnBlueprint(
                    "clarify", "CLARIFICATION", None,
                    "Update it.", ("حدثه.", "عدّله."),
                    {"clarification": "reference_target"},
                    reference={"kind": "pronoun", "surface": "it/ـه", "target": "ambiguous"},
                    clarification=True,
                ),
                TurnBlueprint(
                    "clarify", "CLARIFICATION", None,
                    "Do that now.", ("نفذ ده دلوقتي.", "اعمل ده حالًا."),
                    {"clarification": "action_target"},
                    reference={"kind": "deictic", "surface": "that/ده", "target": "ambiguous"},
                    clarification=True,
                ),
            ),
        ),
        Scenario(
            "bilingual_switch",
            "bilingual",
            (
                TurnBlueprint(
                    "remember_fact", "MEMORY_WRITE", "remember_fact",
                    "My name is Abdullah.", ("اسمي عبدالله.", "أنا اسمي عبدالله."),
                    {"fact:name": "Abdullah", "key": "name", "value": "Abdullah"},
                    memory_action={"action": "write", "key": "name", "value": "Abdullah"},
                ),
                TurnBlueprint(
                    "query_identity", "MEMORY_READ", "recall_fact",
                    "What do you remember about me?", ("ماذا تتذكر عني؟", "فاكر عني إيه؟"),
                    {"key": "profile"},
                ),
                TurnBlueprint(
                    "remember_fact", "MEMORY_WRITE", "remember_fact",
                    "أنا من الأقصر.", ("I am from Luxor.", "أنا من الأقصر."),
                    {"fact:origin": "Luxor", "key": "origin", "value": "Luxor"},
                    memory_action={"action": "write", "key": "origin", "value": "Luxor"},
                ),
                TurnBlueprint(
                    "query_memory", "MEMORY_READ", "recall_fact",
                    "Where am I from?", ("من أين أنا؟", "أنا منين؟"),
                    {"recall:key": "origin", "key": "origin"},
                ),
            ),
        ),
        Scenario(
            "topic_switch_return",
            "topic_switch",
            (
                TurnBlueprint(
                    "web_research", "RESEARCH", "web_research",
                    "Search the web for agent memory.", ("ابحث في الويب عن ذاكرة الوكلاء.", "دوّر على الويب عن agent memory."),
                    {"query": "agent memory"},
                ),
                TurnBlueprint(
                    "query_knowledge", "INFORMATION", "knowledge_query",
                    "What is a semantic frame?", ("ما هو الإطار الدلالي؟", "يعني إيه semantic frame؟"),
                    {"query": "semantic frame"},
                ),
                TurnBlueprint(
                    "rag_reasoning", "RESEARCH", "rag_query",
                    "Return to the previous research.", ("ارجع للبحث السابق.", "خلينا نرجع للبحث اللي فات."),
                    {"query": "agent memory"},
                    reference={"kind": "context", "surface": "previous research", "target": "agent_memory_research"},
                ),
            ),
        ),
        Scenario(
            "correction_with_reference",
            "correction",
            (
                TurnBlueprint(
                    "remember_fact", "MEMORY_WRITE", "remember_fact",
                    "My city is Luxor.", ("مدينتي الأقصر.", "أنا في الأقصر."),
                    {"fact:city": "Luxor", "key": "city", "value": "Luxor"},
                    memory_action={"action": "write", "key": "city", "value": "Luxor"},
                ),
                TurnBlueprint(
                    "correction", "CLARIFICATION", "remember_fact",
                    "No, make it Cairo.", ("لا، خليها القاهرة.", "لأ، صححها للقاهرة."),
                    {"correction:key": "city", "correction:value": "Cairo", "key": "city", "value": "Cairo"},
                    reference={"kind": "deictic", "surface": "it/ها", "target": "city"},
                    memory_action={"action": "update", "key": "city", "value": "Cairo"},
                ),
                TurnBlueprint(
                    "query_memory", "MEMORY_READ", "recall_fact",
                    "What city am I in now?", ("ما المدينة التي أعيش فيها الآن؟", "أنا في مدينة إيه دلوقتي؟"),
                    {"recall:key": "city", "key": "city"},
                ),
            ),
        ),
        Scenario(
            "tool_task_reference",
            "tool_task",
            (
                TurnBlueprint(
                    "development_validation", "EXECUTION", "run_tests",
                    "Run the test suite.", ("شغّل مجموعة الاختبارات.", "شغّل الـtest suite."),
                    {"operation": "run_tests"},
                ),
                TurnBlueprint(
                    "development_validation", "EXECUTION", "run_tests",
                    "Run it again.", ("شغّله تاني.", "شغله مرة كمان."),
                    {"operation": "run_tests", "reference_target": "test_suite"},
                    reference={"kind": "pronoun", "surface": "it/ـه", "target": "test_suite"},
                ),
                TurnBlueprint(
                    "development_validation", "EXECUTION", "run_tests",
                    "Check the failures.", ("راجع الاختبارات الفاشلة.", "راجع الـfailures."),
                    {"operation": "inspect_test_failures"},
                ),
            ),
        ),
    )


SCENARIOS = _scenario_catalog()


def _stable_seed(root_seed: int, index: int) -> int:
    digest = hashlib.sha256(f"{root_seed}:{index}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def _contains_arabic(text: str) -> bool:
    return any("\u0600" <= ch <= "\u06ff" for ch in text)


def _infer_language(text: str) -> str:
    has_ar = _contains_arabic(text)
    has_latin = any(ch.isascii() and ch.isalpha() for ch in text)
    if has_ar and has_latin:
        return "mixed"
    return "ar" if has_ar else "en"


def _dialect_variant(arabic_options: tuple[str, ...], dialect: str, rng: random.Random) -> str:
    if len(arabic_options) == 1:
        return arabic_options[0]
    return arabic_options[1] if dialect == "egyptian" and len(arabic_options) > 1 else arabic_options[0]


def _apply_generic_noise(text: str, rng: random.Random, language: str) -> tuple[str, list[str]]:
    applied: list[str] = []
    noise = rng.choice(("please", "kindly", "", "quickly")) if language == "en" else rng.choice(("لو سمحت", "من فضلك", "", "بس"))
    if noise:
        if language == "en":
            text = f"{noise}, {text[0].lower() + text[1:]}"
        else:
            text = f"{noise}، {text}"
        applied.append("politeness_or_filler")
    if rng.random() < 0.35:
        text += rng.choice(("!", ".", "؟" if language == "ar" else "?"))
        applied.append("punctuation_noise")
    return text, applied


def _apply_typo(text: str, rng: random.Random, language: str) -> tuple[str, str | None]:
    if len(re.findall(r"[A-Za-z\u0600-\u06ff]", text)) < 5:
        return text, None
    candidates = [i for i, ch in enumerate(text) if ch.isalpha()]
    if not candidates:
        return text, None
    idx = rng.choice(candidates)
    mode = rng.choice(("delete", "swap"))
    chars = list(text)
    if mode == "delete":
        original = chars[idx]
        del chars[idx]
        return "".join(chars), f"delete:{original}@{idx}"
    if idx + 1 < len(chars) and chars[idx + 1].isalpha():
        chars[idx], chars[idx + 1] = chars[idx + 1], chars[idx]
        return "".join(chars), f"swap:{idx}:{idx+1}"
    return text, None


def _translate_structured(text_en: str, text_ar: tuple[str, ...], language: str, dialect: str, rng: random.Random) -> tuple[str, str]:
    if language == "en":
        return text_en, "en"
    if language == "ar":
        return _dialect_variant(text_ar, dialect, rng), "ar"
    # mixed: use one language for the outer frame while retaining technical English
    ar_text = _dialect_variant(text_ar, dialect, rng)
    if any(token in text_en.lower() for token in ("editor", "semantic", "agent", "test suite", "failures", "code", "repository")):
        return ar_text, "mixed"
    if rng.random() < 0.5:
        return f"{ar_text} {rng.choice(('please', 'now', 'again'))}", "mixed"
    return f"{text_en} {rng.choice(('دلوقتي', 'لو سمحت', 'تاني'))}", "mixed"


def _choose_variation(rng: random.Random) -> Variation:
    language_mode = rng.choices(
        ["en", "ar", "mixed", "ar_to_en", "en_to_ar"],
        weights=[0.20, 0.20, 0.25, 0.175, 0.175],
        k=1,
    )[0]
    dialect = rng.choice(DIALECTS)
    return Variation(
        language_mode=language_mode,
        dialect=dialect,
        typo_rate=rng.choice((0.0, 0.0, 0.08, 0.12)),
        noise=rng.random() < 0.35,
        correction=rng.random() < 0.25,
        topic_switch=rng.random() < 0.25,
        reference_mode=rng.choice(("explicit", "natural", "mixed")),
    )


def _turn_languages(mode: str, count: int, rng: random.Random) -> list[str]:
    if mode == "en":
        return ["en"] * count
    if mode == "ar":
        return ["ar"] * count
    if mode == "mixed":
        langs = ["ar" if i % 2 else "en" for i in range(count)]
        if count > 2:
            rng.shuffle(langs)
        return ["mixed" if i == rng.randrange(count) else x for i, x in enumerate(langs)]
    pivot = max(1, count // 2)
    if mode == "ar_to_en":
        return ["ar"] * pivot + ["en"] * (count - pivot)
    return ["en"] * pivot + ["ar"] * (count - pivot)


def _translate_reference(reference: dict[str, Any] | None, language: str) -> dict[str, Any] | None:
    if reference is None:
        return None
    ref = dict(reference)
    if language == "ar" and ref.get("surface") == "it/ـه":
        ref["surface"] = "هو/ـه"
    elif language == "ar" and ref.get("surface") == "it/ها":
        ref["surface"] = "ها"
    return ref


def _expected(turn: TurnBlueprint, text: str, actual_language: str) -> dict[str, Any]:
    return {
        "expected_class": turn.conversation_class,
        "expected_intent": turn.intent,
        "expected_slots": dict(turn.slots),
        "expected_entities": [dict(e) for e in turn.entities],
        "expected_reference": _translate_reference(turn.reference, actual_language),
        "expected_memory_action": dict(turn.memory_action) if turn.memory_action else None,
        "expected_tool": turn.tool,
        "expected_clarification": bool(turn.clarification),
    }


def _apply_topic_switch(turns: list[TurnBlueprint], rng: random.Random) -> list[TurnBlueprint]:
    if len(turns) < 4:
        return turns
    insert_at = rng.randint(1, len(turns) - 2)
    info = TurnBlueprint(
        "query_knowledge", "INFORMATION", "knowledge_query",
        "What is a semantic frame?", ("ما هو الإطار الدلالي؟", "يعني إيه semantic frame؟"),
        {"query": "semantic frame"},
    )
    return turns[:insert_at] + [info] + turns[insert_at:]


def _apply_reference_variation(turn: TurnBlueprint, previous: TurnBlueprint | None, rng: random.Random, language: str) -> TurnBlueprint:
    if previous is None or turn.reference is None:
        return turn
    ref = dict(turn.reference)
    if ref.get("target") in {"project", "repository", "test_suite", "sales.csv"}:
        if language == "en" and rng.random() < 0.45:
            replacement = {
                "project": "the project",
                "repository": "the repository",
                "test_suite": "the tests",
                "sales.csv": "that file",
            }.get(ref["target"], ref["target"])
            text_en = re.sub(r"\bit\b|\bthem\b", replacement, turn.text_en, flags=re.I)
            return TurnBlueprint(**{**turn.__dict__, "text_en": text_en})
    return turn


def _render_session(root_seed: int, index: int, scenario: Scenario) -> dict[str, Any]:
    rng = random.Random(_stable_seed(root_seed, index))
    variation = _choose_variation(rng)
    blueprint_turns = list(scenario.turns)
    if variation.topic_switch:
        blueprint_turns = _apply_topic_switch(blueprint_turns, rng)

    languages = _turn_languages(variation.language_mode, len(blueprint_turns), rng)
    rendered: list[dict[str, Any]] = []
    previous: TurnBlueprint | None = None
    for turn_index, (blueprint, language) in enumerate(zip(blueprint_turns, languages), 1):
        effective = _apply_reference_variation(blueprint, previous, rng, language)
        text, actual_language = _translate_structured(effective.text_en, effective.text_ar, language, variation.dialect, rng)
        noise_applied: list[str] = []
        if variation.noise and rng.random() < 0.55:
            text, noise_applied = _apply_generic_noise(text, rng, "ar" if _contains_arabic(text) and not any(c.isascii() and c.isalpha() for c in text) else "en")
        typo = None
        if variation.typo_rate and rng.random() < variation.typo_rate:
            text, typo = _apply_typo(text, rng, "ar" if _contains_arabic(text) else "en")
        if variation.reference_mode == "natural" and effective.reference:
            natural_map = {
                "Update it.": ("Change that.", "غيّر ده."),
                "Inspect it again.": ("Check the previous item again.", "راجع اللي فات تاني."),
                "Run it again.": ("Repeat the previous operation.", "كرر العملية السابقة."),
            }
            if effective.text_en in natural_map:
                text = natural_map[effective.text_en][0] if language == "en" else natural_map[effective.text_en][1]
                actual_language = _infer_language(text)

        expected = _expected(effective, text, actual_language)
        rendered.append({
            "turn_id": turn_index,
            "text": text,
            "language": actual_language,
            "dialect": variation.dialect if actual_language in {"ar", "mixed"} else "neutral",
            "noise": noise_applied,
            "typo": typo,
            "expected": expected,
        })
        previous = effective

    memory_actions = [
        turn["expected"]["expected_memory_action"]
        for turn in rendered
        if turn["expected"]["expected_memory_action"]
    ]
    final_state: dict[str, Any] = {"memory": {}, "active_reference": None}
    for action in memory_actions:
        if action["action"] in {"write", "update"} and action.get("key"):
            if "value" in action:
                final_state["memory"][action["key"]] = action["value"]
        elif action["action"] == "write_result":
            final_state.setdefault("result_keys", []).append(action.get("key"))

    languages_present = sorted({turn["language"] for turn in rendered})
    dimensions = {
        "language_mode": variation.language_mode,
        "dialect": variation.dialect,
        "typo": any(turn["typo"] for turn in rendered),
        "noise": any(turn["noise"] for turn in rendered),
        "correction": any(turn["expected"]["expected_memory_action"] and turn["expected"]["expected_memory_action"].get("action") == "update" for turn in rendered),
        "topic_switch": variation.topic_switch,
        "reference_mode": variation.reference_mode,
    }
    transcript_hash = hashlib.sha256("\n".join(turn["text"] for turn in rendered).encode("utf-8")).hexdigest()[:12]
    conversation_id = f"dialogue-10-{root_seed}-{index:04d}-{transcript_hash}"
    return {
        "schema_version": SCHEMA_VERSION,
        "generator_version": GENERATOR_VERSION,
        "conversation_id": conversation_id,
        "seed": root_seed,
        "session_seed": _stable_seed(root_seed, index),
        "scenario_id": scenario.scenario_id,
        "category": scenario.family,
        "turns": rendered,
        "language_metadata": {
            "languages_present": languages_present,
            "mode": variation.language_mode,
            "dialect": variation.dialect,
            "switch_points": [
                turn["turn_id"]
                for turn in rendered
                if turn["turn_id"] > 1 and turn["language"] != rendered[turn["turn_id"] - 2]["language"]
            ],
        },
        "generation_dimensions": dimensions,
        "expected_final_state": final_state,
        "metadata": {
            "turn_count": len(rendered),
            "independent_session": True,
            "state_scope": "session-local",
            "no_runtime_execution": True,
        },
    }


def generate_dialogues(count: int = DEFAULT_COUNT, seed: int = DEFAULT_SEED) -> list[dict[str, Any]]:
    if count < 1:
        raise ValueError("count must be >= 1")
    sessions: list[dict[str, Any]] = []
    for index in range(count):
        scenario = SCENARIOS[index % len(SCENARIOS)]
        sessions.append(_render_session(seed, index, scenario))
    return sessions


def iter_dialogues(count: int = DEFAULT_COUNT, seed: int = DEFAULT_SEED) -> Iterable[dict[str, Any]]:
    for session in generate_dialogues(count=count, seed=seed):
        yield session


def validate_dialogues(dialogues: list[dict[str, Any]], expected_count: int | None = None) -> dict[str, Any]:
    errors: list[str] = []
    ids: set[str] = set()
    transcripts: set[str] = set()
    required = {
        "schema_version", "generator_version", "conversation_id", "seed", "session_seed",
        "scenario_id", "category", "turns", "language_metadata", "generation_dimensions",
        "expected_final_state", "metadata",
    }
    for position, dialogue in enumerate(dialogues):
        missing = required - dialogue.keys()
        if missing:
            errors.append(f"session[{position}] missing keys: {sorted(missing)}")
            continue
        cid = dialogue["conversation_id"]
        if cid in ids:
            errors.append(f"duplicate conversation_id: {cid}")
        ids.add(cid)
        if not isinstance(dialogue["turns"], list) or len(dialogue["turns"]) < 2:
            errors.append(f"{cid}: conversation must contain >=2 turns")
            continue
        texts = []
        for turn_pos, turn in enumerate(dialogue["turns"], 1):
            for key in ("turn_id", "text", "language", "dialect", "noise", "typo", "expected"):
                if key not in turn:
                    errors.append(f"{cid}/turn{turn_pos}: missing {key}")
            expected = turn.get("expected", {})
            for key in (
                "expected_class", "expected_intent", "expected_slots", "expected_entities",
                "expected_reference", "expected_memory_action", "expected_tool", "expected_clarification",
            ):
                if key not in expected:
                    errors.append(f"{cid}/turn{turn_pos}: missing expected.{key}")
            texts.append(str(turn.get("text", "")))
        signature = "\n".join(texts)
        transcripts.add(signature)
        if not dialogue["metadata"].get("independent_session"):
            errors.append(f"{cid}: not marked independent_session")
    if expected_count is not None and len(dialogues) != expected_count:
        errors.append(f"expected {expected_count} dialogues, got {len(dialogues)}")
    return {
        "valid": not errors,
        "count": len(dialogues),
        "unique_ids": len(ids),
        "unique_transcripts": len(transcripts),
        "duplicate_transcripts": len(dialogues) - len(transcripts),
        "errors": errors,
    }


def write_dialogues(dialogues: list[dict[str, Any]], output_dir: str | Path, *, seed: int, filename: str | None = None) -> tuple[Path, Path]:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    filename = filename or f"dialogues_phase10_seed_{seed}.jsonl"
    jsonl_path = target / filename
    with jsonl_path.open("w", encoding="utf-8") as handle:
        for dialogue in dialogues:
            handle.write(json.dumps(dialogue, ensure_ascii=False, separators=(",", ":")) + "\n")
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generator_version": GENERATOR_VERSION,
        "seed": seed,
        "count": len(dialogues),
        "conversation_ids": [dialogue["conversation_id"] for dialogue in dialogues],
        "categories": {category: sum(1 for item in dialogues if item["category"] == category) for category in sorted({d["category"] for d in dialogues})},
        "language_modes": {mode: sum(1 for item in dialogues if item["language_metadata"]["mode"] == mode) for mode in sorted({d["language_metadata"]["mode"] for d in dialogues})},
        "dimensions": {
            name: sum(1 for item in dialogues if item["generation_dimensions"][name])
            for name in ("typo", "noise", "correction", "topic_switch")
        },
        "reproducibility": {
            "seeded": True,
            "per_session_seed": "sha256(root_seed:index) first 8 bytes",
            "runtime_state_shared": False,
        },
        "output": str(jsonl_path.as_posix()),
    }
    manifest_path = target / "dialogues_phase10_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return jsonl_path, manifest_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Deterministic SHURY Phase 10 multi-turn dialogue generator")
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--output-dir", default="benchmarks/dialogues")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()

    dialogues = generate_dialogues(args.count, args.seed)
    validation = validate_dialogues(dialogues, expected_count=args.count)
    if not validation["valid"]:
        raise SystemExit(json.dumps(validation, ensure_ascii=False, indent=2))
    if not args.validate_only:
        write_dialogues(dialogues, args.output_dir, seed=args.seed)
    print(json.dumps({**validation, "seed": args.seed, "output_dir": args.output_dir}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
