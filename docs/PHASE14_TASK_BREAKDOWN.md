# SHURY Phase 14 — Production Hardening

## Objective
Make the existing SHURY online interface safe to operate continuously without changing the cognitive architecture or making the LLM the brain.

## Task 14.1 — Persistent API task ledger
- [x] Reuse the existing `Memory` database.
- [x] Persist task lifecycle, timestamps, state, errors, and revisions.
- [x] Keep the local task dictionary as cache/compatibility only.

## Task 14.2 — Atomic idempotency
- [x] Add persistent `(route, idempotency_key)` records.
- [x] Atomically create the task and idempotency record with SQLite `BEGIN IMMEDIATE`.
- [x] Return the original response for a matching retry.
- [x] Reject key reuse with a different request fingerprint.

## Task 14.3 — Execution lease / stale-worker protection
- [x] Add durable execution owner and expiry fields.
- [x] Allow one active worker lease per task.
- [x] Renew the lease through the heartbeat thread.
- [x] Detect stale tasks using the production configuration.
- [x] Clear the lease when the UI releases a timed-out task.
- [x] Pass an execution guard into the canonical Brain.
- [x] Stop further Brain actions when the lease is lost.
- [x] Prevent a stale worker from overwriting durable timeout state.

## Task 14.4 — Durable approval state
- [x] Persist approval requests in the existing database.
- [x] Poll durable approval state so multiple API processes can observe the same decision.
- [x] Persist redacted approval arguments only.

## Task 14.5 — Request security
- [x] Optional bearer authentication, required automatically in production unless explicitly disabled.
- [x] Do not expose the authentication token in logs or error bodies.
- [x] Bound JSON body size.
- [x] Validate JSON content type.
- [x] Bound chat/session/idempotency input sizes.
- [x] Add request IDs and security headers.
- [x] Emit `WWW-Authenticate` on 401 and `Retry-After` on 429.

## Task 14.6 — Rate limiting
- [x] Add process-safe token-bucket API throttling.
- [x] Support trusted proxy client identity when explicitly enabled.
- [x] Add a separate provider-side LLM rate limiter.
- [x] Rate limiting never sleeps the request globally.

## Task 14.7 — LLM gateway resilience
- [x] Preserve provider abstraction.
- [x] Add provider timeout through the existing transport.
- [x] Retry only transient provider failures.
- [x] Add exponential bounded backoff.
- [x] Add per-provider circuit breaker with cooldown and single half-open probe.
- [x] Add optional exact-request structured-output cache; disabled by default.
- [x] Log provider metadata without logging prompts, secrets, or raw model output.
- [x] Expose provider health in `brain_status()` and `/api/health`.

## Task 14.8 — Telemetry / redaction
- [x] Redact recursive secret-like keys before durable `events` writes.
- [x] Redact runtime audit arguments before JSONL logging.
- [x] Provider logs contain metadata only.
- [x] Request telemetry records request ID, route, status, duration, and client key.

## Task 14.9 — Verification
- [x] Phase 14 production-hardening tests.
- [x] Phase 11 replay regression.
- [x] Phase 12 self-model regression.
- [x] Phase 13 language-pattern regression.
- [x] V23 cognitive and semantic regression.
- [x] Memory V22 regression.
- [x] Python compilation.
- [x] Full suite excluding the documented legacy V8 concurrency assertion.

## Explicit non-goals
- No Cloudflare integration is introduced by Phase 14.
- No LLM-generated tool selection is introduced.
- No LLM access to permissions, policy, runtime authority, or learning updates.
- No second database architecture is introduced.
- No private chain-of-thought is persisted or exposed.
