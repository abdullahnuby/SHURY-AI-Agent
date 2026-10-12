# SHURY — PHASE 6 RESULT

## Scope
User-facing response separation for CLI and Web.

## Changes
- Added `serialize_public_state()` to expose only `status` and the natural final response.
- Added `serialize_task_for_api()` to project persisted tasks into a safe public Web contract.
- `/api/tasks` and `/api/session` now return sanitized task state by default.
- Debug diagnostics require both `?debug=1` and `SHURY_ENABLE_DEBUG_UI=1`.
- Existing full `serialize_state()` remains available for trusted diagnostics/tests.
- Web polling now requests debug data only when the UI is explicitly in debug mode.
- Replaced internal cognitive-process wording in the normal composer hint with user-facing language.
- Added response-boundary regression tests in `tests/test_phase6_response_boundary.py`.

## Baseline failures recorded before fix
- Web task transport exposed full serialized cognitive state by default.
- Normal CLI response path itself was green.
- `tests/test_chat_ui_regressions.py`: 1 pre-existing Brain cognition failure (`research` expected, `clarify` observed).

## Verification
- Phase 6 boundary regressions: 6/6 passed.
- CLI layer regression: 4/4 passed.
- Chat runtime regression: 9/9 passed.
- Web interface regression: 4/4 passed.
- Brain Arabic NLP bridge regression: 2/2 passed.
- Python compile: PASS.
- JavaScript syntax: PASS.
- Live CLI: PASS; normal output was `Hello. I'm SHURY.` with no runtime metadata.
- Live Web: PASS; normal task payload contained only safe state fields and no `trace`, `cognitive`, `plan`, `run_id`, `trace_id`, `world`, or `execution` fields.
- Live debug mode: PASS; diagnostics appeared only when `SHURY_ENABLE_DEBUG_UI=1` and `debug=1` were both active.

## Out-of-scope failures still recorded
`tests/test_cognitive_kernel.py` remains red on four pre-existing semantic/Brain assertions:
- `answer_source`: `memory` vs `beliefs`
- missing `memory` evidence kind
- Arabic greeting routed to `research`
- Arabic calculation classified as `clarify`

These are not response-layer defects and were deliberately not changed during Phase 6.

## Gate
PASS
