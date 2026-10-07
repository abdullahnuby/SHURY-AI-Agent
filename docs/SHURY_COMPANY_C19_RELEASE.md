# SHURY Company 22 — C19 Release

Version: `25.8.0-alpha1-company22`
Base: `25.7.0-alpha1-company21`

C19 adds explicit, fail-closed execution capacity and cost guardrails over the canonical Company portfolio and declared tool registry. It is opt-in at the `SHURYCompany.route_plan()` boundary so existing callers without a budget remain behavior-compatible.

## Gate

- Company: 125/125
- Required Core/Layer-5/lifecycle + C19: 19/19
- C15–C18 numbered regression + C19: 40/40
- Source compile: PASS
- Runtime `app/data/*.db`: CLEAN
- C19 on C18 baseline: collection failure because `app.organization.capacity` is absent

There is no pre-defined C20 in the current roadmap.
