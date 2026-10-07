# SHURY Company — C9 Delegation & Recovery

## Goal

When a Company-assigned task fails, SHURY must not randomly hand the work to another tool or
specialist. Recovery must use the same organizational ownership facts that were used for the
original delegation, plus verified execution evidence accumulated by the existing LearningStore.

## Runtime contract

`CompanyRecoveryManager` classifies the failure before changing delegation.

- Execution and verification failures may trigger recovery evaluation.
- Authorization, policy, approval, context, and dependency failures escalate without changing ownership.
- A recovery candidate must already be qualified for the same structured capability by the OrganizationRegistry.
- The candidate must accept the failed action's arguments.
- Automatic re-delegation requires at least one verified organizational success for that candidate.
- Organization ownership is never rewritten by recovery.
- Company-owned actions do not fall back to an unrelated generic replan after recovery has been evaluated.

## Evidence

The existing `LearningStore` now records bounded delegation evidence by:

`capability + department + specialist + skill + tool`

The evidence tracks attempts, verified successes, verified failures, duration, last failure class,
and the last run. This is learning/execution evidence only; it is not user memory and not a source of
organizational ownership truth.

## Canonical trace

The Brain emits:

- `company_recovery_decision`
- `company_redelegated`
- `company_recovery_escalated`

The final `company_coordination` object retains recovery decisions and active redelegations.

## Gate

C9 passes when a failed Company action either:

1. re-delegates to an already-qualified same-capability candidate backed by verified success evidence; or
2. escalates without changing ownership when no safe evidence-backed alternative exists.

No sentence-specific rule is used.
