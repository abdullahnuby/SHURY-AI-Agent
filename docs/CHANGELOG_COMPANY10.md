# Company 10 — C8 CEO Team Formation

## Added
- `app/organization/team.py` with deterministic minimum-specialist team formation.
- `CompanyTeamMember` and `ExecutiveTeamPlan` contracts.
- SkillBank success/failure history and confidence as organizational selection evidence.
- `SHURYCompany.form_team()` / `OrganizationRegistry.form_team()`.
- `CompanyCoordination.team_formation` persisted into Brain coordination and trace.
- `/company-team <goal>` inspection command.
- C8 regression suite covering single-department, shared-specialist, cross-department, unresolved, and coordination cases.

## Policy
Team size is minimized first. Candidate fit, verified SkillBank history, risk and cost are deterministic quality signals after qualification and ownership. No department-name keyword routing is introduced.

## Validation
- 82 Company/organization/canonical regression tests pass.
- compileall passes.
- Release package contains no runtime caches, logs, or local databases.
