from __future__ import annotations

import gc
import importlib
import json
import os
import statistics
import time
import tracemalloc
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

MODEL_NAME = "omarelshehy/Arabic-Retrieval-v1.0"


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(0, min(len(ordered) - 1, int(round((pct / 100.0) * (len(ordered) - 1)))))
    return float(ordered[rank])


def measure_model_preflight() -> dict[str, Any]:
    retrieval = importlib.import_module("app.intelligence.semantic.retrieval")
    previous = os.environ.get("SHURY_NLP_MODE")
    os.environ["SHURY_NLP_MODE"] = "required"
    retrieval._model = None
    retrieval._load_error = None
    started = time.perf_counter()
    try:
        retrieval.get_model()
        cold_ms = (time.perf_counter() - started) * 1000.0
        return {"status": "available", "model": MODEL_NAME, "cold_load_ms": cold_ms}
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return {
            "status": "blocked",
            "model": MODEL_NAME,
            "cold_load_ms": None,
            "preflight_failure_ms": elapsed_ms,
            "error": f"{type(exc).__name__}: {exc}",
        }
    finally:
        if previous is None:
            os.environ.pop("SHURY_NLP_MODE", None)
        else:
            os.environ["SHURY_NLP_MODE"] = previous


def measure_with_real_model() -> dict[str, Any]:
    retrieval = importlib.import_module("app.intelligence.semantic.retrieval")
    previous = os.environ.get("SHURY_NLP_MODE")
    os.environ["SHURY_NLP_MODE"] = "required"
    try:
        retrieval._model = None
        retrieval._load_error = None
        cold_started = time.perf_counter()
        model = retrieval.get_model()
        cold_ms = (time.perf_counter() - cold_started) * 1000.0
        if model is None:
            raise RuntimeError("real model returned no instance")

        warm_samples: list[float] = []
        embedding_samples: list[float] = []
        for _ in range(20):
            started = time.perf_counter()
            retrieval.get_model()
            warm_samples.append((time.perf_counter() - started) * 1000.0)

            started = time.perf_counter()
            retrieval.encode_queries(["measure Arabic retrieval performance"])
            embedding_samples.append((time.perf_counter() - started) * 1000.0)

        return {
            "status": "available",
            "model": MODEL_NAME,
            "cold_load_ms": cold_ms,
            "warm_get_model_ms": {
                "n": len(warm_samples),
                "mean": statistics.mean(warm_samples),
                "p95": _percentile(warm_samples, 95),
                "max": max(warm_samples),
            },
            "embedding_ms": {
                "n": len(embedding_samples),
                "mean": statistics.mean(embedding_samples),
                "p95": _percentile(embedding_samples, 95),
                "max": max(embedding_samples),
            },
            "same_model_identity": all(retrieval.get_model() is model for _ in range(10)),
        }
    finally:
        if previous is None:
            os.environ.pop("SHURY_NLP_MODE", None)
        else:
            os.environ["SHURY_NLP_MODE"] = previous


def measure_rag_and_e2e_diagnostics() -> dict[str, Any]:
    # These diagnostics are explicitly non-production when the required model is unavailable.
    output: dict[str, Any] = {}
    with TemporaryDirectory(prefix="shury-phase21-") as tmp:
        from app.knowledge.rag import RAGEngine

        src = Path("app/data/rag.db")
        rag_db = Path(tmp) / "rag.db"
        rag_db.write_bytes(src.read_bytes())
        os.environ["AGENT_RAG_DB"] = str(rag_db)
        try:
            try:
                rag = RAGEngine(rag_db)
                samples: list[float] = []
                for _ in range(10):
                    started = time.perf_counter()
                    rag.query("project logistics", top_k=5, max_hops=1)
                    samples.append((time.perf_counter() - started) * 1000.0)
                output["rag"] = {
                    "status": "available",
                    "n": len(samples),
                    "mean_ms": statistics.mean(samples),
                    "p95_ms": _percentile(samples, 95),
                    "max_ms": max(samples),
                }
            except Exception as exc:
                output["rag"] = {
                    "status": "blocked",
                    "error": f"{type(exc).__name__}: {exc}",
                }

            previous = os.environ.get("SHURY_NLP_MODE")
            os.environ["SHURY_NLP_MODE"] = "off"
            from app.api import run_brain
            samples = []
            tracemalloc.start()
            for idx in range(5):
                started = time.perf_counter()
                run_brain("calculate 20*5", session_id=f"phase21-diagnostic-{idx}")
                samples.append((time.perf_counter() - started) * 1000.0)
            current, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            output["e2e_off_mode_diagnostic"] = {
                "status": "diagnostic_only",
                "n": len(samples),
                "mean_ms": statistics.mean(samples),
                "p95_ms": _percentile(samples, 95),
                "max_ms": max(samples),
                "tracemalloc_current_bytes": current,
                "tracemalloc_peak_bytes": peak,
            }
            if previous is None:
                os.environ.pop("SHURY_NLP_MODE", None)
            else:
                os.environ["SHURY_NLP_MODE"] = previous
        finally:
            os.environ.pop("AGENT_RAG_DB", None)
            gc.collect()
    return output


def collect() -> dict[str, Any]:
    result: dict[str, Any] = {
        "phase": 21,
        "model": MODEL_NAME,
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    preflight = measure_model_preflight()
    result["model_preflight"] = preflight
    if preflight["status"] == "available":
        result["real_model"] = measure_with_real_model()
    else:
        result["real_model"] = {
            "status": "blocked",
            "reason": preflight["error"],
            "cold_load_ms": None,
            "warm_inference_ms": None,
            "embedding_ms": None,
            "embedding_p95_ms": None,
        }
    result["diagnostics"] = measure_rag_and_e2e_diagnostics()
    result["gate"] = {
        "real_measurements_complete": result["real_model"]["status"] == "available",
        "model_loaded_once_and_cached": (
            result["real_model"].get("same_model_identity") is True
            if result["real_model"]["status"] == "available"
            else None
        ),
    }
    return result


if __name__ == "__main__":
    print(json.dumps(collect(), ensure_ascii=False, indent=2))
