# V22 Verification

Date: 2026-09-29

## Automated regression

**158 passed, 0 failed** via `pytest -q`.

`python -m compileall -q app tests` completed successfully.

## Targeted V22 fixes

- Bilingual natural-language routing: PASS
- Compound analytical goal preservation: PASS
- Build/test tool contract: PASS
- Remote Skill install/approve identity consistency: PASS
- Upstream Skill refresh forces re-approval on content change: PASS
- Quarantined Skill cannot auto-promote: PASS
- Trust downgrade revokes active/approved state: PASS
- Connected HTTP peer must match validated public DNS: PASS
- IPv6/private network URL validation: PASS
- Failure duration accumulates across retries: PASS
- Resume does not duplicate terminal audit event: PASS
- Cross-step result/output piping: PASS

## Benchmark

The existing V21 benchmark remains **9/9**. V22 adds focused regression tests in `tests/test_v22.py` without weakening the V21 contracts.
