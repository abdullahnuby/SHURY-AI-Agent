#!/usr/bin/env python3
"""Run pytest files independently and emit a deterministic summary.

This avoids conflating per-suite runtime/fixture state and makes slow legacy suites
observable without treating a single aggregate timeout as a failed application test.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tests", nargs="+", help="pytest file/path values")
    parser.add_argument("--timeout", type=float, default=90.0, help="per-file timeout in seconds")
    parser.add_argument("--skip-ruff", action="store_true", help="skip the mandatory F821 ruff gate")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)

    if not args.skip_ruff:
        try:
            ruff = subprocess.run(
                ["ruff", "check", "--select", "F821", "app/"],
                cwd=root, env=env, text=True, capture_output=True,
            )
        except FileNotFoundError:
            ruff_payload = {
                "gate": "ruff F821",
                "command": "ruff check --select F821 app/",
                "status": "tool_missing",
                "exit_code": None,
                "stdout": "",
                "stderr": "ruff executable is not installed in the current environment",
            }
            print(json.dumps({"ruff": ruff_payload}, ensure_ascii=False, indent=2))
            return 1
        ruff_payload = {
            "gate": "ruff F821",
            "command": "ruff check --select F821 app/",
            "status": "passed" if ruff.returncode == 0 else "failed",
            "exit_code": ruff.returncode,
            "stdout": ruff.stdout[-12000:],
            "stderr": ruff.stderr[-4000:],
        }
        print(json.dumps({"ruff": ruff_payload}, ensure_ascii=False, indent=2))
        if ruff.returncode != 0:
            return 1
    env["PYTHONPATH"] = str(root) + os.pathsep + env.get("PYTHONPATH", "")

    results: list[dict[str, object]] = []
    for raw in args.tests:
        started = time.monotonic()
        command = [sys.executable, "-m", "pytest", "-q", raw]
        try:
            completed = subprocess.run(
                command,
                cwd=root,
                env=env,
                text=True,
                capture_output=True,
                timeout=args.timeout,
            )
            result = {
                "test_file": raw,
                "status": "passed" if completed.returncode == 0 else "failed",
                "exit_code": completed.returncode,
                "duration_seconds": round(time.monotonic() - started, 3),
                "stdout": completed.stdout[-12000:],
                "stderr": completed.stderr[-4000:],
            }
        except subprocess.TimeoutExpired as exc:
            result = {
                "test_file": raw,
                "status": "timeout",
                "exit_code": None,
                "duration_seconds": round(time.monotonic() - started, 3),
                "stdout": _text(exc.stdout)[-12000:],
                "stderr": _text(exc.stderr)[-4000:],
            }
        results.append(result)

    passed = sum(1 for item in results if item["status"] == "passed")
    failed = sum(1 for item in results if item["status"] == "failed")
    timeouts = sum(1 for item in results if item["status"] == "timeout")
    summary = {
        "root": str(root),
        "timeout_seconds": args.timeout,
        "files": len(results),
        "passed": passed,
        "failed": failed,
        "timeouts": timeouts,
        "results": results,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if failed == 0 and timeouts == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
