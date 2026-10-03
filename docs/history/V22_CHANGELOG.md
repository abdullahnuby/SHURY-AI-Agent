# V22 Change Log

V22 is a bug-fix and reliability release based on a September 2026 review of recent agent research and the V21 runtime.

## Fixed

- Natural-language intent/routing coverage and precedence.
- Analytical conjunction parsing and semantic task grouping.
- `check_project` parameter contract (`checks`).
- Remote skill manifest/SkillBank key consistency.
- Legacy remote-skill approval migration path.
- Skill trust/status lifecycle invariants and quarantine promotion.
- Upstream refresh re-approval semantics.
- Attempt-duration accounting and resume audit duplication.
- Cross-step result piping.
- DNS/peer verification and HTTP/HTTPS port validation.

## Verification

- `python -m compileall -q app tests` — OK
- `pytest -q` — **158 passed**
- V21 benchmark — **9/9**
- Remote install → approve → refresh/hash-change → quarantine regression — PASS

## Research alignment

Recent work emphasizes query-conditional skill compatibility, explicit long-horizon planning/evaluation, replay-backed self-evolution, bounded skill retirement, hybrid retrieval/reranking, evidence verification, and context management. V22 applies the portions that fit the existing deterministic runtime without introducing an unverified remote model dependency.
