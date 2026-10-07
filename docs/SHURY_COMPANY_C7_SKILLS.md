# SHURY Company C7 — Skill & Competency Catalog

C7 connects the existing `SkillBank` to the organization without creating a second skill store.

## Contract

`department → role → skill → capability → tool → verification`

The `SkillBank` remains authoritative for skill content and lifecycle: triggers, contraindications,
preconditions, workflow, outputs, evidence, verification, confidence, trust and outcome history.
The organization catalog remains authoritative for who owns a skill. `OrganizationSkillIndex` is a
runtime projection only; it stores no duplicate skill records.

## Behavior

- Missing company skill references fail validation.
- A skill may not be owned by multiple departments.
- Capability lookup derives from SkillBank workflow capability fields.
- When a planned action has a capability but no `skill_key`, Company routing attempts to bind it to
a company-owned SkillBank skill whose workflow contains the selected tool.
- If no skill is bound, existing structural capability/effect/tool ownership rules remain available.
- Skill metadata is inspectable through `/company-skills`.

## Gate

A structured capability can resolve to an existing verified SkillBank skill and then to its owning
department and specialist without any sentence-specific routing rule.
