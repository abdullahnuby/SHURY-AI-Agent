"""Dedicated read-only counterfactual rollout tool for Phase 6."""
from __future__ import annotations

from app.knowledge.memory import get_memory
from app.runtime.registry import load_tools, tool
from app.runtime.session_context import current_session_id
from app.world.counterfactual import action_from_tool
from app.world.model import WorldModel
from app.world.store import load_session_world


@tool(
    "يحاكي تسلسلًا افتراضيًا من الأفعال باستخدام النموذج المتعلم دون تنفيذ أي أداة أو تعديل الذاكرة. "
    "لا يتجاوز الحالات أو الأفعال التي توجد لها أدلة كافية، ويوقف المسار عند ارتفاع عدم اليقين.",
    {"actions": "قائمة JSON من {tool, args} بالترتيب"},
    name="simulate_counterfactual",
    triggers=("counterfactual", "what if", "hypothetical rollout", "محاكاة افتراضية", "ماذا لو"),
    match=lambda g: any(x in str(g or "").casefold() for x in (
        "counterfactual", "what if", "hypothetical rollout", "محاكاة افتراضية", "ماذا لو"
    )),
    capability="world_simulation",
    produces=(),
    cost=1.2,
    duration=0.1,
    parallel_safe=True,
    idempotent=True,
    verification_level="strong",
    intent_priority=16,
)
def simulate_counterfactual_tool(actions):
    if not isinstance(actions, list) or not actions:
        raise ValueError("actions لازم تكون قائمة غير فارغة")
    registry = load_tools()
    normalized = []
    for item in actions:
        if not isinstance(item, dict):
            raise ValueError("كل عنصر في actions لازم يكون كائن JSON")
        name = str(item.get("tool") or "")
        if not name:
            raise ValueError("كل action لازم يحتوي tool")
        if name in {"simulate_action", "simulate_counterfactual"}:
            raise ValueError("لا يمكن إدخال أداة المحاكاة نفسها داخل محاكاة افتراضية")
        target = registry.get(name)
        if target is None:
            raise ValueError(f"الأداة غير موجودة: {name}")
        args = item.get("args", {})
        normalized.append(action_from_tool(target, args))
    world = load_session_world(get_memory(), current_session_id())
    simulation = WorldModel().simulate_counterfactual(world, normalized, max_depth=len(normalized))
    return simulation.to_dict()
