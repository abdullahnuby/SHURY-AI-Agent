from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from app.brain.kernel import CognitiveKernel
from app.intelligence.semantic.retrieval import MODEL_NAME, model_status
from app.knowledge.memory import Memory
from app.learning.store import LearningStore
from app.brain.store import BrainStateStore
from app.runtime.registry import load_tools
from app.evaluation.oracle import DeterministicEvaluationOracle


class Phase12EnvironmentBlocked(RuntimeError):
    """Raised when required production dependencies make a real run impossible."""


@dataclass(frozen=True)
class ConversationExecution:
    conversation_id: str
    seed: int
    session_id: str
    passed: bool
    turn_count: int
    trace_events: int
    status: str
    result_path: str
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "conversation_id": self.conversation_id,
            "seed": self.seed,
            "session_id": self.session_id,
            "passed": self.passed,
            "turn_count": self.turn_count,
            "trace_events": self.trace_events,
            "status": self.status,
            "result_path": self.result_path,
            "error": self.error,
        }


def load_dialogues(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, 1):
            text = raw.strip()
            if not text:
                continue
            try:
                value = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid dialogue JSON at line {line_number}: {exc}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"dialogue line {line_number} is not an object")
            rows.append(value)
    return rows


class RealDialogueRunner:
    """Execute generated dialogues through the canonical production Brain runtime.

    Each conversation receives separate SQLite state for user memory, cognitive/learning
    state, research memory, RAG, network provenance/cache, and skills. The runner refuses
    to execute at all unless Arabic-Retrieval-v1.0 is actually loaded, preventing a
    deterministic fallback from being misclassified as a real-model execution.
    """

    def __init__(
        self,
        corpus_path: str | Path,
        output_dir: str | Path,
        *,
        max_steps: int = 8,
        timeout_per_turn: float = 120.0,
    ):
        self.corpus_path = Path(corpus_path)
        self.output_dir = Path(output_dir)
        self.max_steps = int(max_steps)
        self.timeout_per_turn = float(timeout_per_turn)
        self.oracle = DeterministicEvaluationOracle()

    def preflight(self) -> dict[str, Any]:
        original_mode = os.getenv("SHURY_NLP_MODE")
        os.environ["SHURY_NLP_MODE"] = "required"
        try:
            try:
                status = model_status()
            except Exception as exc:
                raise Phase12EnvironmentBlocked(
                    f"{MODEL_NAME} could not be loaded: {type(exc).__name__}: {exc}"
                ) from exc
            if not status.get("loaded"):
                raise Phase12EnvironmentBlocked(
                    f"{MODEL_NAME} is not loaded; production execution is forbidden without the real model"
                )
            return status
        finally:
            if original_mode is None:
                os.environ.pop("SHURY_NLP_MODE", None)
            else:
                os.environ["SHURY_NLP_MODE"] = original_mode

    @staticmethod
    def _session_token(conversation_id: str, seed: int) -> str:
        return hashlib.sha256(f"{conversation_id}:{seed}".encode("utf-8")).hexdigest()[:24]

    @contextmanager
    def _isolated_environment(self, root: Path):
        keys = (
            "AGENT_LEARNING_DB", "AGENT_SKILLS_DB", "AGENT_RAG_DB", "AGENT_RESEARCH_DB",
            "AGENT_NETWORK_DB", "AGENT_NETWORK_CACHE", "SHURY_NLP_MODE",
        )
        saved = {key: os.environ.get(key) for key in keys}
        os.environ["AGENT_LEARNING_DB"] = str(root / "learning.db")
        os.environ["AGENT_SKILLS_DB"] = str(root / "skills.db")
        os.environ["AGENT_RAG_DB"] = str(root / "rag.db")
        os.environ["AGENT_RESEARCH_DB"] = str(root / "research.db")
        os.environ["AGENT_NETWORK_DB"] = str(root / "network.db")
        os.environ["AGENT_NETWORK_CACHE"] = str(root / "network_cache")
        os.environ["SHURY_NLP_MODE"] = "required"
        try:
            yield
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    @staticmethod
    def _approve(_tool: str, _args: dict[str, Any]) -> bool:
        return True

    def _run_conversation(self, dialogue: Mapping[str, Any], root: Path) -> ConversationExecution:
        conversation_id = str(dialogue["conversation_id"])
        seed = int(dialogue.get("seed", 0))
        session_id = f"phase12-{self._session_token(conversation_id, seed)}"
        root.mkdir(parents=True, exist_ok=True)
        conversation_dir = root / conversation_id
        conversation_dir.mkdir(parents=True, exist_ok=False)
        trace_path = conversation_dir / "trace.json"

        actual_turns: list[dict[str, Any]] = []
        trace_records: list[dict[str, Any]] = []
        status = "completed"
        error = ""

        # Every conversation receives separate durable stores for memory, learning, RAG,
        # research, and network provenance/cache. Tool definitions remain shared, but their
        # stateful backends resolve from this conversation-local environment.
        with self._isolated_environment(conversation_dir):
            memory = Memory(conversation_dir / "memory.db")
            learning = LearningStore(conversation_dir / "learning.db")
            state_store = BrainStateStore(conversation_dir / "learning.db")
            registry = load_tools()
            kernel = CognitiveKernel(memory=memory, registry=registry, state_store=state_store, experience_store=learning)

            for turn in dialogue.get("turns", []):
                text = str(turn.get("text") or "")
                started = time.monotonic()
                try:
                    result = kernel.act(text, approve=self._approve, session_id=session_id, max_steps=self.max_steps)
                    elapsed = time.monotonic() - started
                    if elapsed > self.timeout_per_turn:
                        raise TimeoutError(f"turn exceeded {self.timeout_per_turn:.1f}s")
                    state = result.state
                    trace_records.append({
                        "turn_id": int(turn.get("turn_id", len(trace_records) + 1)),
                        "input": text,
                        "elapsed_ms": round(elapsed * 1000, 3),
                        "run_id": result.run_id,
                        "status": result.status,
                        "response": result.response,
                        "trace": list(state.trace),
                        "state": state.to_dict(),
                        "runtime_state": result.runtime_state,
                    })
                    actual_turns.append({
                        "conversation_class": str(getattr(state.semantic, "conversation_class", "") or ""),
                        "intent": str(getattr(state.semantic, "requested_operation", "") or ""),
                        "slots": dict(getattr(state.semantic, "slots", ()) or ()),
                        "entities": [{"text": x, "type": y, "normalized": x} for x, y in (getattr(state.semantic, "entities", ()) or ())],
                        "reference": None,
                        "memory_actions": [],
                        "tool": str(getattr(state.decision, "tool", "") or "") or None,
                        "clarification": bool(getattr(state.decision, "kind", "") == "clarify" or getattr(state.semantic, "uncertainty", ())),
                        "decision_kind": str(getattr(state.decision, "kind", "") or ""),
                        "response": result.response,
                    })
                except Exception as exc:
                    status = "failed"
                    error = f"turn {turn.get('turn_id')}: {type(exc).__name__}: {exc}"
                    trace_records.append({"turn_id": turn.get("turn_id"), "input": text, "error": error})
                    break

            final_state = self.oracle.capture_final_state(memory, actual_turns)
            comparison = self.oracle.compare_conversation(dialogue, actual_turns, final_state) if not error else {
                "conversation_id": conversation_id,
                "passed": False,
                "turn_count_expected": len(dialogue.get("turns", [])),
                "turn_count_actual": len(actual_turns),
                "turn_count_match": False,
                "turns": [],
                "final_state": {},
                "execution_error": error,
            }
            model_info = model_status()

        payload = {
            "conversation": dialogue,
            "execution": {
                "conversation_id": conversation_id,
                "seed": seed,
                "session_id": session_id,
                "status": status,
                "error": error,
                "model": MODEL_NAME,
                "model_status": model_info,
                "turns_executed": len(actual_turns),
                "trace_events": sum(len(x.get("trace", [])) for x in trace_records),
                "isolated_state_dir": str(conversation_dir),
            },
            "trace_records": trace_records,
            "oracle": comparison,
        }
        trace_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return ConversationExecution(
            conversation_id=conversation_id,
            seed=seed,
            session_id=session_id,
            passed=bool(comparison.get("passed")) if isinstance(comparison, Mapping) else False,
            turn_count=len(actual_turns),
            trace_events=sum(len(x.get("trace", [])) for x in trace_records),
            status=status,
            result_path=str(trace_path),
            error=error,
        )

    def run(self, *, limit: int | None = None) -> dict[str, Any]:
        model = self.preflight()
        dialogues = load_dialogues(self.corpus_path)
        if limit is not None:
            dialogues = dialogues[: max(0, int(limit))]
        self.output_dir.mkdir(parents=True, exist_ok=True)
        results_path = self.output_dir / "results.jsonl"
        root = Path(tempfile.mkdtemp(prefix="shury-phase12-", dir=self.output_dir))
        executions: list[ConversationExecution] = []
        started = time.monotonic()
        conversations_root = root / "conversations"
        conversations_root.mkdir(parents=True, exist_ok=True)
        for dialogue in dialogues:
            executions.append(self._run_conversation(dialogue, conversations_root))
        with results_path.open("w", encoding="utf-8") as handle:
            for item in executions:
                handle.write(json.dumps(item.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")
        summary = {
            "runner_version": "shury.phase12.real-runtime.v1",
            "model": MODEL_NAME,
            "model_preflight": model,
            "corpus": str(self.corpus_path),
            "requested_sessions": len(dialogues),
            "executed_sessions": len(executions),
            "passed_sessions": sum(1 for item in executions if item.passed),
            "failed_sessions": sum(1 for item in executions if not item.passed),
            "turns_executed": sum(item.turn_count for item in executions),
            "trace_events": sum(item.trace_events for item in executions),
            "unique_session_ids": len({item.session_id for item in executions}),
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "results_path": str(results_path),
            "conversation_root": str(root / "conversations"),
            "gate12_execution_complete": len(executions) == len(dialogues) == 1000,
        }
        (self.output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        return summary


__all__ = ["Phase12EnvironmentBlocked", "RealDialogueRunner", "ConversationExecution", "load_dialogues"]
