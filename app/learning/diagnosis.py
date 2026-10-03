from __future__ import annotations
import hashlib
import re
from collections import Counter
from app.intelligence.understanding import normalize

STOP = {
    "the","and","for","with","from","then","that","this","into","about","what","please","could","would","should",
    "من","في","على","إلى","عن","ثم","و","هذا","هذه","هو","هي","لي","من فضلك","ممكن"
}


def task_signature(goal: str) -> str:
    # Never persist credentials or secret values in the reusable task-family signature.
    # Signatures are durable identifiers and therefore must be safer than raw user text.
    safe_goal = re.sub(r"(?i)(api[_-]?key|token|password|secret|private[_-]?key)\s*[:=]\s*\S+", r"\1=<redacted>", str(goal or ""))
    text = normalize(safe_goal)
    text = re.sub(r"\b\d+(?:\.\d+)?\b", "<n>", text)
    text = re.sub(r"[A-Za-z]:\\[^\s]+|/[^\s]+", "<path>", text)
    toks=[]
    for t in re.findall(r"[\w\u0600-\u06ff<>]+", text, flags=re.UNICODE):
        if t in STOP or len(t) < 2:
            continue
        if t not in toks:
            toks.append(t)
    # Collapse common paraphrases into a stable task-family token so learning evidence
    # transfers across surface wording instead of fragmenting by user phrasing.
    family_aliases = {
        "calculation": "calculate", "compute": "calculate", "computing": "calculate",
        "arithmetic": "calculate", "operation": "calculate", "operations": "calculate",
        "احسب": "calculate", "حساب": "calculate",
        "researching": "research", "investigate": "research", "investigation": "research",
    }
    toks = [family_aliases.get(t, t) for t in toks]
    normalized = []
    for token in toks:
        if token not in normalized:
            normalized.append(token)
    if "calculate" in normalized:
        numeric_placeholder = "<n>" if "<n>" in text else "<n>"
        return "calculate <n>"
    if "research" in normalized:
        return "research"
    return " ".join(normalized[:24])


def failure_class(tool: str, error: str | None) -> str:
    e=(error or "").casefold()
    if "timeout" in e or "timed out" in e: return "timeout"
    if "permission" in e or "approval" in e or "forbidden" in e or "policy" in e: return "policy"
    if "not found" in e or "no such file" in e or "does not exist" in e: return "not_found"
    if "argument" in e or "invalid" in e or "expected" in e or "syntax" in e: return "invalid_input"
    if "network" in e or "dns" in e or "http" in e or "connection" in e: return "network"
    if "verify" in e or "verification" in e or "postcondition" in e: return "verification"
    if "resource" in e or "disk" in e or "memory" in e: return "resource"
    return "execution" if error else ""


def sanitize(text: str, limit: int = 700) -> str:
    value = str(text or "")
    value = re.sub(r"(?i)(api[_-]?key|token|password|secret|private[_-]?key)\s*[:=]\s*\S+", r"\1=<redacted>", value)
    value = re.sub(r"[A-Za-z]:\\[^\n ]+", "<path>", value)
    value = re.sub(r"/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+", "<path>", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value[:limit]


def summarize_steps(state, memory) -> tuple[dict, ...]:
    out=[]
    try:
        effects = memory.effects(state.run_id)
    except Exception:
        effects=[]
    by_step={e["step_id"]: e for e in effects}
    for step in (state.plan.steps if state.plan else []):
        effect=by_step.get(step.id, {})
        out.append({
            "step": step.id,
            "tool": step.tool,
            "status": step.status,
            "verified": bool(effect.get("verified", step.status == "done")),
            "error": sanitize(step.error or effect.get("error", ""), 320),
            "attempts": step.attempts,
            "capability": step.capability,
            "depends_on": tuple(step.depends_on),
        })
    return tuple(out)


def compute_reward(state, steps: tuple[dict, ...]) -> tuple[float, float]:
    if not steps:
        return (1.0 if state.status == "completed" else 0.0, 0.0)
    verified=sum(1 for s in steps if s["verified"] and s["status"] == "done")
    done=sum(1 for s in steps if s["status"] == "done")
    failed=sum(1 for s in steps if s["status"] == "failed")
    verified_rate=verified/max(1,done)
    reward=(1.0 if state.status == "completed" else 0.0)
    reward*=0.60 + 0.40*verified_rate
    reward-=0.08*failed
    reward-=0.04*max(0, getattr(state,"replans",0))
    reward=max(0.0,min(1.0,reward))
    return round(reward,4), round(verified_rate,4)


def contrastive_lesson(current, similar):
    failures=[x for x in similar if x.status != "completed"]
    successes=[x for x in similar if x.status == "completed"]
    if not failures or not successes:
        return None
    latest_success=successes[0]
    latest_failure=failures[0]
    success_tools=[s.get("tool") for s in latest_success.steps if s.get("status") == "done"]
    failure_tools=[s.get("tool") for s in latest_failure.steps]
    if not success_tools:
        return None
    failure_class=latest_failure.failure_class or "execution"
    divergence=None
    for tool in failure_tools:
        if tool not in success_tools:
            divergence=tool
            break
    key_src=f"{current.task_signature}|{failure_class}|{divergence or 'path'}"
    key="lesson:"+hashlib.sha256(key_src.encode()).hexdigest()[:16]
    if divergence:
        text=f"When handling this task family, avoid repeating the {divergence} path after a {failure_class} failure; a verified successful path used {success_tools[0]} as the next useful action."
        avoid=(divergence,)
    else:
        text=f"A previous run failed with {failure_class}; prefer the previously verified sequence: {', '.join(success_tools[:6])}."
        # Do not blacklist a tool that is itself part of the verified successful path.
        avoid=tuple(tool for tool in failure_tools[:3] if tool not in success_tools)
    return {"key":key,"task_signature":current.task_signature,"kind":"contrastive",
            "lesson":sanitize(text),"when_to_apply":(current.task_signature,),"avoid":avoid,
            "evidence_run_ids":(latest_failure.run_id,latest_success.run_id),"confidence":0.72}
