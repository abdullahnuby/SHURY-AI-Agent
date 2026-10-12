from __future__ import annotations

from app.intelligence.semantic import SemanticContract, semantic_understand


CASES: tuple[tuple[str, str], ...] = (
    # SOCIAL: standalone social acts across English, Arabic and common variants.
    *[("SOCIAL", text) for text in (
        "hello", "hi there", "hey", "good morning", "good afternoon", "good evening",
        "اهلا", "أهلا وسهلا", "السلام عليكم", "ازيك", "إزيك", "عامل ايه",
        "how are you", "how are you doing", "how is it going", "thanks",
        "thank you so much", "شكرا", "goodbye", "bye",
    )],
    # MEMORY_WRITE: facts/preferences are memory operations, not generic tasks.
    *[("MEMORY_WRITE", text) for text in (
        "my name is Abdullah", "I am from Luxor", "I'm from Aswan", "I'm originally from Cairo",
        "I prefer dark mode", "I like Alexandria", "I usually use VS Code", "my city is Luxor",
        "my language is Arabic", "remember that my name is Abdullah", "save this information: name=Abdullah",
        "store my city as Luxor", "remember this fact: project=SHURY", "احفظ أن اسمي عبدالله",
        "أنا من الأقصر", "أنا أصلي من أسوان", "اسمي عبدالله", "مدينتي هي الأقصر", "أنا بفضل الوضع الداكن",
    )],
    # MEMORY_READ: questions about durable user state stay on the memory path.
    *[("MEMORY_READ", text) for text in (
        "what is my name?", "who am i?", "where am i from?", "what is my city?", "what is my origin?",
        "do you remember my name?", "what language do i prefer?", "فاكر اسمي؟", "أنا من فين؟",
        "فاكر أنا منين؟", "ما اسمي؟", "من أنا؟", "إيه مدينتي؟", "ماذا تعرف عني؟",
        "what do you remember about me?", "show my memory profile", "search my memory", "ابحث في ذاكرتي",
        "ماذا تتذكر عني؟",
    )],
    # INFORMATION: ordinary knowledge/system questions must not become execution tasks.
    *[("INFORMATION", text) for text in (
        "what is a black hole?", "what is photosynthesis?", "why is the sky blue?", "where is the Nile?",
        "when is Ramadan?", "what can you do?", "what are your capabilities?", "what time is it?",
        "tell me the current time", "what day is today?", "ماذا تستطيع؟", "ما هو الثقب الأسود؟",
        "لماذا السماء زرقاء؟", "أين النيل؟", "متى الوقت؟", "ما هو الذكاء الاصطناعي؟",
        "how does gravity work?", "what is machine learning?", "ممكن تشرح الجاذبية؟",
    )],
    # RESEARCH / ANALYSIS / EXECUTION: explicit actionable domains retain task routing.
    *[("RESEARCH", text) for text in (
        "search the web for current weather", "search online for latest AI news",
        "find recent academic papers about RAG", "research the latest agent memory methods",
        "browse the internet for current prices", "ابحث على الانترنت عن الطقس الحالي",
        "دور اونلاين على آخر الأخبار التقنية", "أحدث الأبحاث العلمية عن الوكلاء",
        "ابحث على الويب عن معلومات حديثة", "تعلم من الإنترنت عن RAG",
    )],
    *[("ANALYSIS", text) for text in (
        "analyze sales.csv", "profile the data", "find outliers in the dataset",
        "diagnose the dataset", "حلل البيانات",
    )],
    *[("EXECUTION", text) for text in (
        "calculate 20*5", "compute 10+3", "احسب 30/5", "build the project", "run the tests and build the project",
    )],
    # CLARIFICATION: ambiguity/correction is a control state and must stop before planning.
    *[("CLARIFICATION", text) for text in (
        "update it", "No, I mean Ahmed", "solve this problem",
    )],
)


def test_phase5_has_100_deterministic_conversational_inputs():
    assert len(CASES) == 100
    observed: dict[str, int] = {}
    for expected, text in CASES:
        parse = semantic_understand(text)
        contract = SemanticContract.from_parse(parse)
        observed[contract.conversation_class] = observed.get(contract.conversation_class, 0) + 1
        assert contract.conversation_class == expected, text
    assert sum(observed.values()) == 100


def test_phase5_social_turns_do_not_need_planning(monkeypatch, tmp_path):
    from app.knowledge import memory as memory_module
    import app.runtime.agent as agent_module

    memory_module.configure(tmp_path / "memory.db")
    calls = []

    class PlannerMustNotRun:
        def __init__(self, *args, **kwargs):
            pass

        def plan(self, *args, **kwargs):
            calls.append((args, kwargs))
            raise AssertionError("social conversation reached the planner")

    monkeypatch.setattr(agent_module, "RulePlanner", PlannerMustNotRun)
    monkeypatch.setattr(agent_module, "LOG_FILE", tmp_path / "agent.jsonl")
    monkeypatch.setenv("SHURY_NLP_MODE", "off")

    social_texts = [text for expected, text in CASES if expected == "SOCIAL"]
    assert len(social_texts) == 20
    for index, text in enumerate(social_texts):
        state = agent_module.run_agent(text, session_id=f"phase5-social-{index}")
        assert state.status == "completed", text
        assert not state.plan.steps, text
        assert state.final_message.strip(), text
    assert calls == []
