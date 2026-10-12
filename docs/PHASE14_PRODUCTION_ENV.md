# Phase 14 — Production Environment Controls

Phase 14 does not require a second database, a GPU host, or a provider-specific brain implementation.

## Minimum online API settings

```text
SHURY_ENV=production
SHURY_API_TOKEN=<long-random-secret>
AGENT_UI_HOST=0.0.0.0
AGENT_UI_PORT=8765
```

The application keeps TLS outside the Python HTTP server; expose it through the deployment's HTTPS reverse proxy before making it publicly reachable.

## HTTP limits

```text
SHURY_MAX_JSON_BYTES=2000000
SHURY_MAX_CHAT_CHARS=20000
SHURY_MAX_SESSION_CHARS=160
SHURY_MAX_IDEMPOTENCY_KEY_CHARS=128
SHURY_RATE_CAPACITY=60
SHURY_RATE_REFILL_PER_SECOND=1
SHURY_TRUST_PROXY=false
```

Set `SHURY_TRUST_PROXY=true` only when the deployment controls and validates the forwarding headers.

## Task lease / recovery

```text
AGENT_UI_TASK_STALE_SECONDS=45
AGENT_UI_APPROVAL_TIMEOUT_SECONDS=180
```

A task lease is kept longer than the stale UI threshold. A stale task releases the lease so a previous worker cannot continue as an authorized executor.

## Optional LLM resilience

```text
SHURY_LLM_MAX_RETRIES=2
SHURY_LLM_RETRY_BACKOFF_SECONDS=0.25
SHURY_LLM_CIRCUIT_FAILURE_THRESHOLD=3
SHURY_LLM_CIRCUIT_COOLDOWN_SECONDS=20
SHURY_LLM_RATE_CAPACITY=30
SHURY_LLM_RATE_REFILL_PER_SECOND=0.5
SHURY_LLM_CACHE_TTL_SECONDS=0
SHURY_LLM_CACHE_SIZE=256
```

Structured LLM caching is disabled by default. Enable it only for language requests where an exact repeated input is safe to reuse.

## Logging

`SHURY_REQUEST_LOG_BODY` is false by default and should remain disabled unless a controlled debugging environment explicitly requires it. Provider telemetry records metadata and never stores prompts or API credentials.
