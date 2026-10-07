# Company 8 — Organization Blueprint

Release: `24.5.0-alpha1-company8`

- Introduced declarative organization source of truth at `app/organization/organization.toml`.
- Added `OrganizationCatalog` with structural validation for CEO, roles, departments, heads, specialists and reviewers.
- Preserved `CEO`, `ROLES`, `DEPARTMENTS` and `DEFAULT_COMPANY` compatibility.
- Added the master Company roadmap and master TODO.
- Deliberately did not create a second SkillBank; competency metadata remains the next phase and must reference the existing SkillBank.
- Preserved existing Company 1–7 behavior.
