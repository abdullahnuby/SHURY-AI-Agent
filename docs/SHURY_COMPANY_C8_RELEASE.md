# SHURY Company C8 — CEO Team Formation

Implemented on `24.7.0-alpha1-company10`.

## Purpose
Choose the smallest effective set of specialists whose declared capabilities cover the
structured requirements of a goal. Team selection does not inspect benchmark sentence wording.

## Runtime contract
`goal -> structured capability requirements -> qualified candidates -> minimum specialist set ->
team formation record -> company coordination -> Brain trace`.

Verified SkillBank history is a quality tie-breaker after ownership and minimum team size.
Unresolved capabilities fail closed.

## CLI
`/company-team <goal>` inspects the CEO team decision without executing the task separately.

## Acceptance gate
- 5 dedicated C8 tests pass.
- Existing Company/runtime regressions remain green.
- Compileall passes.
- No runtime artifacts are packaged in the release ZIP.
