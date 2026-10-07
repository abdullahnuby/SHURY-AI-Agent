# SHURY Company — Master Execution Plan

## North Star

SHURY is being evolved from a strong single-agent cognitive/execution system into a real AI company.
The target is **not** to copy another repository. The target principle is to organize work around
real responsibility boundaries: a CEO/orchestrator, departments, specialist roles, capabilities and
skills, evidence and sources, independent review, company memory, and controlled execution.

## Non-negotiable principles

1. Preserve the existing SHURY cognitive core and `Arabic-Retrieval-v1.0` path.
2. Do not create an agent merely because a topic sounds different. A role must own a stable responsibility boundary.
3. Prefer structured contracts over sentence-specific rules.
4. Ownership must be explicit and fail-closed when it is ambiguous.
5. Producer and reviewer must be independent.
6. Department execution must use isolated task context and explicit handoffs.
7. Parallelism is opt-in and should follow task structure; more agents are not automatically better.
8. Company knowledge and execution state are different things.
9. Company memory must distinguish durable organizational knowledge from temporary task state.
10. Every milestone ends with a regression gate and a runnable artifact.

## Master roadmap

| Phase | Name | Objective | Status |
|---|---|---|---|
| C0 | Baseline | Freeze the known-good canonical runtime and V27 behavior | Done |
| C1 | Organization Core | CEO, departments, roles, ownership, authority, independent reviewers | Done |
| C2 | Capability Synthesis | Map novel structured goals to organizational capabilities | Done |
| C3 | Department Context | Isolated task context, allowed references, least privilege | Done |
| C4 | Coordination | DAG, handoffs, dependency validation | Done |
| C5 | Scheduling | Safe serial/parallel execution | Done |
| C6 | Organization Blueprint | Single source of truth for departments and roles | Done |
| C7 | Skill & Competency Catalog | Bind capabilities to real skills, triggers, preconditions, outputs, verification | Done |
| C8 | CEO Team Formation | Choose the smallest effective team for a goal | Done |
| C9 | Delegation & Recovery | Re-delegate on measured failure without rewriting ownership facts | Done |
| C10 | Company Memory | Decisions, ownership, procedures, outcomes, evidence, lessons | Done |
| C11 | Evidence & Sources | Source registry and evidence policy integrated into departments/skills | Done |
| C12 | Governance | Authority, approvals, audit trail, reviewer independence, external action gates | Done |
| C13 | Company Evaluation | Multi-department, novel-goal, failure, saturation, and security benchmarks | Done |
| C14 | Multi-Horizon Company | Concurrent projects, reprioritization, workload, persistent employee identities | Done |
| C15 | Self-Improving Organization | Controlled skill acquisition, promotion, deprecation, and organizational evolution | Complete |
| C16 | Controlled Company Learning Loop | Measure post-change generalization and open governed rollback proposals | Complete |
| C17 | Evidence-Calibrated Workforce | Convert canonical runtime evidence into conservative competency signals for team selection | Complete |
| C18 | Adaptive Delegation & Load-Aware Routing | Rank already-qualified delegation candidates using evidence, current canonical load, risk, and cost | Complete |
| C19 | Capacity & Budget Guardrails | Enforce explicit preflight cost and capacity limits using canonical portfolio state without changing ownership or authority | Complete |
| C20 | Weight-Driven Policy Learning | Make learned action-value parameters the primary final policy basis after sufficient observed evidence, while retaining safe cold-start behavior | Complete |

## Historical implementation checklist — C11 Evidence & Sources

### To-do

- [x] Create one declarative organization catalog.
- [x] Load CEO, roles, and departments from that catalog.
- [x] Validate unique role/department ownership.
- [x] Validate parent/head/specialist relationships.
- [x] Validate reviewer boundaries.
- [x] Preserve the existing public `CEO`, `ROLES`, and `DEPARTMENTS` API.
- [x] Add structured competency metadata to every current skill is deferred to C7; no duplicate skill store is created in C6.
- [x] Source/evidence references remain in the dedicated evidence registry rather than the organization catalog.

### Gate

C6 is complete when:

- `OrganizationCatalog.load()` passes validation.
- `DEFAULT_COMPANY` is constructed only from the catalog.
- Existing Company/Cross-Department/Runtime regressions remain green.
- Removing or corrupting an owner relationship causes a deterministic validation failure.
- No sentence-specific routing rule is introduced.

## Current release phase — C20 Weight-Driven Policy Learning

C20 is complete on Company 23. The current release is `25.9.0-alpha1-company23`. After sufficient observed action-value evidence, final model-based policy selection uses learned action values as the primary selection basis; the prior fixed heuristic remains cold-start only. The release does not change ownership, authority, reviewer policy, or SkillBank lifecycle.

## Implementation order after C6

### C7 — Skill & Competency Catalog

Create a structured bridge:

`department → role → skill → capability → tool contract → evidence`

Do not duplicate the existing SkillBank workflow data. The Company layer references the SkillBank
rather than becoming a second skill store.

### C8 — CEO Team Formation

For a goal, the CEO chooses the smallest team whose declared competencies cover the required
work. Selection uses capability fit and verified SkillBank history, not department-name keywords.
The team decision is recorded in Company coordination and the Brain trace.

### C9 — Delegation & Recovery — completed

Track verified outcomes per role/capability. On failure, choose a different qualified specialist or
escalate. Ownership facts remain immutable during delegation.

### C10 — Company Memory — completed

Add durable organizational facts: decisions, ownership, successful procedures, failed approaches,
review findings, and cross-department lessons. Keep it separate from transient task context.

The implementation uses the existing canonical Memory store under an explicit company namespace; no second memory store is introduced.

### C11 — Evidence & Sources — completed

Attach source requirements to skills where an external authority settles a claim. Store references,
licenses, retrieval timestamps, content hashes and freshness metadata; do not reproduce protected source text.

The implementation adds a declarative Company source registry and skill-level evidence policies,
and the canonical Brain blocks completion when a research-oriented skill lacks required provenance.

### C12 — Governance — completed

Model authority and reviewer policy consistently across departments. External publication, destructive
operations and high-impact actions are explicitly gated by the runtime governance layer.

### C13 — Evaluation

Benchmark whether SHURY can form and run teams for goals it has never seen as a named workflow.
Measure outcome quality, unnecessary delegation, coordination overhead, review independence, and
failure recovery.

### C13 — Evaluation — completed

The Company evaluation suite is contract-level and intentionally independent of named Company
workflows. It covers single/two/three-department team formation, novel goals, wrong ownership,
ambiguous ownership, reviewer independence, evidence-backed recovery, saturated context isolation,
unnecessary delegation, and a canonical structured Brain delegation smoke. Readiness is fail-closed
and requires a 100% scenario pass rate, zero safety/ambiguity/reviewer/recovery/context failures,
and unnecessary delegation ≤5%.

### C14 — Multi-Horizon Company — completed

Support multiple active projects with isolated contexts and tiered memory, while tracking
interdependencies and reprioritization cost. Project state uses the canonical LearningStore; durable
organizational knowledge remains in CompanyMemory.

### C15 — Self-Improving Organization

Allow controlled addition and retirement of skills/roles only through evidence-backed governance and
regression gates.

## Research anchors

Google Research's 2026 controlled study of 180 agent configurations found that centralized
multi-agent systems can help strongly parallelizable tasks while degrading sequential tasks; this
supports SHURY's policy of using parallelism only when task structure justifies it. citeturn595866search0

Microsoft Research's 2026 CORPGEN work frames realistic corporate agents around persistent
identities, hierarchical planning, isolated sub-agents, tiered memory, and adaptation under
multi-horizon workloads. citeturn595866search1turn595866search2

Google's 2026 work on budget-aware tool use shows that token cost and tool-call cost should both be
considered when scaling agent execution. citeturn595866search4

The `headcount` repository is used as an organizational design reference for bounded responsibilities,
departments, skills, source references, and independent review. It is not a template to copy. Its
current README advertises 16 departments, 172 skills and 184 cited sources; its `sources/` catalog
maps authoritative external references to skills with explicit licensing and freshness metadata.
citehttps://github.com/cbrock84/headcount/blob/main/README.mdhttps://github.com/cbrock84/headcount/blob/main/sources/README.md

### C12 Governance — completed

Runtime governance is now a distinct authority layer between planning/context authorization and tool execution. High-impact actions require independent security review plus human approval; proposed/escalated authority requires approval; controlled action classes cannot execute silently; and every approval carries a deterministic action fingerprint.


### C18 — Adaptive Delegation & Load-Aware Routing

Add a deterministic routing controller that scores already-qualified candidates using capability fit,
verified organizational evidence, current active workload from the canonical Company portfolio, risk, and
cost. Load/evidence may change the choice among qualified candidates, but cannot create eligibility or
rewrite factual ownership. Recovery may use the same secondary ordering after a measured execution
failure; governance failures still escalate.

Gate: a less-loaded qualified specialist wins only when the structured ownership/capability constraints
remain satisfied, and no routing decision can bypass authority, reviewer, or SkillBank governance.


### C19 — Capacity & Budget Guardrails

C19 adds an explicit, caller-supplied execution budget as a preflight guard. Limits may constrain estimated plan cost, active tasks per specialist, and total active tasks. Measurements come from the canonical LearningStore and declared tool costs; if a constrained dimension cannot be verified, the guard fails closed. The guard never changes ownership, authority, reviewer policy, or SkillBank lifecycle.

Gate: a plan inside its declared limits proceeds unchanged; a plan outside its limits is rejected before execution, and unverifiable cost/capacity evidence is rejected.
