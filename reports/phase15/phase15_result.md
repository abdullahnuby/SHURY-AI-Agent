# PHASE 15 RESULT — ROOT CAUSE FIXES

## Scope
Implemented root-cause fixes from Phase 14 using the required sequence:

FIX → REGRESSION TEST → FOCUSED TESTS

No Phase 16 work was started.

## Implemented

### Memory
- Canonical identity recall now produces `recall:key=name` and routes to `query_identity`.
- Canonical memory evidence is surfaced as `kind=memory` rather than a generic belief-only compatibility item.

### Social
- Normalized Egyptian Arabic social vocabulary is consumed consistently after Arabic text normalization.

### Reference
- Arabic copular constructions (`ما هو/ما هي ...`) no longer create false discourse-reference ambiguity.

### Research / Learning
- `open_world_learning` is normalized into canonical research/learning operation families.
- Learning intent/capability and research query are preserved through planning.
- External learning selects the learning-aware research capability.

### Planning / Execution
- Namespaced semantic fields are transferred to the Brain's stable slot vocabulary, including calculation expressions and research/memory queries.
- Calculator requests now become executable planner actions.

### Verification / Learning
- The repaired calculation path reaches the existing verification and learning transition machinery; persistence is regression-tested.

### Runtime test orchestration
- Added `scripts/run_isolated_tests.py` for deterministic clean-process execution and explicit timeout reporting.
- Runner safely serializes timeout output without creating false passes.

## Regression evidence

- Phase 15 capability regressions: **7/7 PASS**
- Core affected suites: **18/18 PASS**
- Reference + bilingual isolated capability coverage after final fix: **19/19 PASS**
- Phase 8 reference suite: **8/8 PASS**
- Semantic contract: **3/3 PASS**
- Semantic Layer 2: **13/13 PASS**
- Semantic real-user: **19/19 PASS**
- Phase 10 generator: **6/6 PASS**
- Phase 11 oracle: **10/10 PASS**
- Phase 14 production hardening: **10/10 PASS**
- Python compileall: **PASS**

## Runtime-orchestration evidence

`test_chat_ui_regressions.py`: **6/6 PASS**, clean isolated process.

`test_memory_v22_full.py`: bounded runner recorded an explicit timeout after **38 completed tests**; no false PASS was produced. The isolated correction test itself terminates successfully.

This is an orchestration/runtime-cost mitigation, not a claim that the historical aggregate memory suite is fully optimized.

## Environment blocker

`omarelshehy/Arabic-Retrieval-v1.0` remains the required production semantic model. The environment still lacks `sentence_transformers`/`transformers` and model weights, and dependency installation is blocked by DNS/network failure.

The canonical runtime is therefore intentionally **fail-closed** under required NLP mode.

No replacement model and no generative LLM were added.

## Changed files

1. `app/brain/deliberation.py` — canonical memory evidence source and research/learning decision handling.
2. `app/brain/models.py` — canonical-memory compatibility evidence.
3. `app/intelligence/semantic/parser.py` — identity recall slots, normalized social handling, learning query extraction, capability/context preservation.
4. `app/intelligence/semantic/references.py` — copular-reference grammar boundary.
5. `app/brain/kernel.py` — semantic-to-Brain slot/operation normalization.
6. `app/brain/methods.py` — learning-aware research capability selection.
7. `app/brain/planner.py` — canonical capability/tool planning for learning.
8. `scripts/run_isolated_tests.py` — bounded deterministic test orchestration.
9. `tests/test_phase15_root_cause_fixes.py` — capability regressions.

## Source integrity

The Phase 14 snapshot comparison shows exactly the seven production modules plus one runner and one regression test as intentional code/test changes. Runtime probe mutations to `app/data/learning.db`, `app/data/skills.db`, and `app/logs/agent.jsonl` were restored to the Phase 14 snapshot before packaging.

No exact-sentence production pattern was introduced.

## Gate

**PASS for all code-addressable Phase 14 root causes.**

The external production-model/environment blocker remains explicitly documented and fail-closed; it is not falsely reported as solved.
