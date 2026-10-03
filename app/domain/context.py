"""Context resolver for multi-turn references; never invents missing context."""
from app.domain.world import WorldState, resolve_reference
from app.intelligence.keywords import CALC_KW, SAVE_KW, TIME_KW
from app.knowledge.memory import get_memory
import re

PRONOUNS = ("ده", "دي", "ده تاني", "نفسه", "النتيجة", "الناتج", "اللي فات", "السابق")
DATA_FOLLOW_UP_PREFIXES = (
    "focus on ", "compare it ", "compare that ", "summarize it", "summarize that",
    "summarise it", "summarise that", "ركز على", "قارنه", "قارنها", "لخصه", "لخصها",
)

def resolve_goal(goal: str, world: WorldState, session_id: str | None = None) -> tuple[str, bool]:
    # A last-result question is itself a memory/context query. Do not replace the
    # result token with its value before intent routing, or it becomes "ما هو 84؟".
    if re.search(r"^(?:what was (?:the )?(?:last |previous )?(?:result|output)|ما(?: هو)? الناتج|ايه الناتج|إيه الناتج)\s*[?؟]?$", goal.strip(), re.I):
        return goal, False

    # A forward pipeline reference (e.g. "calculate 5*3 then save the result") is
    # resolvable by the planner itself; do not consume cross-turn context here.
    has_local_producer = any(k in goal.lower() for k in CALC_KW + TIME_KW)
    if ("النتيجة" in goal or re.search(r"\b(?:the\s+)?result|\boutput\b", goal, re.I)) and has_local_producer:
        return goal, False

    # Explicit cross-turn result reference. This is intentionally narrow: we do not
    # resolve arbitrary pronouns such as "it" without a clear target.
    if re.search(r"(?:save|store)\s+(?:the\s+)?(?:result|output)\s+as\s+.+", goal, re.I):
        last = world.last_outputs.get("last_result")
        if last is None:
            try:
                last = get_memory().last_completed_output(session_id=session_id)
            except Exception:
                last = None
        if isinstance(last, dict) and last.get("output") is not None:
            return re.sub(r"(?:save|store)\s+(?:the\s+)?(?:result|output)", "save the previous result", goal, count=1, flags=re.I), False
        if last is not None:
            return re.sub(r"(?:save|store)\s+(?:the\s+)?(?:result|output)", "save the previous result", goal, count=1, flags=re.I), False

    # Carry an explicit dataset target into terse follow-ups, but only from the
    # immediately completed task. Never infer a file or substitute prior context
    # when the previous goal did not name a supported data file.
    if world.last_goal and goal.lstrip().casefold().startswith(DATA_FOLLOW_UP_PREFIXES):
        previous_data = re.search(r"([\w.-]+\.(?:csv|json|sqlite3?|db))\b", world.last_goal, re.I)
        if previous_data:
            return f"{world.last_goal.rstrip(' ;')} ; {goal.strip()}", False

    # Explicit human correction after a prior fact assignment: "No, I mean Cairo"
    # becomes a new assignment on the same key; other "I mean" statements remain
    # unresolved instead of guessing.
    m = re.fullmatch(r"(?:no[, ]+)?i\s+mean\s+(.+?)\s*", goal.strip(), re.I | re.S)
    if m:
        value = m.group(1).strip(" .?!?")
        # Prefer explicit key metadata from the previous successful run. This covers
        # corrections after a question such as: "what is my city?" -> "No, I mean Cairo".
        meta = None
        if isinstance(world.last_outputs, dict):
            # Conversational correction must use the previous completed turn, not
            # the narrower "meaningful result" channel. Informational turns can
            # establish the semantic key for a later correction.
            meta = world.last_outputs.get("last_turn_meta") or world.last_outputs.get("last_result_meta")
        if isinstance(meta, dict):
            plan_steps = list((meta.get("plan") or {}).get("steps") or [])
            for step in reversed(plan_steps):
                if step.get("status") == "done" and step.get("tool") in {"recall_fact", "remember_fact"}:
                    key = (step.get("args") or {}).get("key")
                    if key and value:
                        return f"my {key} is {value}", False
        if world.last_goal:
            prev = world.last_goal
            prev_match = re.search(r"(?:^|\b)my\s+([a-zA-Z][\w -]{0,48})\s+(?:is|=)\s+(.+)$", prev, re.I | re.S)
            if prev_match and value:
                return f"my {prev_match.group(1).strip()} is {value}", False

    if any(p in goal for p in PRONOUNS):
        resolved = resolve_reference(goal, world)
        if resolved == goal and not world.last_goal and not world.last_outputs:
            return goal, True
        return resolved, False
    return goal, False
