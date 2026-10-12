from __future__ import annotations

import argparse
import json
import os
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import app.knowledge.memory as memory_mod
from app.knowledge.memory import get_memory
from app.runtime.agent import run_agent


CATEGORIES = [
    "social",
    "personal_memory",
    "memory_recall",
    "task_execution",
    "multi_step",
    "research",
    "data_analysis",
    "ambiguous",
    "context_reference",
    "long_horizon_mixed",
]

SOCIAL_PATTERNS = [
    ("hello", "greeting"),
    ("hi shury", "greeting"),
    ("good morning", "greeting"),
    ("how are you?", "how_are_you"),
    ("thanks", "thanks"),
    ("bye", "goodbye"),
]

CONVERSATION_TEMPLATES = {
    "social": [
        ("hello", "greeting"),
        ("hi shury", "greeting"),
        ("how are you?", "how_are_you"),
        ("thanks", "thanks"),
    ],
    "personal_memory": [
        ("my name is Abdullah", "remember_fact"),
        ("I am from Luxor", "remember_fact"),
        ("what is my name?", "recall_fact"),
        ("where am I from?", "recall_fact"),
        ("do you remember my name?", "recall_fact"),
    ],
    "memory_recall": [
        ("remember that my favorite editor is VS Code", "remember_fact"),
        ("what editor do I prefer?", "recall_fact"),
        ("forget my city", "forget_fact"),
        ("what is my city?", "recall_fact"),
        ("what do you remember about me?", "memory_profile"),
    ],
    "task_execution": [
        ("calculate 25*16", "calculate"),
        ("save the result as total", "remember_result"),
        ("what is total?", "recall_fact"),
        ("calculate 40+10", "calculate"),
    ],
    "multi_step": [
        ("calculate 20*15", "calculate"),
        ("save the result as budget_base", "remember_result"),
        ("increase it by 20%", "calculate"),
        ("save the result as final_budget", "remember_result"),
        ("what is final_budget?", "recall_fact"),
    ],
    "research": [
        ("search the web for agent memory", "web_research"),
        ("focus on recent papers", "scientific_research"),
        ("compare the sources", "rag_reasoning"),
        ("summarize the result in English", "rag_reasoning"),
        ("which evidence supports the comparison?", "rag_reasoning"),
    ],
    "data_analysis": [
        ("analyze sales.csv for anomalies", "data_analysis"),
        ("analyze outliers in sales.csv", "data_analysis"),
        ("analyze sales.csv and summarize the findings", "data_analysis"),
        ("analyze sales.csv and identify records to inspect next", "data_analysis"),
        ("analyze sales.csv and recommend a follow-up", "data_analysis"),
    ],
    "ambiguous": [
        ("review the report", "clarify"),
        ("update it", "clarify"),
        ("compare it to the previous one", "clarify"),
        ("do that now", "clarify"),
    ],
    "context_reference": [
        ("analyze sales.csv for anomalies", "data_analysis"),
        ("focus on Q3", "data_analysis"),
        ("compare it to last year", "data_analysis"),
        ("summarize it in Arabic", "data_analysis"),
    ],
    "long_horizon_mixed": [
        ("my name is Abdullah", "remember_fact"),
        ("I am from Luxor", "remember_fact"),
        ("calculate 12*8", "calculate"),
        ("save it as total", "remember_result"),
        ("What is my name?", "recall_fact"),
        ("where am I from?", "recall_fact"),
        ("what was the last result?", "recall_fact"),
        ("summarize what you know about me", "memory_profile"),
    ],
}

ARABIC_TRANSLATIONS = {
    "hello": "مرحبا",
    "hi shury": "أهلا يا شوري",
    "how are you?": "عامل إيه؟",
    "thanks": "شكرا",
    "my name is Abdullah": "اسمي عبدالله",
    "I am from Luxor": "أنا من الأقصر",
    "what is my name?": "ما اسمي؟",
    "where am I from?": "من أين أنا؟",
    "do you remember my name?": "هل تتذكر اسمي؟",
    "remember that my favorite editor is VS Code": "تذكر أن محرري المفضل هو VS Code",
    "what editor do I prefer?": "ما محرر النصوص الذي أفضله؟",
    "forget my city": "انس مدينتي",
    "what is my city?": "ما مدينتي؟",
    "what do you remember about me?": "ماذا تتذكر عني؟",
    "calculate 25*16": "احسب 25*16",
    "save the result as total": "احفظ النتيجة باسم total",
    "what is total?": "ما قيمة total؟",
    "calculate 40+10": "احسب 40+10",
    "calculate 20*15": "احسب 20*15",
    "save the result as budget_base": "احفظ النتيجة باسم budget_base",
    "increase it by 20%": "زدها بنسبة 20 بالمئة",
    "save the result as final_budget": "احفظ النتيجة باسم final_budget",
    "what is final_budget?": "ما قيمة final_budget؟",
    "search the web for agent memory": "ابحث في الويب عن ذاكرة الوكلاء",
    "focus on recent papers": "ركز على الأوراق البحثية الحديثة",
    "compare the sources": "قارن المصادر",
    "summarize the result in English": "لخص النتيجة بالإنجليزية",
    "which evidence supports the comparison?": "ما الأدلة التي تدعم المقارنة؟",
    "analyze sales.csv for anomalies": "حلل ملف sales.csv لاكتشاف القيم الشاذة",
    "analyze outliers in sales.csv": "حلل القيم المتطرفة في ملف sales.csv",
    "analyze sales.csv and summarize the findings": "حلل ملف sales.csv ولخص النتائج",
    "analyze sales.csv and identify records to inspect next": "حلل ملف sales.csv وحدد السجلات التي ينبغي فحصها بعد ذلك",
    "analyze sales.csv and recommend a follow-up": "حلل ملف sales.csv واقترح تحليلا إضافيا",
    "review the report": "راجع التقرير",
    "update it": "حدثه",
    "compare it to the previous one": "قارنه بالتقرير السابق",
    "do that now": "نفذ ذلك الآن",
    "analyze the sales report": "حلل تقرير المبيعات",
    "focus on Q3": "ركز على الربع الثالث",
    "compare it to last year": "قارنه بالعام الماضي",
    "summarize it in Arabic": "لخصه بالعربية",
    "calculate 12*8": "احسب 12*8",
    "save it as total": "احفظها باسم total",
    "What is my name?": "ما اسمي؟",
    "what was the last result?": "ما آخر نتيجة؟",
    "summarize what you know about me": "لخص ما تعرفه عني",
}

EXPECTED_TOOLS = {
    "remember_fact": {"remember_fact"},
    "remember_result": {"remember_result", "remember_last_result"},
    "forget_fact": {"forget_fact"},
    "recall_fact": {"recall_fact", "recall_last_result"},
    "memory_profile": {"memory_profile"},
    "calculate": {"calculator"},
    "web_research": {"web_research", "internet_research"},
    "scientific_research": {"arxiv_research"},
    "rag_reasoning": {"rag_query", "agentic_rag"},
    "data_analysis": {"analyze_dataset", "profile_dataset", "diagnose_dataset"},
}


def _build_expected(turn_text: str, expected_tool: str, index: int) -> dict[str, Any]:
    requires_clarification = expected_tool == "clarify"
    if expected_tool in {"remember_fact", "remember_result", "forget_fact"}:
        key = "name" if "name" in turn_text.lower() else "city" if "city" in turn_text.lower() else "result"
        return {
            "turn": index,
            "expected_tool": expected_tool,
            "expected_status": "needs_user" if requires_clarification else "completed",
            "expected_key": key,
            "requires_clarification": requires_clarification,
        }
    if expected_tool in {"recall_fact", "memory_profile"}:
        return {
            "turn": index,
            "expected_tool": expected_tool,
            "expected_status": "completed",
            "requires_clarification": False,
        }
    return {
        "turn": index,
        "expected_tool": expected_tool,
        "expected_status": "needs_user" if requires_clarification else "completed",
        "requires_clarification": requires_clarification,
    }


def generate_sessions(count: int = 1000, seed: int = 1) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    sessions: list[dict[str, Any]] = []
    categories = CATEGORIES[:]
    rng.shuffle(categories)
    for idx in range(count):
        category = categories[idx % len(categories)]
        options = CONVERSATION_TEMPLATES[category]
        language_mode = "mixed" if rng.random() < 0.35 else ("arabic" if rng.random() < 0.5 else "english")
        language_choices = [
            "english" if position == 0 else "arabic" if position == 1 else rng.choice(("english", "arabic"))
            for position in range(len(options))
        ] if language_mode == "mixed" else [language_mode] * len(options)
        chosen = []
        for position, ((message, expected_tool), turn_language) in enumerate(zip(options, language_choices), 1):
            text = ARABIC_TRANSLATIONS.get(message, message) if turn_language == "arabic" else message
            chosen.append({"turn": position, "text": text, "expected_tool": expected_tool})
        turn_count = len(chosen)
        session = {
            "id": f"dialogue-{seed}-{idx:04d}",
            "seed": seed,
            "category": category,
            "language": language_mode,
            "turns": [item["text"] for item in chosen],
            "expected": [_build_expected(item["text"], item["expected_tool"], idx2) for idx2, item in enumerate(chosen, 1)],
            "metadata": {
                "turn_count": turn_count,
                "superset": "stateful-conversation-agent",
                "language_mix": "ar-en" if language_mode == "mixed" else language_mode,
            },
        }
        sessions.append(session)
    return sessions


def _run_turns_for_session(session: dict[str, Any], live: bool = False, output_dir: str | Path = "benchmarks") -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    session_id = session["id"]
    runtime_dir = Path(output_dir) / "runtime" / session_id
    runtime_dir.mkdir(parents=True, exist_ok=True)
    memory_mod.configure(runtime_dir / "memory.db")
    env_keys = ("AGENT_WORKSPACE", "AGENT_LEARNING_DB", "AGENT_SKILLS_DB", "AGENT_RAG_DB")
    old_env = {key: os.environ.get(key) for key in env_keys}
    workspace = runtime_dir / "workspace"
    if live:
        workspace.mkdir(parents=True, exist_ok=True)
        if session["category"] in {"data_analysis", "context_reference"}:
            (workspace / "sales.csv").write_text(
                "product,region,units,revenue\nA,north,12,120\nB,south,15,180\nC,east,11,110\nD,west,90,1800\nE,north,13,130\n",
                encoding="utf-8",
            )
        os.environ["AGENT_WORKSPACE"] = str(workspace)
        os.environ["AGENT_LEARNING_DB"] = str(runtime_dir / "learning.db")
        os.environ["AGENT_SKILLS_DB"] = str(runtime_dir / "skills.db")
        os.environ["AGENT_RAG_DB"] = str(runtime_dir / "rag.db")
    try:
        for idx, text in enumerate(session["turns"], 1):
            state = run_agent(text, approve=lambda *_: True, session_id=session_id, max_steps=8, max_seconds=20) if live else None
            expected = session["expected"][idx - 1]
            actual_tools = [] if state is None or state.plan is None else [step.tool for step in state.plan.steps]
            expected_tool = expected["expected_tool"]
            expected_tools = EXPECTED_TOOLS.get(expected_tool, set())
            if expected_tool in {"greeting", "how_are_you", "thanks", "clarify"}:
                route_matches = not actual_tools
            else:
                route_matches = bool(expected_tools.intersection(actual_tools))
            status_matches = bool(state is not None and state.status == expected["expected_status"])
            passed = bool(live and state is not None and status_matches and route_matches)
            results.append({
                "turn": idx,
                "user_message": text,
                "expected": expected,
                "actual_tools": actual_tools,
                "status": state.status if state is not None else "skipped",
                "route_matches": route_matches if live else None,
                "status_matches": status_matches if live else None,
                "passed": passed if live else None,
            })
    finally:
        for key, value in old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    return {"conversation_id": session["id"], "category": session["category"], "results": results}


def run_stateful_benchmark(count: int = 1000, seed: int = 1, rounds: int = 3, output_dir: str = "benchmarks", live: bool = False) -> dict[str, Any]:
    base_dir = Path(output_dir)
    base_dir.mkdir(parents=True, exist_ok=True)
    if live:
        from app.evaluation.real_user_100 import patch_network
        patch_network()
    (base_dir / "dialogues").mkdir(exist_ok=True)
    (base_dir / "results").mkdir(exist_ok=True)
    (base_dir / "failures").mkdir(exist_ok=True)
    (base_dir / "clusters").mkdir(exist_ok=True)
    (base_dir / "regression").mkdir(exist_ok=True)
    (base_dir / "reports").mkdir(exist_ok=True)

    all_sessions: list[dict[str, Any]] = []
    for round_index in range(1, rounds + 1):
        round_seed = seed + round_index - 1
        sessions = generate_sessions(count=count, seed=round_seed)
        all_sessions.extend(sessions)
        dialogues_path = base_dir / "dialogues" / f"dialogues_round_{round_index:02d}.json"
        dialogues_path.write_text(json.dumps(sessions, ensure_ascii=False, indent=2), encoding="utf-8")

    results = []
    pass_count = 0
    route_pass_count = 0
    status_pass_count = 0
    turn_total = 0
    evaluated_turns = 0
    category_counts: dict[str, int] = defaultdict(int)
    category_turns: dict[str, int] = defaultdict(int)
    category_passes: dict[str, int] = defaultdict(int)

    for session in all_sessions:
        category_counts[session["category"]] += 1
        evaluated = _run_turns_for_session(session, live=live, output_dir=base_dir)
        results.append(evaluated)
        for item in evaluated["results"]:
            turn_total += 1
            category_turns[session["category"]] += 1
            if live:
                evaluated_turns += 1
                route_pass_count += int(item["route_matches"] is True)
                status_pass_count += int(item["status_matches"] is True)
            if item["passed"] is True:
                pass_count += 1
                category_passes[session["category"]] += 1

    total_dialogs = len(all_sessions)
    categories_summary = {}
    for category in sorted(category_counts):
        category_total = category_turns[category]
        categories_summary[category] = {
            "count": category_counts[category],
            "turns": category_total,
            "pass_rate": round((category_passes[category] / max(1, category_total)) * 100, 2) if live else None,
        }

    successful_conversations = sum(
        bool(conversation["results"]) and all(turn["passed"] is True for turn in conversation["results"])
        for conversation in results
    )
    conversation_success_rate = (
        round((successful_conversations / max(1, len(results))) * 100, 2) if live else None
    )
    summary = {
        "dialogs": total_dialogs,
        "turns_total": turn_total,
        "pass_count": pass_count,
        "evaluated_turns": evaluated_turns,
        "fail_count": max(0, evaluated_turns - pass_count),
        "pass_rate": round((pass_count / max(1, evaluated_turns)) * 100, 2) if live else None,
        "categories": categories_summary,
        "metrics": {
            "tool_routing_accuracy": round((route_pass_count / max(1, evaluated_turns)) * 100, 2) if live else None,
            "status_accuracy": round((status_pass_count / max(1, evaluated_turns)) * 100, 2) if live else None,
            "reference_resolution": None,
            "memory_correctness": None,
            "conversation_success": conversation_success_rate,
            "false_execution": None,
            "hallucinated_memory": None,
        },
    }

    run_id = f"benchmark_run_{seed:03d}"
    run_payload = {
        "run_id": run_id,
        "seed": seed,
        "rounds": rounds,
        "dialogs": total_dialogs,
        "execution_mode": "live" if live else "generation_only",
        "categories": summary["categories"],
        "summary": summary,
        "results": results,
    }
    (base_dir / "results" / f"{run_id}.json").write_text(json.dumps(run_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (base_dir / "results" / f"{run_id}_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    failure_clusters: dict[str, list[dict[str, Any]]] = {
        "reference_resolution": [],
        "memory_update": [],
        "mixed_language": [],
        "tool_routing": [],
    }
    failures = []
    for session, conversation in zip(all_sessions, results):
        for turn in conversation["results"]:
            if turn["passed"] is not False:
                continue
            failure = {
                "conversation_id": session["id"],
                "category": session["category"],
                "turn": turn["turn"],
                "user_message": turn["user_message"],
                "expected_tool": turn["expected"]["expected_tool"],
                "actual_tools": turn["actual_tools"],
                "status": turn["status"],
                "language": session["language"],
            }
            failures.append(failure)
            expected_tool = failure["expected_tool"]
            if expected_tool in {"recall_fact", "memory_profile"}:
                failure_clusters["reference_resolution"].append(failure)
            elif expected_tool in {"remember_fact", "remember_result", "forget_fact"}:
                failure_clusters["memory_update"].append(failure)
            elif session["language"] == "mixed":
                failure_clusters["mixed_language"].append(failure)
            else:
                failure_clusters["tool_routing"].append(failure)
    (base_dir / "failures" / f"{run_id}_failures.json").write_text(
        json.dumps(failures, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (base_dir / "clusters" / f"{run_id}_failure_clusters.json").write_text(
        json.dumps(failure_clusters, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (base_dir / "regression" / f"{run_id}_regression_cases.json").write_text(json.dumps(generate_sessions(min(20, max(1, count)), seed=seed + 99), ensure_ascii=False, indent=2), encoding="utf-8")
    report_path = base_dir / "reports" / f"{run_id}_report.md"
    pass_rate_label = f"{summary['pass_rate']}%" if live else "Not executed (generation only)"
    conversation_success_label = (
        f"{summary['metrics']['conversation_success']}%" if live else "Not measured"
    )
    report_path.write_text(
        "# SHURY Stateful Conversation Benchmark\n\n"
        f"- Dialogs: {total_dialogs}\n"
        f"- Turns: {turn_total}\n"
        f"- Pass rate: {pass_rate_label}\n"
        f"- Conversation success: {conversation_success_label}\n",
        encoding="utf-8",
    )
    return {
        "run_id": run_id,
        "dialogs": total_dialogs,
        "turns_total": turn_total,
        "categories": summary["categories"],
        "summary": summary,
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Seeded, stateful conversational benchmark for SHURY.")
    parser.add_argument("--count", type=int, default=20, help="Number of conversations to generate")
    parser.add_argument("--seed", type=int, default=1, help="Random seed")
    parser.add_argument("--rounds", type=int, default=1, help="Number of rounds")
    parser.add_argument("--output-dir", default="benchmarks", help="Base output directory")
    parser.add_argument("--live", action="store_true", help="Execute the real SHURY runtime for each turn")
    args = parser.parse_args()
    report = run_stateful_benchmark(count=args.count, seed=args.seed, rounds=args.rounds, output_dir=args.output_dir, live=args.live)
    print(json.dumps({"run_id": report["run_id"], "dialogs": report["dialogs"], "turns_total": report["turns_total"], "summary": report["summary"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
