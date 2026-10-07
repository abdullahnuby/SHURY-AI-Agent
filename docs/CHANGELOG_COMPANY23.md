# SHURY Company23 — Acceptance Failures Fix Pass

**Release:** `25.8.0-alpha2-company23`  
**Scope:** F0–F7 acceptance-failure root causes only.  
**C20:** not started.

## Important test-boundary rule

The held-out acceptance artifacts were not read, imported, grepped, executed, or used as fixtures. The dev set is independent and lives under `tests/dev_real_phrasing/`.

## F0 — verification NameError

**Root cause:** `app/brain/kernel.py` (baseline around execution/replan branch near line 1219) referenced `verification_error` after the loop scope had exposed the failure as `error`.

**Change:** use the scoped `error` value when constructing the replan request. The verification path now records a failed verification and proceeds through the normal recovery/replan path instead of raising `NameError`.

**Test:** `tests/dev_real_phrasing/test_fixes.py::test_f0_verification_failure_replans_without_nameerror`.

**Result:** `1 passed` in isolated class run.

## F1 — local workspace reference extraction

**Root cause:** duplicated `_extract_path()` implementations returned the whole user sentence as a path when marker-based parsing failed. Baseline locations were `app/tools/integrations/workspace.py` around lines 9–22 and `app/tools/data/analysis.py` around lines 43–70.

**Change:** added one shared resolver in `app/tools/workspace_reference.py` with explicit `resolved / ambiguous / missing / outside` states. It resolves quoted names, extension-bearing tokens, marker-following names, nested paths, and live workspace names with conservative normalization/fuzzy matching. No whole-sentence fallback remains. Concrete paths are existence-checked before tool use.

`app/tools/integrations/workspace.py` and `app/tools/data/analysis.py` now use the shared resolver. Generic semantic dataset references use the canonical `@active_dataset` symbol rather than the user sentence.

**Test:** 8 independent phrasing/fixture cases in `test_f1_workspace_reference_is_resolved_against_live_files`.

**Result:** `8 passed`.

## F2 — local-first data/file source selection

**Root cause:** generic knowledge/research routing could win when the user was asking about local workspace data, and failed local tools could be followed by remote retrieval.

**Change:** `app/brain/deliberation.py` now blocks ambiguous/outside local references before execution and keeps explicitly local operations on the workspace path. Web/RAG is only selected when external research is explicit or no local operation is available. Empty/unhelpful remote evidence is not treated as a successful answer.

**Test:** 8 local-workspace cases with actual CSV/text/recursive fixtures and remote-tool probes.

**Result:** `8 passed`.

## F3 — clarification gate / human-facing slots

**Root cause:** incomplete or ambiguous references could fall through to execution, and `goal_or_capability` / other implementation slot names could appear in the user response.

**Change:** `app/intelligence/semantic/parser.py` adds a strict unresolved-reference gate, candidate surfacing, and explicit clarification questions for ambiguous/missing local targets. `app/brain/deliberation.py` converts those conditions into `clarify`/`refuse` decisions. `app/brain/response.py` maps internal slot identifiers to Arabic questions and never emits raw implementation vocabulary.

**Test:** 8 cases covering missing targets, ambiguous filenames/folders, missing destinations, and underspecified actions.

**Result:** `8 passed`.

## F4 — capability/action/destination coverage and postconditions

**Root cause:** a nearby skill/tool could be selected for the wrong action, destination information could be lost between semantic parsing and execution, and a tool could report success without the requested filesystem state actually being true.

**Change:** `app/brain/planner.py` validates that a materialized Skill covers required action/destination semantics. `app/brain/kernel.py` validates tool coverage before execution and performs filesystem goal-postcondition checks after tool verification for moves and report artifacts. Destination slots are preserved into executable steps. `app/brain/capabilities.py` exposes the move capability needed by the direct workspace-file organization route.

An intermediate review-contract regression was found during this pass: the company QA reviewer was incorrectly treating every move tool as a cross-department workflow. `app/organization/review.py` now chooses the stronger QA contract from workflow structure (department span, declared cross-department class, or an actual analysis+move workflow), so a standalone local move is reviewed as a standalone filesystem action while true cross-department workflows retain the stronger QA contract.

**Test:** 8 cases with real move/report fixtures and filesystem assertions.

**Result:** `8 passed`.

## F5 — memory must stay memory

**Root cause:** Egyptian colloquial recall questions without an explicit memory verb (for example direct questions about a stored number/code) could fall into general knowledge routing. Forgetting also needed to remove the derived belief projection, not only the canonical Memory record.

**Change:** `app/intelligence/semantic/parser.py` recognizes generic stored-datum recall shapes and prevents discourse-reference logic from turning a memory request into an unresolved action. `app/brain/deliberation.py` returns an explicit memory miss instead of web/RAG fallback. `app/brain/kernel.py` refreshes/removes the canonical derived belief projection through the existing `LearningStore` alias path after `forget_fact`.

**Test:** 16 cases: 8 store/recall/forget dialogues plus 8 recall-without-match cases with remote-tool probes.

**Result:** `16 passed`.

## F6 — direct calculation and wall-clock budget

**Root cause:** direct numeric expressions could be displaced by memory/knowledge evidence, and the execution budget was not a hard wall-clock boundary for the whole `act()` call.

**Change:** validated numeric expressions are reasserted as `calculate` after late semantic adjustments. `app/brain/response.py` returns the expression and result together. `app/brain/kernel.py` carries a monotonic deadline through thinking and execution, bounds tool calls with a timeout, and terminates the act loop when the wall-clock budget is exceeded. The existing network gateway already supplies request timeouts; the new Brain-level boundary also prevents a slow call from exceeding the overall task budget.

**Test:** 8 direct arithmetic variants + 1 thinking-budget case + 1 slow-network timeout case.

**Result:** `10 passed`.

## F7 — workspace boundary refusal

**Root cause:** external/escaping paths were classified too late, so the user could get a generic "missing information" response instead of an explicit governed refusal.

**Change:** the shared workspace resolver classifies absolute/escaping paths as `outside`; semantic uncertainty is promoted to a refusal before planning/execution; `app/brain/response.py` returns an explicit Arabic boundary message. Dev tests also assert no tool call occurs.

**Test:** 8 external-path variants (`../`, absolute Unix, absolute Windows, and outside destinations).

**Result:** `8 passed`.

## F821 gate

`scripts/run_isolated_tests.py` now runs `ruff check --select F821 app/` as a mandatory gate unless explicitly invoked with `--skip-ruff` for diagnostic test isolation.

**Actual environment result at delivery:** Ruff is not installed in this container. The gate exits non-zero with `status: tool_missing`. No claim of a successful Ruff F821 scan is made.

## Existing test suites

No existing test file was edited. The added dev suite is the only new test file.

Final observed results:

| Gate | Actual result |
|---|---:|
| `tests/test_company_*.py` | **125 passed** |
| `tests/test_organization_core_v1.py` | **8 passed** |
| `tests/test_layer5_canonical_runtime.py` | **1 passed** |
| `tests/test_real_skill_lifecycle.py` | **4 passed** |
| Dev F0 | **1 passed** |
| Dev F1 | **8 passed** |
| Dev F2 | **8 passed** |
| Dev F3 | **8 passed** |
| Dev F4 | **8 passed** |
| Dev F5 | **16 passed** |
| Dev F6 | **10 passed** |
| Dev F7 | **8 passed** |
| Dev total (isolated class runs) | **67/67 passed** |
| `ruff --select F821 app/` | **blocked: Ruff missing** |

A single aggregate `pytest -q tests/dev_real_phrasing/test_fixes.py` invocation did not produce a trustworthy completion signal in this container and ended in a transport timeout. The per-class process-isolated runs are the authoritative dev-set results for this delivery; the aggregate-run behavior is recorded as an environment/test-runner issue, not declared fixed.

## Live Arabic retrieval limitation

The container does not have `sentence_transformers` installed. Running the production NLP path therefore cannot instantiate `omarelshehy/Arabic-Retrieval-v1.0` here. The pytest environment deliberately uses `SHURY_NLP_MODE=off`, so the canonical model itself was not revalidated in this container.

## Status

- **F0:** dev-verified resolved.
- **F1:** dev-verified resolved.
- **F2:** dev-verified resolved.
- **F3:** dev-verified resolved.
- **F4:** dev-verified resolved.
- **F5:** dev-verified resolved.
- **F6:** dev-verified resolved for the tested direct-calculation and wall-clock budget paths.
- **F7:** dev-verified resolved.

No C20 feature/phase was started in this pass.
