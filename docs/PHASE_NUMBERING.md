# SHURY Phase Numbering

The engineering migration specification explicitly defines the canonical roadmap as Phase 0 through Phase 14, including:
- Phase 9 — LLM-independent execution
- Phase 10 — learning loop
- Phase 11 — replay
- Phase 12 — self-model
- Phase 13 — language-pattern caching
- Phase 14 — production hardening

These numbers are specification phases and are not to be renumbered.

Post-Phase-14 work is **specification gap closure**, not a new roadmap phase. It is tracked as `G01`, `G02`, ... and may contain multiple implementation tasks and acceptance tests.

Current mapping:
- G01 — Model invalidation / drift + procedure invalidation
- G02 — Meta-strategy controller
- G03 — Structured procedural memory + procedure generalization
- G04 — Failure diagnosis + recovery learning
- G05 — Evaluation metrics + specification experiments
- G06 — Causal learning + controlled counterfactual replay
- G07 — Architecture boundaries: canonical learning store + LLM boundary
- G08 — Integration proof, metrics wiring, and acceptance-matrix hardening

G08 is the current proof/integration track; it does not redefine the canonical Phase 0–14 roadmap.

This keeps the source specification roadmap separate from post-roadmap proof/closure work.


Post-G08 integration hardening is tracked as **G09.x** sub-tasks. These labels do not
change the canonical Phase 0–14 numbering and are used only for release-boundary work.
