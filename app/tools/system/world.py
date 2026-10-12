"""Read-only world-model tools used by the model before committing an action."""
from __future__ import annotations

from app.runtime.registry import tool, load_tools
from app.world.model import WorldModel
from app.world.store import load_session_world
from app.knowledge.memory import get_memory
from app.runtime.session_context import current_session_id


@tool(
    "يحاكي أثر أداة بدون تنفيذها: يعرض تغييرات الحالة المتوقعة والمخاطر وقابلية الرجوع."
    " استخدمها قبل الأفعال غير القابلة للعكس أو عالية المخاطر أو عندما تكون العواقب غير واضحة.",
    {"tool": "اسم الأداة", "args": "كائن JSON بالوسائط"},
    name="simulate_action",
    triggers=("simulate action", "predict consequence", "what will happen", "simulate", "حاكي العملية", "ايه اللي هيحصل", "توقع النتيجة"),
    match=lambda g: any(x in str(g or "").casefold() for x in (
        "simulate action", "predict consequence", "what will happen", "simulate", "حاكي العملية", "ايه اللي هيحصل", "توقع النتيجة"
    )),
    capability="world_simulation",
    produces=(),
    cost=0.8,
    duration=0.05,
    parallel_safe=True,
    idempotent=True,
    verification_level="strong",
    intent_priority=14,
)
def simulate_action_tool(tool: str, args: dict):
    registry = load_tools()
    target = registry.get(str(tool))
    if target is None:
        raise ValueError(f"الأداة غير موجودة: {tool}")
    if not isinstance(args, dict):
        raise ValueError("args لازم تكون JSON object")
    errors = target.validate_args(args)
    if errors:
        raise ValueError("; ".join(errors))
    world = load_session_world(get_memory(), current_session_id())
    prediction = WorldModel().predict(target, args, world)
    return prediction.to_dict()
