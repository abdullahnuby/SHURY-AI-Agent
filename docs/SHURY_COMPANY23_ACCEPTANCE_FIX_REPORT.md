# SHURY Company23 Acceptance Fix Report

## Release target

`25.8.0-alpha2-company23`

## What was changed

This pass addresses the F0–F7 failure classes from the externally observed acceptance failures without reading the held-out acceptance artifacts. The fix strategy is structural: shared workspace reference resolution, explicit semantic gating, local-first source selection, capability/goal coverage validation, canonical Memory routing, direct calculation precedence, and a whole-act wall-clock budget.

## Held-out isolation

The held-out acceptance files were not opened, imported, grepped, executed, or used to generate fixtures. The repository package excludes acceptance artifacts.

## Test evidence

### Existing suites

`python -m pytest -q tests/test_company_*.py --disable-warnings`

**Observed:** `125 passed in 18.96s`

`python -m pytest -q tests/test_organization_core_v1.py --disable-warnings`

**Observed:** `8 passed in 6.38s`

`python -m pytest -q tests/test_layer5_canonical_runtime.py --disable-warnings`

**Observed:** `1 passed in 6.32s`

`python -m pytest -q tests/test_real_skill_lifecycle.py --disable-warnings`

**Observed:** `4 passed in 5.73s`

### New dev set

`tests/dev_real_phrasing/test_fixes.py` contains **67 tests**:

- F0: 1
- F1: 8
- F2: 8
- F3: 8
- F4: 8
- F5: 16
- F6: 10
- F7: 8

Observed process-isolated results:

- F0: **1 passed**
- F1: **8 passed**
- F2: **8 passed**
- F3: **8 passed**
- F4: **8 passed**
- F5: **16 passed**
- F6: **10 passed**
- F7: **8 passed**

**Dev result:** **67/67 passed** under isolated class runs.

The aggregate single-process dev invocation did not complete with a trustworthy signal in this environment and ended in a transport timeout. This is recorded rather than hidden.

### F821

The required gate is installed in `scripts/run_isolated_tests.py` as:

```text
ruff check --select F821 app/
```

Actual delivery-environment result:

```text
status: tool_missing
ruff executable is not installed in the current environment
```

The gate fails closed. The result is **not** represented as a successful lint scan.

## Other environment limitation

The production NLP path is not runnable in this container because `sentence_transformers` is missing. The repository tests intentionally run with `SHURY_NLP_MODE=off`, so the actual `omarelshehy/Arabic-Retrieval-v1.0` runtime was not reloaded/revalidated here. This is an environment limitation, not a claim that the model is broken.

## Additional issue discovered but not silently fixed

The dev suite exhibits a cumulative single-process timeout/transport failure even though every F-class test passes in isolated process runs. This points to test/runtime process state rather than a deterministic class assertion failure. No speculative global reset or architectural feature was added to mask it.

During the pass, four Company tests briefly regressed because the acceptance fixes interacted with existing organization/planning semantics. Those regressions were traced to our changes, fixed, and the final Company gate returned to **125/125**. No existing test file was modified.

## Final acceptance stance

The external acceptance suite itself was intentionally not run or inspected because it is held-out. Therefore this delivery proves the requested root causes against an independent dev set and the required repository regression gates; it does **not** claim the held-out 0/16 acceptance result has been re-run.

No C20 work was started.

## Post-delivery runtime F821 review

A post-delivery source review identified three additional runtime name-binding defects:

1. `app/brain/kernel.py:1904`: `_compose_observed_answer()` referenced `Decision` without importing it. Fixed by importing the canonical `Decision` model from `app.brain.models`.
2. `app/organization/recovery.py:183`: the C9 re-delegation routing block constructed `CapabilityCandidate` without importing it. Fixed by importing the canonical `CapabilityCandidate` from `.capability_planning`.
3. `app/learning/store.py:2227`: `update_replay_priorities()` used `replay_priority_components`, but the import existed only in `index_replay_transitions()`. Fixed by adding the local import to `update_replay_priorities()` as well. The import was deliberately not promoted to module scope because that introduces a circular import through `app.learning.replay -> app.planning -> app.learning.brain_store`.

Regression proof:
- New `tests/test_runtime_name_binding_regressions.py`: **3/3 passed** after the fix.
- The same three tests copied unchanged to the unmodified Company23 acceptance-fix archive: **3/3 failed**, reproducing the targeted defects.

Post-patch regression gates observed:
- all `tests/test_company_*.py`: **125/125 passed** when executed file-by-file with per-file timeouts;
- `tests/test_organization_core_v1.py`: **8/8 passed**;
- `tests/test_layer5_canonical_runtime.py`: **1/1 passed**;
- `tests/test_real_skill_lifecycle.py`: **4/4 passed**;
- dev set historical isolated result for F0-F7: **67/67 passed**; fresh post-patch checks additionally confirmed F0 **1/1**, F1 **8/8**, and F2 **8/8**;
- direct `ruff check --select F821 app/`: **blocked because Ruff is not installed and the environment cannot reach the package index**. The delivery gate remains fail-closed.

No held-out acceptance artifact was read, imported, grepped, executed, or used. No C20 work was started.
