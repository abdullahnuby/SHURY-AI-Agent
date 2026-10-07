"""Independent objective and state verification."""
from dataclasses import dataclass
from app.runtime.verify import verify_step


@dataclass(frozen=True)
class Verification:
    ok: bool
    reason: str


def verify_objective(plan, status: str, company_review: dict | None = None) -> Verification:
    if status != "completed":
        return Verification(False, "الخطة لم تكتمل")
    if company_review is not None and not bool(company_review.get("ok")):
        return Verification(False, "المراجع المستقل للشركة لم يثبت اكتمال الهدف")
    unfinished = [s.id for s in plan.steps if s.status != "done"]
    if unfinished:
        return Verification(False, f"خطوات غير مكتملة: {unfinished}")
    return Verification(True, "كل خطوات الهدف تحققت بشكل مستقل")


__all__ = ["verify_step", "Verification", "verify_objective"]
