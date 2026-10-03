# SHURY Phase 14 — Production Hardening Result

Phase 14 hardens the existing online boundary while preserving the SHURY cognitive architecture.

## Production controls

The HTTP/API layer now has optional bearer authentication, bounded request bodies, input length limits, request IDs, security response headers, 429 retry guidance, and token-bucket rate limiting.

API task state is persistent in the existing `Memory` database. Idempotency keys are claimed atomically with task creation, so a retry with the same request cannot create a second task. Reusing the same key with a different request fingerprint is rejected.

Long-running tasks use a durable execution lease. Only the lease owner may renew execution state. A stale task releases the lease and the canonical Brain receives an execution guard that stops additional actions after lease loss. This prevents an old worker from silently continuing into a second execution after the UI has timed it out.

Approval state is durable and can be observed across API processes. Approval arguments are redacted before persistence.

## LLM gateway resilience

The existing provider abstraction remains intact. The production wrapper adds:

- transient-error retry with bounded exponential backoff;
- provider-side token-bucket rate limiting;
- circuit breaker with cooldown and a single half-open probe;
- optional exact-request structured-output caching, disabled by default;
- provider health counters and circuit state;
- safe provider request/success/failure telemetry without prompt or secret logging.

The wrapper does not select tools, execute actions, or decide success. Structured output still returns into the existing validation and SHURY planning path.

## Telemetry and secret handling

Durable event payloads and runtime audit events are recursively redacted. Secret-like keys, bearer/auth tokens, passwords, private keys, and path-like values are removed or normalized before logging. Provider telemetry contains metadata rather than prompts or raw model outputs.

## Verification

- Phase 14 hardening suite: 13 passed.
- Exhaustive batched repository regression: **509/509 collected tests passed**.
- The monolithic all-in-one pytest invocation exceeded the command execution limit, so the same 509 collected tests were executed in deterministic batches instead of treating the timeout as a pass.
- Python `compileall app tests`: passed.

## Architecture outcome

Phase 14 strengthens the online delivery boundary without moving intelligence into the LLM. SHURY remains the state/experience/world-model/planner/policy/learning system; the model remains an optional language gateway.

## G09.x Integration / Release Boundary — 2026-10-01

### Canonical persistence
`LearningStore` is the single canonical persistence owner for learning, transition evidence, persistent beliefs, and cognitive events. `BrainStateStore` is a compatibility facade and defines no schema of its own. `BrainExperienceStore` remains an alias for `LearningStore`. The historical `brain_state.db` is import-only and is never implicitly imported into custom/test stores.

### Canonical LLM boundary
`run_cognitive` and structured Brain execution do not give an LLM tool-selection or execution authority. `run_react` is disabled by default. `run_legacy_llm_react` is an explicit compatibility/benchmark surface, and its tests are marked `legacy_llm`.

### Proof status
- Specification gap gate: 41 passed.
- V23/evaluation/real-user integration gate: 75 passed.
- Store/boundary regression gate: 35 passed.
- Procedure family transfer proof: 3 passed.
- Phase 2–9 regression batch: 54 passed.
- Phase 10–14 + gap integration batch: 47 passed.
- Clean release packaging is required to exclude generated runtime artifacts.
