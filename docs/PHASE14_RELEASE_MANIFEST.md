# SHURY Phase 14 — Release Manifest

## New production package
- `app/production/__init__.py`
- `app/production/config.py`
- `app/production/rate_limit.py`
- `app/production/redaction.py`

## Hardened existing boundaries
- `app/api.py`
- `app/brain/kernel.py`
- `app/knowledge/memory.py`
- `app/interfaces/web/server.py`
- `app/integrations/llm.py`

## Tests
- `tests/test_phase14_production_hardening.py`

## Documentation
- `docs/PHASE14_TASK_BREAKDOWN.md`
- `docs/SHURY_PHASE14_RESULT.md`
- `docs/PHASE14_PRODUCTION_ENV.md`
- `docs/PHASE14_RELEASE_MANIFEST.md`
- `CHANGELOG.md`

## Explicitly not added
- No Cloudflare Workers AI integration.
- No new database technology.
- No direct LLM-to-tool execution path.
- No change to SHURY's core planner/policy authority boundary.
