from __future__ import annotations

import json
import os
import hmac
import hashlib
import secrets
import threading
import time
import uuid
from dataclasses import asdict, is_dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from app.api import run_agent, run_cognitive, run_brain, run_structured_goal
from app.brain.structured import validate_structured_goal
from app.identity import get_identity
from app.knowledge.memory import get_memory
from app.production.config import get_config
from app.production.rate_limit import RateLimiter
from app.production.redaction import fingerprint, redact, redact_for_log, safe_request_id

STATIC_DIR = Path(__file__).resolve().parent / "static"
DEFAULT_HOST = os.getenv("AGENT_UI_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.getenv("AGENT_UI_PORT", "8765"))
TASK_STALE_SECONDS = float(os.getenv("AGENT_UI_TASK_STALE_SECONDS", "45"))
APPROVAL_TIMEOUT_SECONDS = float(os.getenv("AGENT_UI_APPROVAL_TIMEOUT_SECONDS", "180"))
PRODUCTION = get_config()
RATE_LIMITER = RateLimiter(PRODUCTION.rate_capacity, PRODUCTION.rate_refill_per_second)


def _client_key(handler: BaseHTTPRequestHandler) -> str:
    if PRODUCTION.rate_trust_proxy:
        forwarded = str(handler.headers.get("X-Forwarded-For") or "").split(",", 1)[0].strip()
        if forwarded:
            return forwarded[:128]
    return str(handler.client_address[0] if handler.client_address else "unknown")[:128]


class ApprovalBroker:
    def __init__(self) -> None:
        self._lock = threading.Condition()

    def request(self, task_id: str, tool: str, args: dict[str, Any]) -> bool:
        deadline = time.monotonic() + APPROVAL_TIMEOUT_SECONDS
        memory = get_memory()
        memory.claim_api_approval(
            task_id=task_id, tool=tool, args=args,
            expires_at=time.time() + APPROVAL_TIMEOUT_SECONDS,
        )
        while time.monotonic() < deadline:
            row = memory.get_api_approval(task_id)
            if row and row.get("decision") is not None:
                return bool(row["decision"])
            remaining = deadline - time.monotonic()
            with self._lock:
                self._lock.wait(timeout=min(1.0, max(0.05, remaining)))
        return False

    def approve(self, task_id: str, decision: bool) -> bool:
        ok = get_memory().set_api_approval(task_id, decision)
        if ok:
            with self._lock:
                self._lock.notify_all()
        return ok

    def pending(self, task_id: str) -> dict[str, Any] | None:
        row = get_memory().get_api_approval(task_id)
        if not row or row.get("decision") is not None or float(row.get("expires_at") or 0) <= time.time():
            return None
        return {k: v for k, v in row.items() if k not in {"decision", "revision", "updated_at"}}


class TaskStore:
    """Persistent API task ledger; the local dict is only a compatibility/cache layer."""
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tasks: dict[str, dict[str, Any]] = {}

    def create(self, message: str, session_id: str, task_id: str | None = None, owner_id: str | None = None, session_token: str | None = None) -> str:
        task_id = task_id or uuid.uuid4().hex
        token_hash = hashlib.sha256(session_token.encode("utf-8")).hexdigest() if session_token else None
        task = get_memory().create_api_task(task_id=task_id, message=message, session_id=session_id, owner_id=owner_id, session_token_hash=token_hash)
        with self._lock:
            self._tasks[task_id] = dict(task)
        return task_id

    def create_idempotent(self, *, route: str, key: str, request_hash: str,
                          message: str, session_id: str, response: dict[str, Any], owner_id: str | None = None, session_token: str | None = None) -> tuple[str, dict[str, Any]]:
        task_id = str(response["task_id"])
        status, record = get_memory().create_idempotent_api_task(
            route=route, idempotency_key=key, request_hash=request_hash,
            task_id=task_id, message=message, session_id=session_id, response=response, owner_id=owner_id,
            session_token_hash=(hashlib.sha256(session_token.encode("utf-8")).hexdigest() if session_token else None),
        )
        if status == "new":
            self.get(task_id)
        return status, record

    def update(self, task_id: str, **changes: Any) -> None:
        if "error" in changes and changes["error"]:
            changes["error"] = str(redact(changes["error"]))[:1000]
        task = get_memory().update_api_task(task_id, **changes)
        if task:
            with self._lock:
                self._tasks[task_id] = dict(task)

    def heartbeat(self, task_id: str) -> None:
        task = get_memory().heartbeat_api_task(task_id)
        if task:
            with self._lock:
                self._tasks[task_id] = dict(task)

    def claim_execution(self, task_id: str, owner: str) -> bool:
        ok = get_memory().claim_api_task_lease(task_id, owner, max(PRODUCTION.task_stale_seconds * 2.0, 30.0))
        if ok:
            self.get(task_id)
        return ok

    def renew_execution(self, task_id: str, owner: str) -> bool:
        ok = get_memory().renew_api_task_lease(task_id, owner, max(PRODUCTION.task_stale_seconds * 2.0, 30.0))
        if ok:
            self.get(task_id)
        return ok

    def release_execution(self, task_id: str, owner: str) -> bool:
        ok = get_memory().release_api_task_lease(task_id, owner)
        if ok:
            self.get(task_id)
        return ok

    def execution_active(self, task_id: str, owner: str) -> bool:
        return get_memory().api_task_execution_active(task_id, owner)

    def get(self, task_id: str, owner_id: str | None = None, session_token: str | None = None) -> dict[str, Any] | None:
        token_hash = hashlib.sha256(session_token.encode("utf-8")).hexdigest() if session_token else None
        task = get_memory().get_api_task(task_id, owner_id=owner_id, session_token_hash=token_hash)
        if task:
            with self._lock:
                self._tasks[task_id] = dict(task)
            return dict(task)
        if owner_id:
            return None
        with self._lock:
            cached = self._tasks.get(task_id)
            return dict(cached) if cached else None

    def latest_for_session(self, session_id: str, owner_id: str | None = None, session_token: str | None = None) -> dict[str, Any] | None:
        token_hash = hashlib.sha256(session_token.encode("utf-8")).hexdigest() if session_token else None
        task = get_memory().latest_api_task(session_id, owner_id=owner_id, session_token_hash=token_hash)
        if task:
            with self._lock:
                self._tasks[task["task_id"]] = dict(task)
        return dict(task) if task else None

    def active_count(self) -> int:
        return get_memory().active_api_task_count()

    def stale_task(self, task: dict[str, Any]) -> dict[str, Any]:
        current = self.get(str(task.get("task_id") or "")) or task
        status = str(current.get("status") or "")
        heartbeat = float(current.get("heartbeat_at") or current.get("updated_at") or current.get("created_at") or 0)
        stale_after = min(float(TASK_STALE_SECONDS), float(PRODUCTION.task_stale_seconds))
        if status in {"queued", "running", "waiting_approval"} and heartbeat and time.time() - heartbeat > stale_after:
            self.update(current["task_id"], status="timeout", lease_owner=None, lease_expires_at=0.0,
                        error="العملية لم ترسل أي تقدم لفترة طويلة، فتم تحرير واجهة المحادثة. يمكن إعادة المحاولة.")
            return self.get(current["task_id"]) or current
        return current


BROKER = ApprovalBroker()
TASKS = TaskStore()


def _json_default(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, Path):
        return str(value)
    return str(value)


def _cognitive_summary(cognitive: Any) -> dict[str, Any]:
    """Expose compact, inspectable cognitive evidence without exposing private chain-of-thought."""
    semantic = getattr(cognitive, 'semantic', None)
    decision = getattr(cognitive, 'decision', None)
    plan = list(getattr(cognitive, 'plan', None) or [])
    trace = list(getattr(cognitive, 'trace', None) or [])
    trace_kinds = {str(event.get('kind') or '') for event in trace if isinstance(event, dict)}
    exploration = next((event for event in reversed(trace) if event.get('kind') == 'exploration_decision'), None)
    learning = next((event for event in reversed(trace) if event.get('kind') == 'learning_recorded'), None)
    prediction = next((event for event in reversed(trace) if event.get('kind') in {'prediction_scored', 'prediction_error'}), None)
    learning_payload = learning.get('learning') if isinstance(learning, dict) else None
    if not isinstance(learning_payload, dict):
        learning_payload = {}
    experience = learning_payload.get('experience') if isinstance(learning_payload.get('experience'), dict) else {}
    value_learning = learning_payload.get('value_learning') if isinstance(learning_payload.get('value_learning'), dict) else {}
    prediction_learning = learning_payload.get('prediction_error_learning') if isinstance(learning_payload.get('prediction_error_learning'), dict) else {}

    # These are operational stages backed by trace evidence, not an internal reasoning trace.
    stages = [
        ('observe', 'perception' in trace_kinds),
        ('state', 'canonical_state' in trace_kinds),
        ('retrieve', any(event.get('kind') == 'retrieval' and int(event.get('evidence_count') or 0) > 0 for event in trace if isinstance(event, dict))),
        ('predict', 'prediction_scored' in trace_kinds or 'prediction_error' in trace_kinds),
        ('explore', 'exploration_decision' in trace_kinds or any(getattr(step, 'exploration_mode', '') for step in plan)),
        ('select', 'decision' in trace_kinds),
        ('execute', 'action_observed' in trace_kinds),
        ('verify', 'step_completed' in trace_kinds or 'verification_failed' in trace_kinds),
        ('learn', 'learning_recorded' in trace_kinds),
    ]

    alternatives: list[dict[str, Any]] = []
    if exploration and isinstance(exploration.get('candidates'), (list, tuple)):
        for item in exploration.get('candidates', ())[:6]:
            if isinstance(item, dict):
                alternatives.append({
                    'tool': str(item.get('tool') or ''),
                    'score': round(float(item.get('score') or 0.0), 3),
                    'evidence_count': int(item.get('evidence_count') or 0),
                    'information_gain': round(float(item.get('information_gain') or 0.0), 3),
                    'information_value': round(float(item.get('information_value') or 0.0), 3),
                    'expected_failure_cost': round(float(item.get('expected_failure_cost') or 0.0), 3),
                })
    if not alternatives and decision is not None:
        for item in list(getattr(decision, 'candidates', ()) or ())[:6]:
            try:
                row = item.to_dict()
            except Exception:
                row = dict(item) if isinstance(item, dict) else {}
            if row:
                alternatives.append({
                    'tool': str(row.get('tool') or ''),
                    'score': round(float(row.get('score') or 0.0), 3),
                    'evidence_count': None,
                    'information_gain': None,
                    'information_value': None,
                    'expected_failure_cost': None,
                })

    evidence = []
    for item in list(getattr(cognitive, 'evidence', ()) or ())[:6]:
        try:
            row = item.to_dict()
        except Exception:
            row = dict(item) if isinstance(item, dict) else {}
        if row:
            evidence.append({
                'kind': str(row.get('kind') or ''),
                'source': str(row.get('source') or ''),
                'confidence': round(float(row.get('confidence') or 0.0), 3),
                'content': str(row.get('content') or '')[:280],
            })

    state_uncertainty = list(getattr(semantic, 'uncertainty', ()) or ()) if semantic else []
    model_uncertainty = None
    if exploration:
        model_uncertainty = float(exploration.get('model_uncertainty') or 0.0)
    elif prediction:
        model_uncertainty = float(prediction.get('uncertainty') or 0.0) if prediction.get('uncertainty') is not None else None

    return {
        'operation': str(getattr(semantic, 'requested_operation', '') or ''),
        'goal': str(getattr(getattr(cognitive, 'goal', None), 'name', '') or ''),
        'decision': str(getattr(decision, 'kind', '') or ''),
        'decision_confidence': round(float(getattr(decision, 'confidence', 0.0) or 0.0), 3) if decision else 0.0,
        'decision_rationale': str(getattr(decision, 'rationale', '') or '') if decision else '',
        'plan': [str(getattr(step, 'tool', '') or '') for step in plan[:8]],
        'planning_mode': ('exploration' if exploration or any(getattr(step, 'exploration_mode', '') for step in plan)
                          else 'model-based' if any('model-based' in str(getattr(step, 'rationale', '')).casefold() for step in plan)
                          else 'deterministic' if plan else 'none'),
        'evidence_count': len(getattr(cognitive, 'evidence', ()) or ()),
        'uncertainty_reasons': [str(x) for x in state_uncertainty[:8]],
        'model_uncertainty': round(model_uncertainty, 3) if model_uncertainty is not None else None,
        'stages': [{'name': name, 'complete': bool(complete)} for name, complete in stages],
        'alternatives': alternatives,
        'evidence': evidence,
        'exploration': {
            'mode': str(exploration.get('mode') or ''),
            'strategy': str(exploration.get('strategy') or exploration.get('mode') or ''),
            'tool': str(exploration.get('selected_tool') or ''),
            'score': round(float(exploration.get('score') or 0.0), 3),
            'information_gain': round(float(exploration.get('information_gain') or 0.0), 3),
            'information_value': round(float(exploration.get('information_value') or 0.0), 3),
            'expected_failure_cost': round(float(exploration.get('expected_failure_cost') or 0.0), 3),
            'ucb_bonus': round(float(exploration.get('ucb_bonus') or 0.0), 3),
            'novelty': round(float(exploration.get('novelty') or 0.0), 3),
            'evidence_count': int(exploration.get('evidence_count') or 0),
            'uncertainty': round(float(exploration.get('model_uncertainty') or 0.0), 3),
            'reason': str(exploration.get('reason') or ''),
        } if exploration else None,
        'prediction_error': {
            'mean_error': round(float(prediction.get('mean_error') or prediction.get('error') or 0.0), 4),
            'surprise': round(float(prediction.get('surprise') or 0.0), 4),
        } if prediction else None,
        'learning': {
            'transitions': int(learning_payload.get('transition_model_updates') or experience.get('transition_model_updates') or 0),
            'replay_indexed': int(learning_payload.get('replay_indexed') or 0),
            'state_updates': int(value_learning.get('state_updates') or 0),
            'action_updates': int(value_learning.get('action_updates') or 0),
            'prediction_scored': int(prediction_learning.get('scored_predictions') or 0),
            'self_model_updated': bool(learning.get('self_model_updated', True)) if isinstance(learning, dict) else False,
        } if learning else None,
    }


def brain_health_payload() -> dict[str, Any]:
    """Describe the canonical Brain and its retrieval-native Arabic NLP engine."""
    return {
        'configured': True,
        'mode': 'learning',
        'reasoning_engine': 'canonical-state-brain',
        'learning': True,
        'world_model': True,
        'value_model': True,
        'prediction_error': True,
        'counterfactual_simulation': True,
        'model_based_planning': True,
        'safe_exploration': True,
        'information_gain': True,
        'semantic_nlp': 'arabic-retrieval-v1.0',
    }


def serialize_state(state: Any) -> dict[str, Any]:
    """Serialize the full diagnostic state for trusted engineering/debug consumers.

    Normal chat clients must never receive this representation. Use
    :func:`serialize_public_state` for the user-facing transport boundary.
    """
    if hasattr(state, 'state') and hasattr(state, 'response'):
        cognitive = state.state
        runtime = getattr(state, 'runtime_state', None)
        return {
            'run_id': getattr(state, 'run_id', ''),
            'trace_id': '',
            'goal': cognitive.goal.to_dict() if getattr(cognitive, 'goal', None) else '',
            'status': getattr(state, 'status', 'completed'),
            'final_message': str(getattr(state, 'response', '') or ''),
            'replans': 0,
            'next_index': 0,
            'plan': [x.to_dict() for x in (getattr(cognitive, 'plan', None) or [])],
            'world': {},
            'cognitive': {
                'semantic': cognitive.semantic.to_dict() if cognitive.semantic else None,
                'decision': cognitive.decision.to_dict() if cognitive.decision else None,
                'hypotheses': [x.to_dict() for x in cognitive.hypotheses],
                'evidence': [x.to_dict() for x in cognitive.evidence],
                'revision': cognitive.revision,
                'trace': cognitive.trace[-40:],
                'summary': _cognitive_summary(cognitive),
            },
            'execution': runtime if isinstance(runtime, dict) else {},
        }
    plan = getattr(state, "plan", None)
    return {
        "run_id": getattr(state, "run_id", ""),
        "trace_id": getattr(state, "trace_id", ""),
        "goal": getattr(state, "goal", ""),
        "status": getattr(state, "status", ""),
        "final_message": getattr(state, "final_message", ""),
        "replans": getattr(state, "replans", 0),
        "next_index": getattr(state, "next_index", 0),
        "plan": plan.to_dict() if plan and hasattr(plan, "to_dict") else None,
        "world": state.world.snapshot() if getattr(state, "world", None) and hasattr(state.world, "snapshot") else {},
    }


def serialize_public_state(state: Any) -> dict[str, Any]:
    """Return only the user-facing state needed by the chat transport.

    Internal run identifiers, plans, semantic frames, evidence, traces, rationales,
    confidence values, world state, and learning diagnostics are deliberately omitted.
    """
    status = str(getattr(state, 'status', '') or '')
    response = getattr(state, 'response', None)
    if response is None:
        response = getattr(state, 'final_message', '')
    message = humanize_persisted_assistant_text(response)
    return {
        'status': status,
        'final_message': message,
    }


def _debug_ui_requested(route) -> bool:
    query = parse_qs(route.query)
    requested = query.get('debug', ['0'])[0].strip().casefold() in {'1', 'true', 'yes', 'on'}
    enabled = os.getenv('SHURY_ENABLE_DEBUG_UI', '0').strip().casefold() in {'1', 'true', 'yes', 'on'}
    return bool(requested and enabled)


def serialize_task_for_api(task: dict[str, Any], *, include_debug: bool = False) -> dict[str, Any]:
    """Project a persisted task into the public Web API contract."""
    public = {
        'task_id': str(task.get('task_id') or ''),
        'session_id': str(task.get('session_id') or ''),
        'status': str(task.get('status') or ''),
        'error': str(redact(task.get('error'))) if task.get('error') else None,
    }
    state = task.get('state')
    if isinstance(state, dict):
        public['state'] = {
            'status': str(state.get('status') or task.get('status') or ''),
            'final_message': humanize_persisted_assistant_text(state.get('final_message')),
        }
        if include_debug:
            public['debug'] = redact(state)
    elif state is not None:
        public['state'] = serialize_public_state(state)
    if include_debug:
        for key in ('run_id', 'trace_id', 'goal', 'replans', 'next_index', 'plan', 'world', 'cognitive', 'execution'):
            if key in task and key not in public:
                public['debug_' + key] = redact(task[key])
    if 'approval' in task:
        public['approval'] = task['approval']
    return public


def _use_cognitive() -> bool:
    # The browser chat is deterministic by default. Optional cognitive reasoning
    # must be an explicit deployment choice, not a hidden source of inconsistent replies.
    return os.getenv("SHURY_ENABLE_COGNITIVE_UI", "0").strip().lower() in {"1", "true", "yes", "on"}



def _task_heartbeat(task_id: str, owner: str, stop: threading.Event) -> None:
    interval = max(1.0, min(10.0, PRODUCTION.task_stale_seconds / 3.0))
    while not stop.wait(interval):
        try:
            if not TASKS.renew_execution(task_id, owner):
                stop.set()
                return
        except Exception:
            stop.set()
            return


def _run_structured_task(task_id: str, payload: dict[str, Any], session_id: str) -> None:
    owner = uuid.uuid4().hex
    if not TASKS.claim_execution(task_id, owner):
        return
    stop = threading.Event()
    threading.Thread(target=_task_heartbeat, args=(task_id, owner, stop), daemon=True).start()

    def active() -> bool:
        return TASKS.execution_active(task_id, owner)

    def approve(tool: str, args: dict[str, Any]) -> bool:
        if not active():
            return False
        TASKS.update(task_id, status="waiting_approval")
        decision = BROKER.request(task_id, tool, args)
        if not active():
            return False
        TASKS.update(task_id, status="running")
        return decision

    try:
        state = run_structured_goal(payload, approve=approve, session_id=session_id, execution_guard=active)
        if active():
            TASKS.update(task_id, status=state.status, state=serialize_state(state), error=None)
    except Exception as exc:
        if active():
            TASKS.update(task_id, status="failed", error=f"{type(exc).__name__}: {exc}")
    finally:
        stop.set()
        TASKS.release_execution(task_id, owner)


def _run_task(task_id: str, message: str, session_id: str) -> None:
    owner = uuid.uuid4().hex
    if not TASKS.claim_execution(task_id, owner):
        return
    stop = threading.Event()
    threading.Thread(target=_task_heartbeat, args=(task_id, owner, stop), daemon=True).start()

    def active() -> bool:
        return TASKS.execution_active(task_id, owner)

    def approve(tool: str, args: dict[str, Any]) -> bool:
        if not active():
            return False
        TASKS.update(task_id, status="waiting_approval")
        decision = BROKER.request(task_id, tool, args)
        if not active():
            return False
        TASKS.update(task_id, status="running")
        return decision

    try:
        if os.getenv('SHURY_USE_LEGACY_RUNTIME', '0').strip().lower() in {'1', 'true', 'yes', 'on'}:
            state = run_agent(message, approve=approve, session_id=session_id)
            guard_supported = False
        elif _use_cognitive():
            state = run_cognitive(message, approve=approve, session_id=session_id)
            guard_supported = False
        else:
            state = run_brain(message, approve=approve, session_id=session_id, execution_guard=active)
            guard_supported = True
        if active():
            TASKS.update(task_id, status=state.status, state=serialize_state(state), error=None)
        elif guard_supported:
            # The core already observed the lost lease; preserve durable timeout/cancel state.
            return
    except Exception as exc:  # UI must never take the entire process down.
        if active():
            TASKS.update(task_id, status="failed", error=f"{type(exc).__name__}: {exc}")
    finally:
        stop.set()
        TASKS.release_execution(task_id, owner)


def identity_payload() -> dict[str, Any]:
    identity = get_identity()
    return identity.to_dict()


def humanize_persisted_assistant_text(value: Any) -> str:
    """Prevent old internal task envelopes from leaking into the chat transcript."""
    if value is None:
        return ""
    if isinstance(value, dict):
        final = value.get("final_message")
        if isinstance(final, str) and final.strip():
            return final.strip()
        nested = value.get("state")
        if nested is not None:
            return humanize_persisted_assistant_text(nested)
        return str(value.get("message") or "").strip()
    text = str(value).strip()
    if not text:
        return ""
    if text.startswith("{") and text.endswith("}"):
        try:
            payload = json.loads(text)
            if isinstance(payload, dict):
                human = humanize_persisted_assistant_text(payload)
                if human:
                    return human
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
    return text


class Handler(BaseHTTPRequestHandler):
    server_version = "SHURYWeb/1.2"

    def _request_id(self) -> str:
        value = safe_request_id(self.headers.get("X-Request-ID"))
        self._shury_request_id = value
        return value

    def _session_token(self) -> str | None:
        token = str(self.headers.get("X-Session-Token") or "").strip()
        return token or None

    def _principal_id(self) -> str | None:
        if not PRODUCTION.require_auth:
            return None
        supplied = str(self.headers.get("Authorization") or "")
        if not supplied.startswith("Bearer "):
            return None
        token = supplied[7:].strip()
        return fingerprint({"authorization": token}) if token else None

    def _owns_task(self, task: dict[str, Any] | None) -> bool:
        if not PRODUCTION.require_auth:
            return task is not None
        principal = self._principal_id()
        return bool(task and principal and hmac.compare_digest(str(task.get("owner_id") or ""), principal))

    def _owns_session(self, session_id: str) -> bool:
        if not PRODUCTION.require_auth:
            return True
        principal = self._principal_id()
        session_token = self._session_token()
        if not principal or not session_token:
            return False
        token_hash = hashlib.sha256(session_token.encode("utf-8")).hexdigest()
        task = get_memory().latest_api_task(session_id, owner_id=principal, session_token_hash=token_hash)
        return bool(task)

    def _authorized(self) -> bool:
        if not PRODUCTION.require_auth:
            return True
        supplied = str(self.headers.get("Authorization") or "")
        if not supplied.startswith("Bearer "):
            return False
        token = supplied[7:].strip()
        return bool(token) and hmac.compare_digest(token, PRODUCTION.api_token)

    def _guard(self, route: str) -> bool:
        request_id = self._request_id()
        self._route = route
        self._started_at = time.monotonic()
        protected = route.startswith("/api/") or route in {"/goal", "/api/goal"}
        if protected and not self._authorized() and route != "/api/health":
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "authentication required", "request_id": request_id})
            return False
        if route in {"/api/chat", "/api/goal", "/goal", "/api/approval"}:
            decision = RATE_LIMITER.allow(_client_key(self))
            if not decision.allowed:
                self._retry_after = decision.retry_after
                self._send(HTTPStatus.TOO_MANY_REQUESTS, json.dumps({
                    "error": "rate limit exceeded", "retry_after": decision.retry_after,
                    "request_id": request_id,
                }, ensure_ascii=False).encode("utf-8"))
                return False
        return True

    def _send(self, status: int, body: bytes, content_type: str = "application/json; charset=utf-8") -> None:
        try:
            self.send_response(status)
            if status == HTTPStatus.TOO_MANY_REQUESTS:
                self.send_header("Retry-After", str(max(1, int(round(getattr(self, "_retry_after", 1.0))))))
            if status == HTTPStatus.UNAUTHORIZED:
                self.send_header("WWW-Authenticate", "Bearer")
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "SAMEORIGIN")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Request-ID", getattr(self, "_shury_request_id", safe_request_id(None)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            return

    def _json(self, status: int, payload: Any) -> None:
        if isinstance(payload, dict) and "request_id" not in payload:
            payload = {**payload, "request_id": getattr(self, "_shury_request_id", "")}
        self._send(status, json.dumps(payload, ensure_ascii=False, default=_json_default).encode("utf-8"))
        try:
            duration_ms = (time.monotonic() - float(getattr(self, "_started_at", time.monotonic()))) * 1000.0
            get_memory().record_event("api_request", {
                "request_id": getattr(self, "_shury_request_id", ""),
                "route": getattr(self, "_route", urlparse(self.path).path),
                "status": int(status), "duration_ms": round(duration_ms, 3),
                "client": _client_key(self),
            })
        except Exception:
            pass

    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid Content-Length") from exc
        if length < 0 or length > PRODUCTION.max_json_bytes:
            raise ValueError("request too large")
        content_type = str(self.headers.get("Content-Type", ""))
        if content_type and not content_type.casefold().startswith("application/json"):
            raise ValueError("Content-Type must be application/json")
        raw = self.rfile.read(length)
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object")
        return data

    def _idempotency_key(self) -> str | None:
        raw = str(self.headers.get("Idempotency-Key") or self.headers.get("X-Idempotency-Key") or "").strip()
        if not raw:
            return None
        if len(raw) > PRODUCTION.max_idempotency_key_chars or not all(ch.isalnum() or ch in "._:-" for ch in raw):
            raise ValueError("invalid idempotency key")
        return raw

    def do_GET(self) -> None:  # noqa: N802
        route = urlparse(self.path)
        if not self._guard(route.path):
            return
        if route.path == "/":
            index = (STATIC_DIR / "index.html").read_bytes()
            self._send(HTTPStatus.OK, index, "text/html; charset=utf-8")
            return
        if route.path == "/static/styles.css":
            self._send(HTTPStatus.OK, (STATIC_DIR / "styles.css").read_bytes(), "text/css; charset=utf-8")
            return
        if route.path == "/static/app.js":
            self._send(HTTPStatus.OK, (STATIC_DIR / "app.js").read_bytes(), "application/javascript; charset=utf-8")
            return
        if route.path == "/api/identity":
            self._json(HTTPStatus.OK, identity_payload())
            return
        if route.path == "/api/health":
            from app.intelligence.semantic.retrieval import model_status
            self._json(HTTPStatus.OK, {
                "ok": True,
                "brain": {**brain_health_payload(), "semantic_model": model_status(), "structured_goal": True},
                "active_tasks": TASKS.active_count(),
                "production": {
                    "auth_required": PRODUCTION.require_auth,
                    "rate_limit": {"capacity": PRODUCTION.rate_capacity, "refill_per_second": PRODUCTION.rate_refill_per_second},
                    "task_lease": {"stale_seconds": PRODUCTION.task_stale_seconds, "lease_seconds": max(PRODUCTION.task_stale_seconds * 2.0, 30.0)},
                },
            })
            return
        if route.path == "/api/session":
            session_id = parse_qs(route.query).get("session_id", [""])[0].strip()
            if not session_id:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "session_id is required"})
                return
            episodes = get_memory().recent_episodes(session_id=session_id, limit=40)
            for episode in episodes:
                if isinstance(episode, dict) and "assistant_text" in episode:
                    episode["assistant_text"] = humanize_persisted_assistant_text(episode.get("assistant_text"))
            if not self._owns_session(session_id):
                self._json(HTTPStatus.FORBIDDEN, {"error": "session access denied"})
                return
            latest = TASKS.latest_for_session(session_id, owner_id=self._principal_id(), session_token=self._session_token())
            if latest:
                latest = TASKS.stale_task(latest)
                latest = serialize_task_for_api(latest, include_debug=_debug_ui_requested(route))
            self._json(HTTPStatus.OK, {"session_id": session_id, "episodes": episodes, "latest_task": latest})
            return
        if route.path == "/api/tasks":
            query = parse_qs(route.query)
            task_id = query.get("id", [""])[0].strip()
            session_id = query.get("session_id", [""])[0].strip()
            if task_id:
                if PRODUCTION.require_auth and not self._session_token():
                    self._json(HTTPStatus.FORBIDDEN, {"error": "session capability required"})
                    return
                task = TASKS.get(task_id, owner_id=self._principal_id(), session_token=self._session_token())
                if not task:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "task not found"})
                    return
                task = TASKS.stale_task(task)
                pending = BROKER.pending(task_id)
                if pending:
                    task["approval"] = {k: v for k, v in pending.items() if k != "decision"}
                self._json(HTTPStatus.OK, serialize_task_for_api(task, include_debug=_debug_ui_requested(route)))
                return
            if session_id:
                if not self._owns_session(session_id):
                    self._json(HTTPStatus.FORBIDDEN, {"error": "session access denied"})
                    return
                latest = TASKS.latest_for_session(session_id, owner_id=self._principal_id(), session_token=self._session_token())
                if latest:
                    latest = TASKS.stale_task(latest)
                    latest = serialize_task_for_api(latest, include_debug=_debug_ui_requested(route))
                self._json(HTTPStatus.OK, {"latest": latest})
                return
            self._json(HTTPStatus.BAD_REQUEST, {"error": "id or session_id is required"})
            return
        if route.path == "/api/memory":
            query_params = parse_qs(route.query)
            query = query_params.get("q", [""])[0].strip()
            memory_session = query_params.get("session_id", [""])[0].strip()
            if PRODUCTION.require_auth and not self._owns_session(memory_session):
                self._json(HTTPStatus.FORBIDDEN, {"error": "session access denied"})
                return
            if not query:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "q is required"})
                return
            self._json(HTTPStatus.OK, get_memory().recall_context(query, limit=8))
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        route = urlparse(self.path)
        if not self._guard(route.path):
            return
        try:
            data = self._read_json()
        except Exception as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return

        if route.path in {"/goal", "/api/goal"}:
            try:
                validate_structured_goal(data)
            except Exception as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            supplied_session = str(data.get("session_id", "")).strip()
            session_id = supplied_session or uuid.uuid4().hex
            principal_id = self._principal_id()
            session_token = self._session_token() if supplied_session else secrets.token_urlsafe(32)
            if supplied_session and PRODUCTION.require_auth and not self._owns_session(supplied_session):
                if get_memory().latest_api_task(supplied_session) is not None:
                    self._json(HTTPStatus.FORBIDDEN, {"error": "session access denied"})
                    return
            idem_key = self._idempotency_key()
            response = {"task_id": uuid.uuid4().hex, "session_id": session_id, "session_token": session_token, "mode": "structured", "semantic_model": "arabic-retrieval-v1.0"}
            if idem_key:
                request_payload = {k: v for k, v in data.items() if k != "session_id"}
                if supplied_session:
                    request_payload["session_id"] = supplied_session
                request_hash = fingerprint({"route": route.path, "payload": request_payload})
                status, record = TASKS.create_idempotent(
                    route=route.path, key=idem_key, request_hash=request_hash,
                    message=json.dumps(data, ensure_ascii=False), session_id=session_id, response=response, owner_id=principal_id, session_token=session_token,
                )
                if status == "forbidden":
                    self._json(HTTPStatus.FORBIDDEN, {"error": "idempotency key owner mismatch"})
                    return
                if status == "conflict":
                    self._json(HTTPStatus.CONFLICT, {"error": "idempotency key reused with a different request"})
                    return
                if status == "replay":
                    self._json(HTTPStatus.ACCEPTED, {**record["response"], "idempotent_replay": True})
                    return
                task_id = response["task_id"]
            else:
                task_id = TASKS.create(json.dumps(data, ensure_ascii=False), session_id, task_id=response["task_id"], owner_id=principal_id, session_token=session_token)
            threading.Thread(target=_run_structured_task, args=(task_id, data, session_id), daemon=True).start()
            self._json(HTTPStatus.ACCEPTED, response)
            return

        if route.path == "/api/chat":
            message = str(data.get("message", "")).strip()
            supplied_session = str(data.get("session_id", "")).strip()
            session_id = supplied_session or uuid.uuid4().hex
            principal_id = self._principal_id()
            session_token = self._session_token() if supplied_session else secrets.token_urlsafe(32)
            if supplied_session and PRODUCTION.require_auth and not self._owns_session(supplied_session):
                if get_memory().latest_api_task(supplied_session) is not None:
                    self._json(HTTPStatus.FORBIDDEN, {"error": "session access denied"})
                    return
            if not message:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "message is required"})
                return
            if len(message) > PRODUCTION.max_chat_chars:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "message too long"})
                return
            idem_key = self._idempotency_key()
            response = {"task_id": uuid.uuid4().hex, "session_id": session_id, "session_token": session_token}
            if idem_key:
                request_payload = {"message": message}
                if supplied_session:
                    request_payload["session_id"] = supplied_session
                request_hash = fingerprint({"route": route.path, "payload": request_payload})
                status, record = TASKS.create_idempotent(
                    route=route.path, key=idem_key, request_hash=request_hash,
                    message=message, session_id=session_id, response=response, owner_id=principal_id, session_token=session_token,
                )
                if status == "forbidden":
                    self._json(HTTPStatus.FORBIDDEN, {"error": "idempotency key owner mismatch"})
                    return
                if status == "conflict":
                    self._json(HTTPStatus.CONFLICT, {"error": "idempotency key reused with a different request"})
                    return
                if status == "replay":
                    self._json(HTTPStatus.ACCEPTED, {**record["response"], "idempotent_replay": True})
                    return
                task_id = response["task_id"]
            else:
                task_id = TASKS.create(message, session_id, task_id=response["task_id"], owner_id=principal_id, session_token=session_token)
            threading.Thread(target=_run_task, args=(task_id, message, session_id), daemon=True).start()
            self._json(HTTPStatus.ACCEPTED, response)
            return

        if route.path == "/api/approval":
            task_id = str(data.get("task_id", "")).strip()
            decision = data.get("approved")
            if not task_id or not isinstance(decision, bool):
                self._json(HTTPStatus.BAD_REQUEST, {"error": "task_id and approved boolean are required"})
                return
            task = TASKS.get(task_id, owner_id=self._principal_id(), session_token=self._session_token())
            if not task:
                self._json(HTTPStatus.FORBIDDEN, {"error": "task access denied"})
                return
            ok = BROKER.approve(task_id, decision)
            self._json(HTTPStatus.OK if ok else HTTPStatus.NOT_FOUND, {"ok": ok})
            return

        self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def log_message(self, fmt: str, *args: Any) -> None:
        return


def create_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), Handler)


def main() -> None:
    host, port = DEFAULT_HOST, DEFAULT_PORT
    server = create_server(host, port)
    identity = get_identity()
    print(f"{identity.name} — browser UI running at http://{host}:{port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping SHURY.")
    finally:
        server.server_close()


__all__ = ["create_server", "main", "serialize_state", "identity_payload"]
