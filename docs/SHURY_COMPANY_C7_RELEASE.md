# SHURY Company C7 Release

Implemented the Skill & Competency Catalog bridge on top of Company C6.

## What changed

- Added `OrganizationSkillIndex` as a derived runtime projection over the existing SkillBank.
- Added skill → department/role/capability lookup and validation.
- Added capability-to-skill binding during CEO capability synthesis.
- Added automatic skill binding when a plan step has a capability but no skill key.
- Added `/company-skills` inspection command.
- Added C7 regressions for missing skills, ownership ambiguity, capability lookup and department skill sets.

## Non-goals

- No second persistent Skill database.
- No sentence-specific skill routing rules.
- No LLM fallback.
- No replacement of Arabic-Retrieval-v1.0.

## Verification

Company/Organization/Runtime suite: **68/68 PASS**.

`python -m compileall -q app`: **PASS**.

CLI smoke: `/company-skills builtin:data-analysis` and `/company-skills data_analysis` both returned the expected Data department bindings with zero validation errors.

Full end-to-end Arabic model verification remains authoritative on the user's Windows runtime.
