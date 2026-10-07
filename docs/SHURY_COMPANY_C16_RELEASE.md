# SHURY Company C16 Release

Version: `25.5.0-alpha1-company19`
Base: `25.4.0-alpha2-company18`

C16 — Controlled Company Learning Loop is complete.

The company can now consume verified post-change runtime outcomes through the canonical LearningStore, update specialist reliability, retain verified outcomes in canonical Company Memory, measure unseen-task generalization separately from the single change, measure organization-level reliability independently, and open governed Skill rollback proposals when monitoring fails. Monitoring never auto-applies rollback.

No new persistence store was introduced. No LLM fallback was introduced. `omarelshehy/Arabic-Retrieval-v1.0` remains unchanged.

## Verification

- Company suite: `125 passed in 27.77s`
- Organization Core: `8 passed in 9.73s` (reported runner output: `8 passed in 9.73s`)
- Layer-5 canonical runtime: `1 passed in 8.83s`
- Real skill lifecycle: `4 passed in 8.54s`
- C18 hardening + runtime artifacts: `15 passed in 10.79s`
- C16 learning loop: `5 passed in 12.62s`
- `python -m compileall -q app tests`: PASS
- `app/data` runtime DB check: `APP_DATA_DB_CLEAN`
