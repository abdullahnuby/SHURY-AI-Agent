# SHURY Company C18 Release

Version: `25.7.0-alpha1-company21`
Base: `25.6.0-alpha1-company20`

C18 — Adaptive Delegation & Load-Aware Routing is complete.

The Company now has a reusable deterministic routing controller that ranks already-qualified candidates using structured capability fit, canonical verified delegation evidence, current active task load from the canonical Company portfolio, declared risk, and cost. It cannot create qualification, rewrite ownership, grant authority, or bypass review.

Company Recovery reuses the controller only after its existing same-capability, verified-evidence, compatible-argument eligibility checks. Governance/context/dependency failures remain escalation-only.

Operational inspection is exposed through `/company-routing <capability>` and has no execution authority.

## Verification
- Company suite: `125/125 passed` in two groups (`64 passed in 21.02s`; `61 passed in 15.54s`)
- Combined core/lifecycle/C15/C16/C17/C18 gate: `47 passed in 15.30s`
- Focused C18/adjacent regression: `23 passed in 11.02s`
- source compile: `SOURCE_COMPILE_PASS`
- runtime DB artifacts: `APP_DATA_DB_CLEAN`
- package integrity: `ZIP_TEST_PASS`
