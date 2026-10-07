# SHURY Company — Company-0

## Purpose

SHURY is now modeled as an organization of deterministic specialist agents rather than one undifferentiated agent. The existing Brain remains the canonical execution authority; the company layer determines **who owns the work** and records the delegation chain.

This phase follows the organizational principles studied from `cbrock84/headcount`:

- one executive orchestrator above specialist agents;
- agents are separated by explicit ownership surfaces;
- builders and reviewers are distinct;
- reviewers are read-only and can stop work;
- one owner is authoritative for each class of capability/fact;
- delegation is explicit and inspectable.

## Current roster

```text
SHURY Company
└── executive:chief-executive
    ├── operations
    │   ├── operations:head
    │   └── operations:file-specialist
    ├── data
    │   ├── data:head
    │   └── data:data-analyst
    ├── research
    │   ├── research:head
    │   └── research:research-analyst
    ├── development
    │   ├── development:head
    │   └── development:project-engineer
    └── memory
        ├── memory:head
        └── memory:steward

Reviewers reporting directly to the CEO:
├── security:reviewer
└── qa:reviewer
```

## Runtime boundary

The company layer does not create a second NLP or execution engine.

```text
User
  ↓
Arabic-Retrieval-v1.0
  ↓
SemanticContract
  ↓
CEO / Company Router
  ↓
Department Head
  ↓
Specialist Agent
  ↓
Existing Skill contract
  ↓
Existing deterministic Tool
  ↓
Verification
  ↓
Reviewer evidence when required
  ↓
CEO result integration
```

## Execution mandate

The CEO issues a scoped `ExecutionMandate` after routing. A specialist can only receive the Skill owned by its department. A cross-department claim raises a permission error instead of falling back to another department. The mandate is organizational authority; the existing deterministic Tool/Skill execution and verification layers remain the runtime authority.

## Inspection commands

```text
/company
/company-route <goal>
```

`/company` prints the roster and surface validation. `/company-route` shows the department/specialist chain for one live goal.

## Phase-0 boundary

Company-0 does **not** enable Web or Telegram. Those are external communication channels and remain behind the training/readiness gate.

It also does not duplicate the Brain. Each department is currently a first-class **organizational role and delegation boundary** over the existing deterministic Skills. Later phases can add department-specific planners without changing the global execution authority.
