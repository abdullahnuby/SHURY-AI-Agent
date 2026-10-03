# Personal Agent V18 — Adaptive Skills + Execution Planning

V18 extends the V17 network-aware agent with a verifier-backed procedural SkillBank and an execution-time policy that adapts tool choice, retry/replan decisions, and search depth from live evidence and observed outcomes.

## Core loop

```text
Goal
 ↓
Intent / Goal model
 ↓
Generic planner portfolio
 +
Verified Skill candidates
 ↓
Current-world certification
 ↓
Adaptive plan selection
 ↓
Policy / Approval
 ↓
Adaptive execution controller
 ├─ reliability-aware tool scoring
 ├─ information-value bias
 ├─ minimal-sufficient search stopping
 ├─ retry / replan decision
 └─ path-centric outcome logging
 ↓
Independent verification
 ↓
Durable effect ledger
 ↓
Verified run → Skill compiler
 ↓
SkillBank lifecycle
 candidate → approved → active → candidate/deprecated
```

## Skill contract

Each Skill contains:

- invocation triggers
- contraindications
- preconditions
- ordered tool workflow
- termination rule
- expected outputs
- evidence/provenance
- confidence
- success/failure counts
- version and lifecycle status

A Skill is never executable by itself. At runtime its tool sequence is reconstructed from the live goal, validated against the current registry, and certified against the current world.

## Skill evolution policy

- successful verified workflows can be compiled into `candidate` skills
- 3 independently recorded successful outcomes with no failures promote a candidate to `active`
- an active skill with failure rate >= 40% after at least 3 observations is demoted to `candidate`
- activation/deprecation can also be explicitly controlled
- current plan evidence can reject a stale skill; experience is a secondary signal

This mirrors current skill research emphasizing structured contracts, lifecycle management, verifier-backed experience, and execution-time intervention while remaining deterministic and model-free.

## Adaptive execution

The controller computes a bounded utility from:

- historical tool reliability posterior
- tool cost and duration
- risk / approval cost
- idempotency
- estimated information value

After each tool result it emits a decision among `execute`, `retry`, `replan`, and `stop`. A result with strong verification and low marginal evidence gain can terminate an exploratory path, following the minimal-sufficient-search principle.

## Development learning

V18 can compile a project-specific candidate skill from the detected project stack and manifest:

`inspect_project → git_status → approved check_project`

The resulting skill stores the detected stack and commands as evidence while remaining inert until activated by the skill lifecycle.

## Safety

External content remains untrusted evidence. Skills never inherit executable shell content from web pages or repositories. Project checks use the existing manifest-derived, `shell=False`, approval-gated development tools.
