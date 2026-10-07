# SHURY Company — Master TODO

## Current truth

Current release: `25.9.0-alpha1-company23`

Completed: C0, C1, C2, C3, C4, C5, C6, C7, C8, C9, C10, C11, C12, C13, C14, C15, C16, C17, C18, C19, C20
Current: C20 Weight-Driven Policy Learning complete. No pre-defined C21 roadmap phase exists yet.

## C0–C6 — completed

- [x] Freeze canonical runtime and preserve Arabic-Retrieval-v1.0.
- [x] Organization core with CEO, departments, specialists, ownership, authority and reviewers.
- [x] Structured capability synthesis for novelty.
- [x] Department execution contexts and least-privilege task scopes.
- [x] Typed handoffs and dependency DAG.
- [x] Safe fail-closed scheduling.
- [x] Declarative organization catalog as the single source of organizational truth.

## C7 — Skill & Competency Catalog

- [x] Define a stable skill metadata contract above the existing SkillBank.
- [x] Link each skill to department/role/capabilities without duplicating SkillBank storage.
- [x] Add triggers, preconditions, outputs, evidence expectations and contraindications.
- [x] Add skill-level verification requirements.
- [x] Detect orphan skills and ambiguous ownership.
- [x] Regression: existing built-in skills retain their current behavior.

Gate: a novel structured capability can resolve `capability → skill → department → specialist → tool` using the existing SkillBank, with no sentence-specific rule.

## C8 — CEO Team Formation

- [x] Estimate the minimum required competencies for a goal.
- [x] Select the smallest effective set of specialists.
- [x] Avoid adding a department when an existing role covers the responsibility.
- [x] Record why each member was selected.

Gate: multi-department tasks use only the departments actually justified by required competencies.

## C9 — Delegation & Recovery

- [x] Track verified success by capability/role/tool in the existing LearningStore.
- [x] Re-delegate after a measured execution/verification failure only when a qualified same-capability alternative has verified success evidence.
- [x] Escalate governance/context failures and cases with no evidence-backed alternative.
- [x] Keep organization ownership facts immutable; recovery may choose among qualified candidates but never rewrites ownership.

Gate: failure causes evidence-based re-delegation, not random reassignment.


## C10 — Company Memory

- [x] Decision memory.
- [x] Ownership memory.
- [x] Reusable procedures.
- [x] Failed approaches and lessons.
- [x] Review findings.
- [x] Separate durable company memory from task context.

Gate: a later task can reuse verified company knowledge without inheriting unrelated task state.

## C11 — Evidence & Sources — completed

- [x] Source registry for claims settled by external authorities.
- [x] Freshness metadata.
- [x] License / citation policy.
- [x] Skill → source bindings.
- [x] No copied third-party source text.
- [x] Runtime provenance gate for research-oriented skills.

Gate: research/legal/compliance outputs carry appropriate evidence provenance.

## C12 — Governance — completed

- [x] Authority policies by action class.
- [x] Human approval gates.
- [x] External publication gates.
- [x] Destructive action gates.
- [x] Independent reviewer enforcement.
- [x] Immutable action fingerprints for approval scope.
- [x] Fail-closed governance denial before tool execution.

Gate: high-impact actions cannot bypass the governance contract.

## C13 — Company Evaluation — completed

- [x] Single-department scenarios.
- [x] Two/three-department scenarios.
- [x] Novel goals without workflow-name dependence.
- [x] Wrong-owner attempts.
- [x] Ambiguous ownership.
- [x] Reviewer independence.
- [x] Failure and evidence-backed re-delegation.
- [x] Context saturation / isolation.
- [x] Unnecessary delegation rate.
- [x] Canonical structured Brain delegation smoke.
- [x] Release gate that refuses Company readiness on any critical failure.

Gate: 10 contract scenarios + canonical Brain delegation pass with zero safety/ambiguity/reviewer/recovery/context failures and unnecessary delegation rate ≤ 5%.

## C14 — Multi-Horizon Company

- [x] Multiple active projects.
- [x] Persistent specialist identities.
- [x] Task prioritization across projects.
- [x] Isolated working contexts.
- [x] Tiered organizational memory.
- [x] Reprioritization under load.

Gate: adding concurrent work does not corrupt unrelated project state.

## C15 — Controlled Self-Improvement — completed

- [x] Skill acquisition as candidate-only proposals in the existing SkillBank.
- [x] Skill evaluation using the existing Layer-5 differential evaluation.
- [x] Promotion/deprecation through explicit Company proposals.
- [x] Organizational change proposals for role/department/capability topology.
- [x] Regression-backed changes only.
- [x] Independent security review plus CEO approval before application.
- [x] Skill rollback through the canonical SkillBank/LearningStore path.

Gate: SHURY may improve the company only through governed, evidence-backed changes. **PASS.**

## C16 — Controlled Company Learning Loop — completed

- [x] Feed verified post-change outcomes back into Company Memory and specialist reliability.
- [x] Detect whether an applied change actually improved unseen-task outcomes.
- [x] Detect regressions after deployment and auto-open rollback proposals without auto-applying them.
- [x] Measure organization-level improvement separately from single-task improvement.

Gate: a Company change is retained only when improvement generalizes beyond the evaluation task family and remains within governance limits. **PASS.**

## C17 — Evidence-Calibrated Workforce — completed

- [x] Calibrate specialist/capability competence from canonical Company delegation evidence.
- [x] Treat sparse evidence conservatively using a confidence-bound score.
- [x] Use calibrated evidence only as a secondary team-selection signal.
- [x] Expose calibration through the Company CLI without granting execution authority.

Gate: no ownership/authority mutation, no second store, and sparse evidence cannot over-promote a specialist. **PASS.**

## Working rule

Never skip a gate. Never create a new workflow solely to satisfy one benchmark sentence. Add a new
organizational concept only when it generalizes across real tasks.


## C18 — Adaptive Delegation & Load-Aware Routing — completed

- [x] Rank already-qualified candidates using structured capability fit and canonical evidence.
- [x] Penalize current active specialist load from the canonical Company portfolio as a secondary signal.
- [x] Keep ownership, role class, authority, reviewer policy, and SkillBank lifecycle immutable.
- [x] Reuse the same secondary ordering for verified recovery alternatives without changing governance behavior.
- [x] Expose routing inspection through the Company CLI.

Gate: routing can change delegation preference only inside the set of already-qualified candidates. **PASS.**


## C19 — Capacity & Budget Guardrails — completed

- [x] Explicit execution budget contract.
- [x] Preflight estimated tool-cost check.
- [x] Canonical portfolio active-capacity check.
- [x] Fail closed when constrained dimensions cannot be verified.
- [x] Preserve ownership, authority, reviewer, and SkillBank invariants.

Gate: declared capacity/cost limits are enforced before execution; default routing behavior is unchanged when no budget is supplied. **PASS.**
