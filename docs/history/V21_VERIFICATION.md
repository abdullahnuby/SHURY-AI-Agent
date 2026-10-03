# V21 Verification

Date: 2026-09-29

## Full regression

**152 passed, 0 failed** via `pytest -q`.

V20's earlier 150-test baseline remains green; V21 adds two test assertions in `tests/test_v21.py` and expands the V21 benchmark to **9/9**.

## V21 benchmark

- `discover_skill_md` — discover actual SKILL.md metadata from GitHub-shaped sources.
- `materialize_and_validate` — bounded package download and schema validation.
- `external_quarantine` — remote skill enters SkillBank as quarantined.
- `workflow_bounded` — only registry-known machine-readable workflow steps are executable.
- `durable_manifest` — external skill provenance survives process boundaries.
- `refresh_provenance` — upstream refresh compares content hashes.
- `security_gate` — destructive command patterns are detected.
- `failure_to_skill_candidate` — runtime failure distillation creates a descriptive candidate without a workflow.
- `progressive_skill_routing` — remote skills are routed by area/family before full package use.

## Tool contract checks

V21 registers 8 new skill-supply/evolution tools. Trust promotion is the only new high-risk skill operation and requires explicit approval.

## Runtime/network note

The production `NetworkGateway` contains bounded public HTTP(S), GitHub, arXiv, SSRF, redirect, robots and rate-limit controls. A live outbound network check from the execution sandbox is not treated as proof because the sandbox may block DNS/network access; GitHub research for this implementation was independently verified through the connected GitHub integration and current web sources.
