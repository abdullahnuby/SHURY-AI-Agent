# SHURY Company Roadmap

## Baseline

Release: `24.8.0-alpha1-company11`

The current Company Core is an organizational substrate above the existing deterministic Brain. It does not replace `Arabic-Retrieval-v1.0`, the cognitive kernel, the existing planner, skills, tools, memory, or verification layers.

## Company Core v1 — implemented in this release

### 1. Organization registry

Departments, roles, capabilities, expected effects, reviewers, and authority are declared as structured data. The runtime no longer maintains a tool-name-to-department routing table.

### 2. Evidence-based ownership

Routing precedence is:

1. skill ownership
2. atomic capability ownership
3. single-owner expected effects
4. explicit tool organizational declaration
5. tool capability ownership
6. fail closed

An unknown capability does not silently become Operations.

### 3. Specialist selection

The organization selects a specialist using the structured tool role when available, then exact skill/capability ownership, then the department's declared specialist roster.

### 4. Typed task and handoff contracts

Each plan step can become a `CompanyTask`. Dependencies that cross departments become explicit `CompanyHandoff` records carrying an observable contract: the producing task must complete and its observation must be available to the consuming department.

### 5. Independent review

QA and security remain independent review roles. Review state can consume the Company coordination object rather than inferring ownership from a workflow name.

### 6. Runtime traceability

The canonical Brain and the legacy runtime expose Company assignments and Company coordination in state/trace data. Replanning re-routes the current plan instead of retaining stale ownership.

## Phase 2 — Executive decomposition

**Implemented across Company 4–5.** The existing semantic/task planner remains the authority for turning a goal into executable plan steps. The Company layer now converts those typed steps into a CEO-visible organizational DAG without workflow-name routing.

Current contract:

`typed plan -> CompanyTask ownership -> cross-department handoffs -> workstreams -> execution waves -> review gates -> critical path`

The output is language-independent after semantic parsing and is validated before execution. Company 5 adds capability synthesis for genuinely novel goals where TaskIR is executable but the normal method planner produces no usable plan. The synthesis is exact-contract and fail-closed.

## Phase 2 status

Company 5 completes the bounded Phase-2 capability-synthesis slice. The CEO can now expose required capabilities, rank exact contract candidates, fail closed on unresolved capabilities, and build a provisional plan from TaskIR only when every capability has an exact executable tool contract. This does not replace the mature planner; it is a conservative fallback for structured novelty.

## Phase 3 — Department execution contexts

**Implemented in Company 6.** Every executable Company task now receives a task-scoped `DepartmentExecutionContext` containing its objective, assigned tool/capability/skill, owned capabilities, explicit dependency steps, inbound/outbound handoff ids, allowed input references, and a least-privilege tool whitelist containing only the current task's assigned tool.

Transient dependency references are fail-closed: `{{sN}}` may be resolved only when `sN` appears in the task's explicit dependency set. Raw prior task outputs are not copied into the persistent Company context; only structural output metadata is recorded. The context is exposed through a runtime `ContextVar` for the duration of the tool call and is cleared afterward. Durable user memory remains governed by the existing memory subsystem rather than being silently re-scoped to a department.

## Phase 4 — Coordination and scheduling

Use the task DAG to identify independent work for safe parallel dispatch, while preserving serial dependencies. Cross-department state must move through explicit handoffs rather than shared mutable scratch state.

## Phase 5 — Organizational memory

Introduce company-level memory categories for decisions, ownership, prior outcomes, reusable procedures, and department evidence. Keep optimization memory distinct from durable organizational memory.

## Phase 6 — Metacognitive delegation

Add a routing controller that scores candidate departments/specialists using capability fit, evidence quality, prior verified success, cost, risk, and current load. The controller may change delegation strategy after measured failures; it must not rewrite factual ownership rules.

## Phase 7 — Governance and release gates

Model authority as `autonomous`, `proposes`, and `escalates`. External publication, destructive operations, high-impact decisions, and security-sensitive actions should remain gated. Reviewers must remain read-only.

## Phase 8 — Company evaluation suite

Add evaluations for:

- single-department tasks
- two- and three-department tasks
- dependency ordering
- safe parallelism
- wrong-department attempts
- ambiguous ownership
- capability collisions
- reviewer independence
- failure recovery and re-delegation
- workload/context saturation

Every benchmark should record the assigned departments, specialist, dependencies, reviewer path, evidence, and final outcome.

## Research basis

The architecture is informed by current multi-agent systems research that consistently emphasizes hierarchy, modular specialists, task decomposition, memory/context control, and adapting orchestration to task structure rather than assuming more agents are always better.

- Microsoft Research, CORPGEN (2026): hierarchical planning, isolated sub-agents, tiered memory, persistent identities, experiential learning, and the effect of context saturation and dependency complexity on performance.
- Google Research, "Towards a science of scaling agent systems" (2026): multi-agent gains are sensitive to task structure; parallelizable work benefits more than strongly sequential work.
- AgentOrchestra (2025): central planning and specialist delegation for modular multi-agent execution.
- MetaCogAgent (2026): metacognitive self-assessment and adaptive delegation based on competence and history.
- `cbrock84/headcount`: organizational ownership, departmental charters, bounded write surfaces, source-of-truth discipline, and independent reviewer roles.

The research is guidance for architecture, not copied implementation content.

## Company 7 — Coordination & Scheduling

Implemented in Company 7. The Company DAG now feeds a deterministic scheduler that identifies
currently-ready work, packs independent `parallel_safe` tools into bounded execution batches, and
serializes approval-gated or resource-exclusive work. Runtime execution uses isolated per-task
state views for parallel-safe calls and merges only observations, structural context metadata, and
state facts back into the canonical Brain state. Parallelism is opt-in and fail-closed.


## Company 8 — Delegation & Recovery

Implemented in Company 11. The canonical Brain now records execution outcomes by capability,
department, specialist and tool in the existing LearningStore. On an execution or verification
failure, Company Recovery searches only already-qualified candidates for the same structured
capability and automatically re-delegates only when verified organizational success evidence exists.
Authorization, policy, approval and undeclared-context failures escalate instead of triggering a
delegation change. Organization ownership remains immutable.
