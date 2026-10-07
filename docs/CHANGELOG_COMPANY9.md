# Company 9 / C7 — Skill & Competency Catalog

## Added

- `OrganizationSkillIndex`: derived runtime bridge from the existing `SkillBank` to Company roles/departments.
- Capability-to-skill resolution for CEO capability synthesis and Company assignment.
- `/company-skills` CLI inspection for skill, capability, department, or role.
- Validation for missing skill references and multi-department skill ownership.

## Preserved

- Existing SkillBank remains the only persistent skill store.
- Arabic-Retrieval-v1.0 path unchanged.
- No LLM fallback.
- Existing Company C0–C6 execution contracts preserved.

## Verification

- Company/Organization/Runtime suite: 68/68 PASS.
- Compileall: PASS.
