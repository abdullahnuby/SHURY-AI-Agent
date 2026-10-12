# SHURY — Phase 15 Fix Matrix

| RCA | Fix | Regression | Focused evidence | Status |
|---|---|---|---|---|
| RC-MEM-01 | Canonical identity recall now emits `recall:key=name`; Brain answers from canonical memory. | `test_identity...`, Phase 15 memory tests | 2/2 focused | PASS |
| RC-MEM-02 | Canonical memory/belief evidence is exposed as `kind=memory` in the compatibility memory view. | memory evidence regression | 2/2 | PASS |
| RC-SOC-01 | Social classifier consumes normalized Arabic vocabulary (`الاخبار`) consistently. | normalized Egyptian social regression | 2/2 | PASS |
| RC-RES-01 | Arabic copular `ما هو/ما هي ...` is treated as grammatical copula, not discourse anaphora. | generic factual-reference regression | 9/9 with Phase 8 refs | PASS |
| RC-RES-02 | `open_world_learning` is normalized into canonical research/learning operation families while preserving learning capability and query. | external + internal learning regressions | 2/2; Web cognition covered | PASS |
| RC-PLAN-01 | Namespaced semantic slots are mapped to Brain-stable slots (`operation:expression -> expression`, research/memory query aliases, etc.). | calculator planner regression | 3/3 incl. execution path | PASS |
| RC-VER-01 | Verification/learning loop now becomes reachable because executable calculation transitions are restored; persistence regression verifies learning evidence. | learning integration regression | 3/3 | PASS |
| RC-RUN-01 | Added bounded isolated-test runner with clean subprocesses and explicit timeout JSON; byte output is normalized safely. | runner + isolated Web/Memory checks | Web 6/6; Memory reports explicit timeout after 38 completed tests | MITIGATED |
| RC-ENV-01 | Production required-NLP path remains fail-closed; no model substitution or hidden fallback. | strict-mode Phase 12 regression | 14/14 strict/runtime checks | BLOCKED BY ENVIRONMENT |

## Control rule

No exact-sentence production branches were added. The fixes operate on semantic vocabulary, grammatical structure, capability preservation, contract mapping, evidence semantics, or test orchestration.
