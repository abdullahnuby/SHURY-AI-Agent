# SHURY Company C17 Release

Version: `25.6.0-alpha1-company20`
Base: `25.5.0-alpha1-company19`

C17 — Evidence-Calibrated Workforce is complete.

The Company now converts canonical delegation outcomes into conservative specialist/capability/tool competency profiles using a 95% Wilson lower confidence bound. Sparse evidence remains explicitly insufficient. When matching evidence exists, calibrated competence is blended into the existing team history score as a secondary quality signal. Ownership, minimum team size, authority, reviewer independence, and SkillBank lifecycle remain unchanged.

Before entering C17, the C16-reported legacy CLI integration issue was closed: governed producer/actor/reason arguments are now passed correctly, governed Skill trust elevation is exposed, and rollback authority is explicit.

No new store, LLM fallback, model replacement, or sentence-specific operation routing was introduced.

## Verification

- `tests/test_company_*.py`: `125 passed in 26.08s`
- `tests/test_organization_core_v1.py`: `8 passed in 10.28s`
- `tests/test_layer5_canonical_runtime.py`: `1 passed in 9.96s`
- `tests/test_real_skill_lifecycle.py`: `4 passed in 7.83s`
- C18/C16/C17/local compatibility regression group: `34 passed in 15.48s`
- source compile: `SOURCE_COMPILE_PASS`
- `app/data`: `APP_DATA_DB_CLEAN`
