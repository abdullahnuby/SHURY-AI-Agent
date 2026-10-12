
## Post-G09 Corrective Hardening — Causal / Drift / Recovery / Arabic Memory (2026-10-01)

### Causal
- Controlled causal effect now compares treatment and control only within matched state context; aggregate association is reported separately.
- Confounding risk is derived from the divergence between aggregate association and matched-state effect.
- Added Simpson-style regression coverage to prevent aggregate-association leakage into controlled effects.

### Model invalidation / regime drift
- Invalidation is idempotent while a transition model is already stale; repeated observations no longer create repeated invalidation events.
- Regime baseline is captured at the change boundary, and trigger failures are counted as fresh evidence.
- Historical pre-regime evidence is retained as weak evidence rather than dominating the new regime.
- Stale models remain stale until sufficient fresh successful evidence restores them; failure bursts do not reset freshness.

### Failure / recovery learning
- Recovery confidence is evidence-weighted rather than a fixed constant.
- Recovery promotion requires repeated verified real outcomes for the same state/failure/root/recovery action context.
- Model-predicted recovery quality is no longer treated as empirical recovery success.
- Failure lesson identity now includes state context and recovery action identity.
- Recovery diagnosis/simulation remains side-effect-free during learning.

### Arabic and durable memory
- Arabic identity questions accept trailing `؟` and the `ما هو اسمي؟` form.
- Identity retrieval uses the requested memory key instead of a hard-coded `name` key.
- Non-name first-person memory questions route to generic durable memory retrieval.
- Profile questions are parsed before generic remember intent, preventing read requests from becoming write requests.
- Canonical Brain syncs legacy profile facts into beliefs and renders profile evidence directly.
- `ما هي مدينتي؟` and `ما هو أصلي؟` are grounded to the correct memory keys and return stored evidence.
- Removed obsolete `app/learning/store.py.tmp` from the release.
