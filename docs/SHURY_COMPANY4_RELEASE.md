# SHURY Company 4 — Release

Version: `24.1.0-alpha1-company4`

## Purpose

Company 4 adds a generic executive decomposition layer above the existing deterministic plan. It does not replace semantic parsing, the Brain planner, tools, skills, memory, learning, verification, or `Arabic-Retrieval-v1.0`.

## Implemented

- `ExecutiveDecomposer` validates the Company task graph.
- Company tasks carry stable internal task IDs and department-head ownership.
- Cross-department dependencies become explicit `CompanyHandoff` records.
- Work is grouped into department workstreams.
- A deterministic topological scheduler exposes execution waves for safe parallel opportunities.
- Independent review obligations become explicit `ReviewGate` records.
- A deterministic critical path is exposed for executive visibility.
- Unknown dependencies, duplicate task IDs, self-dependencies, and cycles fail closed.
- Canonical Brain trace records `company_executive_decomposition`.
- Legacy runtime audit records the same decomposition summary.
- `/company-decompose <goal>` exposes the topology without executing the plan.

## Design boundary

The decomposer is sentence-independent. It consumes structured Company tasks and never inspects benchmark wording or workflow names. The existing semantic layer and planner remain responsible for turning user language into executable actions.

## Verification

- Organization + Company regression: `35 passed`
- Real planning/execution regression: `14 passed`
- `python -m compileall -q app`: PASS
- Dependency-cycle rejection: PASS
- Unknown-dependency rejection: PASS
- Canonical decomposition trace: PASS

## Known limitation

The full repository suite is not claimed green in this environment because the current container does not provide the full Arabic semantic model runtime used by the user's Windows environment, and unrelated legacy tests exist outside this Company release gate.

## Next

The next Company phase should move from **decomposing an existing executable plan** to **capability synthesis for novel goals**: CEO goal -> required capabilities -> candidate departments/specialists -> typed task graph -> executable planner handoff, with measured delegation cost and confidence.
