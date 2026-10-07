# SHURY Company 22 — C19 Capacity & Budget Guardrails

Version: `25.8.0-alpha1-company22`
Base: `25.7.0-alpha1-company21`

## Roadmap note

The pre-defined Company roadmap ended at C18. C19 was introduced as a new bounded milestone to close a concrete architectural gap exposed by C18: routing could rank load/cost but did not enforce caller-declared preflight limits.

## C19

Added `app/organization/capacity.py` with `ExecutionBudget`, `CapacityBudgetDecision`, and fail-closed `CapacityBudgetGuard`.

### Cost guard

Before: routing ranked cost but did not enforce an explicit execution budget.
After: callers may set `max_plan_cost`; the guard resolves declared tool cost for every assignment and rejects the plan before execution when the limit is exceeded. Missing/unverifiable tool cost fails closed.

### Capacity guard

Before: C18 observed active workload only as a routing signal.
After: callers may set `max_active_tasks_per_specialist` and/or `max_active_tasks_total`; the guard reads active canonical Company portfolio tasks from `LearningStore` and rejects capacity overflow before execution.

### Integration

`SHURYCompany.route_plan()` accepts optional `budget` and `learning_store`. Existing callers without a budget retain the prior route behavior.

### Safety boundaries

- No ownership mutation.
- No authority mutation.
- No reviewer-policy mutation.
- No SkillBank lifecycle mutation.
- No new persistence store.
- No LLM or Arabic-Retrieval change.
- No sentence-specific or operation-name routing.
