# SHURY Company 3 — Release Report

## Release

`24.0.0-alpha1-company3`

Baseline: the final clean ZIP supplied by the project owner. This release applies Company Organization Core v1 directly to that baseline.

## Implemented

- Structured organization registry for departments, roles, capabilities, effects, reviewers and authority.
- Evidence-based ownership resolution with fail-closed routing.
- Specialist selection from structured organizational metadata.
- Typed `CompanyTask`, `CompanyHandoff`, and `CompanyCoordination` contracts.
- Company coordination persisted into canonical Brain state and trace.
- Canonical execution authorization gate checks the current step's organization assignment before the tool executes.
- Replanning re-routes company ownership for the current plan.
- Tool organizational metadata exposed in the runtime tool manifest.
- V27 CSV sales workflow preserved, while report creation is owned by Data and file movement by Operations.
- Independent QA and Security reviewer roles remain separate from producers.
- No LLM fallback was added. `Arabic-Retrieval-v1.0` remains the required semantic retrieval model for the production NLP path.

## Verification

- Organization + Company targeted regressions: **36/36 PASS**
- `python -m compileall -q app`: **PASS**
- Canonical structured Brain smoke: **PASS**
- Company snapshot validation: **valid**
- Unknown capability: **fails closed**
- Cross-department dependencies: explicit handoff objects
- Tampered company assignment: blocked before tool execution
- Final release contains no generated Python bytecode, pytest cache, runtime SQLite databases, or application logs.

## Important environment limitation

The validation container used for static and tool-level checks does not include `sentence-transformers`. Therefore a full Arabic-Retrieval end-to-end `run_agent()` claim is not made here. The Windows runtime remains the authoritative NLP/runtime environment for that path.

## Architecture direction

This release is the first Company architecture step, not the final 15+ department organization. The next stages are executive goal decomposition, isolated department contexts, coordination scheduling, organizational memory, metacognitive delegation, governance gates, and multi-horizon Company evaluation.
