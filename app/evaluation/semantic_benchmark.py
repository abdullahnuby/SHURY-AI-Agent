from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import tempfile
from app.core.time import now_in_timezone

import app.knowledge.memory as memory
from app.domain.world import WorldState
from app.intelligence.semantic import semantic_understand


@dataclass(frozen=True)
class SemanticCase:
    text: str
    expected_intent: str
    expected_speech_act: str | None = None
    expected_language: str | None = None
    expected_fresh: bool | None = None
    expected_slot: tuple[str, str] | None = None


CASES: tuple[SemanticCase, ...] = (
    SemanticCase("compute 12 times 7", "calculate"),
    SemanticCase("what is 25 divided by 5", "calculate", "question"),
    SemanticCase("work out 18 plus 24", "calculate"),
    SemanticCase("احسب 15 زائد 9", "calculate", expected_language="ar"),
    SemanticCase("what time is it right now", "time", "question"),
    SemanticCase("tell me the current date", "time", "request"),
    SemanticCase("الساعة كام دلوقتي", "time", expected_language="ar"),
    SemanticCase("remember that my name is Abdullah", "remember_fact", "command", expected_slot=("fact:name", "abdullah")),
    SemanticCase("store my city as Cairo", "remember_fact", expected_slot=("fact:city", "cairo")),
    SemanticCase("اسمي عبدالله", "remember_fact", "statement", expected_language="ar", expected_slot=("fact:name", "عبدالله")),
    SemanticCase("what is my name", "recall_fact", "question", expected_slot=("recall:key", "name")),
    SemanticCase("what is my city", "recall_fact", "question", expected_slot=("recall:key", "city")),
    SemanticCase("ما هي مدينتي", "recall_fact", "question", expected_language="ar", expected_slot=("recall:key", "city")),
    SemanticCase("search my memory for Cairo", "memory_search"),
    SemanticCase("ابحث في ذاكرتك عن الاسم", "memory_search", expected_language="ar"),
    SemanticCase("what do you remember about me", "memory_profile", "question"),
    SemanticCase("ماذا تعرف عني", "memory_profile", "question", expected_language="ar"),
    SemanticCase("forget my city", "forget_fact", "command"),
    SemanticCase("delete that memory", "forget_fact", "command"),
    SemanticCase("save the result as total", "remember_result", "command", expected_slot=("result:key", "total")),
    SemanticCase("store the output as baseline", "remember_result", expected_slot=("result:key", "baseline")),
    SemanticCase("save the previous result as total", "remember_last_result", "command", expected_slot=("result:key", "total")),
    SemanticCase("I prefer dark mode", "remember_memory", "statement", expected_slot=("preference:theme", "dark")),
    SemanticCase("I'm from Luxor", "remember_fact", "statement", expected_slot=("fact:origin", "luxor")),
    SemanticCase("where do I come from?", "recall_fact", "question", expected_slot=("recall:key", "origin")),
    SemanticCase("أنا بفضل الوضع الداكن", "remember_memory", "statement", expected_language="ar"),
    SemanticCase("I usually use VS Code", "remember_memory", "statement"),
    SemanticCase("search the web for current fuel prices", "web_research", expected_fresh=True),
    SemanticCase("look online for today's AI news", "web_research", expected_fresh=True),
    SemanticCase("what is the weather today?", "web_research", "question", expected_fresh=True),
    SemanticCase("find recent academic papers about agent memory", "scientific_research", expected_fresh=True),
    SemanticCase("search the latest scientific literature on RAG", "scientific_research", expected_fresh=True),
    SemanticCase("ابحث عن أحدث الأبحاث العلمية عن الذاكرة", "scientific_research", expected_language="ar", expected_fresh=True),
    SemanticCase("learn from the internet how to improve RAG", "open_world_learning"),
    SemanticCase("research and learn about agent evaluation", "open_world_learning"),
    SemanticCase("find github repositories for agent memory", "github_discovery"),
    SemanticCase("search github for RAG projects", "github_discovery"),
    SemanticCase("analyze this github repository for architecture", "github_learning"),
    SemanticCase("analyze this dataset for anomalies", "data_analysis"),
    SemanticCase("profile the sales data and find outliers", "data_analysis"),
    SemanticCase("analyze all files in this workspace", "workspace_reasoning"),
    SemanticCase("join these csv files and compare them", "workspace_reasoning"),
    SemanticCase("run the tests and build the project", "development_validation"),
    SemanticCase("verify the repository still compiles", "development_validation"),
    SemanticCase("inspect this repository architecture", "development_inspection"),
    SemanticCase("show git status and recent changes", "development_git"),
    SemanticCase("retrieve evidence from the knowledge base about memory", "rag_reasoning"),
    SemanticCase("answer using the indexed documents", "rag_reasoning"),
    SemanticCase("Could you verify the repo still passes its checks before we touch it?", "development_validation", "request"),
    SemanticCase("احفظ النتيجة باسم total", "remember_result", "command", expected_language="ar", expected_slot=("result:key", "total")),
)


def run_semantic_benchmark() -> dict:
    root = Path(tempfile.mkdtemp(prefix="agent-semantic-bench-"))
    memory.configure(root / "memory.db")
    world = WorldState(last_goal="calculate 9*9", last_outputs={"last_result": 81})
    checks = []
    for index, case in enumerate(CASES, 1):
        parse = semantic_understand(case.text, world=world, session_id="semantic-bench")
        top = parse.top_intent.name if parse.top_intent else ""
        ok = top == case.expected_intent
        details = [f"intent={top!r}"]
        if case.expected_speech_act is not None:
            ok = ok and parse.speech_act == case.expected_speech_act
            details.append(f"speech={parse.speech_act!r}")
        if case.expected_language is not None:
            ok = ok and parse.language == case.expected_language
            details.append(f"language={parse.language!r}")
        if case.expected_fresh is not None:
            ok = ok and parse.requires_fresh_data == case.expected_fresh
            details.append(f"fresh={parse.requires_fresh_data!r}")
        if case.expected_slot is not None:
            key, value = case.expected_slot
            actual = parse.slots.get(key)
            ok = ok and actual == value
            details.append(f"slot[{key}]={actual!r}")
        checks.append({"index": index, "text": case.text, "ok": bool(ok), "details": "; ".join(details)})
    passed = sum(1 for item in checks if item["ok"])
    return {"passed": passed, "total": len(checks), "score": round(passed / max(1, len(checks)), 3), "checks": checks}
