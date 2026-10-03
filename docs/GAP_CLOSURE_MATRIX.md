# SHURY Specification Gap Closure Matrix

This document is an engineering proof index, not a new phase roadmap.
Canonical specification phases remain **Phase 0 through Phase 14**.
Gap closure work is tracked as **G01 through G08**.

| Gap | Requirement | Implementation surface | Acceptance proof |
|---|---|---|---|
| 1 | Model invalidation / drift | `app/learning/invalidation.py`, `app/learning/store.py` | `tests/test_model_invalidation.py` |
| 2 | Meta-strategy controller | `app/learning/meta_strategy.py`, `app/brain/planner.py`, `app/planning/planner.py` | `tests/test_meta_strategy_controller.py`, `tests/test_spec_gap_closure_g07.py`, `tests/test_spec_gap_closure_g05.py` |
| 3 | Structured procedural memory | `app/learning/procedures.py`, `app/learning/store.py` | `tests/test_spec_gap_closure_g05.py`, `tests/test_phase13_language_pattern_cache.py` |
| 4 | Causal learning | `app/learning/causal.py`, `app/learning/store.py` | `tests/test_spec_gap_closure_g06.py` |
| 5 | Evaluation metrics | `app/evaluation/learning_metrics.py`, `app/learning/store.py` | `tests/test_spec_gap_closure_g05.py` |
| 6 | Catastrophic forgetting | `app/evaluation/learning_metrics.py`, `app/learning/value_model.py` | `tests/test_spec_gap_closure_g05.py` |
| 7 | Continual learning beliefs/history | `app/learning/continual.py`, `app/learning/store.py`, `app/learning/transition_model.py` | `tests/test_spec_gap_closure_g08.py` |
| 8 | Failure lessons | `app/learning/diagnosis.py`, `app/learning/failure_recovery.py`, `app/learning/store.py` | `tests/test_failure_recovery_learning.py` |
| 9 | Recovery learning | `app/learning/failure_recovery.py`, `app/learning/store.py`, `app/learning/manager.py` | `tests/test_failure_recovery_learning.py` |
| 10 | Procedure generalization | `app/learning/procedures.py`, `app/learning/store.py` | `tests/test_spec_gap_closure_g05.py` |
| 11 | Multi-dimensional reward | `app/learning/value_model.py`, `app/learning/manager.py` | `tests/test_spec_gap_closure_g05.py` |
| 12 | Information-gain planning | `app/learning/exploration.py`, `app/brain/planner.py` | `tests/test_spec_gap_closure_g05.py`, `tests/test_phase8_exploration.py` |
| 13 | Contextual self-model → planning | `app/learning/store.py`, `app/learning/self_model.py`, `app/planning/model_based_planner.py` | `tests/test_spec_gap_closure_g05.py` |
| 14 | Credit assignment | `app/learning/value_model.py` | `tests/test_spec_gap_closure_g05.py` |
| 15 | Single learning store | `app/learning/store.py`, `app/learning/brain_store.py`, `app/brain/learning.py` | `tests/test_spec_gap_closure_g07.py` |
| 16 | LLM boundary | `app/runtime/cognitive_agent.py`, `app/runtime/react.py` | `tests/test_spec_gap_closure_g07.py`, `tests/test_phase9_llm_independent_execution.py` |
| 17 | Phase numbering | `docs/PHASE_NUMBERING.md` | repository documentation review |

## Non-goals / explicit boundaries

- Cloudflare Workers AI is still an optional language-gateway integration; it is not part of the SHURY cognitive authority.
- Legacy `run_react` remains an explicit opt-in adapter and is not part of the canonical cognitive path.
- Evaluation metrics requiring an oracle, baseline, or held-out task set are exposed as explicit evaluation inputs rather than fabricated from runtime evidence.
- Replay and counterfactual learning remain side-effect-free.

### G03 proof hardening — value-slot transfer
A dedicated acceptance test now proves that concrete numeric/task values normalize into one canonical procedure-family record, retain evidence from multiple verified runs, and promote/retrieve the shared family:
`tests/test_procedure_family_generalization.py::test_value_slots_share_one_canonical_procedure_family`.


## Post-G08 integration audit — G09.x

G09.x is an integration hardening track, not a new specification phase.

### G09.5 — canonical persistence
- `app/learning/store.py` owns learning, transition, belief, and cognitive-event persistence.
- `app/brain/store.py` is a compatibility facade; it defines no database schema.
- `app/brain/learning.py` is a compatibility alias to `LearningStore`.
- Legacy `brain_state.db` is import-only and is never used as a default/custom test-state source.

### G09.6 — regression/release boundary
- Custom/test stores never import global legacy state implicitly.
- Legacy LLM ReAct tests are explicitly marked `legacy_llm`.
- Canonical `run_cognitive` / `act_structured` remains LLM-decision-free.
- Full release packaging must exclude runtime-generated SQLite/log/cache artifacts.
