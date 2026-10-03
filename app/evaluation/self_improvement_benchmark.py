from __future__ import annotations
from pathlib import Path
from tempfile import TemporaryDirectory

from app.learning.diagnosis import task_signature, failure_class, sanitize, contrastive_lesson
from app.learning.models import ExperienceRecord, Lesson, SkillEvaluation
from app.learning.store import LearningStore
from app.learning.promotion import promotion_gate
from app.learning.manager import SelfImprovementManager
from app.skills.registry import SkillBank
from app.planning.adaptive_planning import skill_to_plan
from app.runtime.registry import load_tools


def _experience(run_id, goal, status, env):
    return ExperienceRecord(
        run_id=run_id, goal=goal, task_signature=task_signature(goal), status=status,
        reward=1.0 if status == "completed" else 0.0,
        verified_rate=1.0 if status == "completed" else 0.0,
        steps=({"step": "s1", "tool": "calculator", "status": "done" if status == "completed" else "failed",
                "verified": status == "completed", "error": "" if status == "completed" else "invalid syntax",
                "attempts": 1, "capability": "calculation", "depends_on": ()},),
        failure_class=None if status == "completed" else "invalid_input", lesson_keys=(), session_id=None,
        created_at="2026-09-30T00:00:00", environment_signature=env,
    )


def run_self_improvement_benchmark() -> dict:
    checks = []
    checks.append((bool(task_signature("analyze sales data and report anomalies")), "task_signature"))
    checks.append((failure_class("calculator", "invalid syntax") == "invalid_input", "failure diagnosis"))
    checks.append((sanitize("api_key=SECRET123") == "api_key=<redacted>", "secret redaction"))
    checks.append(("SECRET123" not in task_signature("deploy with api_key=SECRET123"), "signature secret isolation"))
    checks.append((hasattr(LearningStore, "record_experience"), "experience store"))

    with TemporaryDirectory() as td:
        root = Path(td)
        store = LearningStore(root / "learning.db")
        failed = _experience("rf", "recover calculation", "failed", "env-f")
        success = _experience("rs", "recover calculation", "completed", "env-s")
        store.record_experience(failed)
        store.record_experience(success)
        lesson_data = contrastive_lesson(success, store.similar_experiences(success.task_signature))
        checks.append((bool(lesson_data and lesson_data["kind"] == "contrastive"), "contrastive learning"))

        skill_bank = SkillBank(root / "skills.db")
        key = "evo:benchmark"
        skill = skill_bank.upsert(
            key=key, name="benchmark", triggers=("calculate", "<n>", "save", "result", "total"),
            workflow=(
                {"tool": "calculator", "depends_on": [], "capability": "calculation"},
                {"tool": "remember_result", "depends_on": ["s1"], "capability": "memory"},
            ), status="candidate",
        )
        plan = skill_to_plan(skill, "calculate 12*7 and save result as total", load_tools())
        checks.append((bool(plan and plan.steps[1].depends_on == ["s1"]), "workflow dependency replay"))

        blocked = promotion_gate(skill, [success, _experience("rs2", "recover calculation", "completed", "env-t")], [
            SkillEvaluation(key, "recover calculation", 1.0, 1.0, 0.0, True, False, "counterfactual", "2026-09-30T00:00:00")
        ])
        checks.append((not blocked["promotable"], "promotion requires positive evidence"))

        manager = SelfImprovementManager(learning_path=root / "manager.db", bank_path=root / "manager-skills.db")
        legacy = Lesson(
            key="reflection:legacy-success", task_signature=success.task_signature, kind="reflection",
            lesson="success narrative without failure evidence", when_to_apply=(success.task_signature,),
            avoid=(), evidence_run_ids=(success.run_id,), confidence=0.5, status="active", uses=0,
            created_at="2026-09-30T00:00:00",
        )
        manager.store.record_experience(success)
        manager.store.upsert_lesson(legacy)
        repaired = SelfImprovementManager(learning_path=root / "manager.db", bank_path=root / "manager-skills.db")
        checks.append((not any(x.key == legacy.key for x in repaired.store.active_lessons()), "legacy lesson reconciliation"))

    passed = sum(1 for ok, _ in checks if ok)
    return {
        "benchmark": "self-improvement",
        "passed": passed,
        "total": len(checks),
        "green": passed == len(checks),
        "details": [{"check": name, "ok": ok} for ok, name in checks],
    }
