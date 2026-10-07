# SHURY Company — C12 Governance

## Goal

Governance is the final deterministic authorization layer between a Company assignment and tool execution. Planning may propose work; governance decides whether that work may execute.

## Rules

- CEO-issued assignment is required.
- Department/specialist/skill/capability must match the current execution context.
- Reviewers cannot execute producer work.
- Medium/high/critical work carries independent security review through the Company assignment contract.
- High/critical actions must explicitly require human approval.
- `requires_approval`, `proposes`, `escalates`, `destructive`, `external-publication`, `privileged`, and `financial` actions require human approval.
- Approval is scoped to a SHA-256 fingerprint of `(task_id, tool, args)`.
- Governance denial is fail-closed and must not become a generic delegation/replan opportunity.
- Governance records decisions, approval requests, grants and denials in the canonical Brain trace.

## Research anchors

OWASP recommends minimum task-specific tool access, per-tool authorization, explicit authorization for sensitive operations, and protection against high-impact action abuse and approval manipulation. citeturn533695search2turn533695search13

Microsoft's 2026 Agent Control Specification describes portable runtime governance across agent lifecycles, while Microsoft guidance recommends human approval for consequential actions and explicit per-action authorization. citeturn533695search5turn533695search6turn533695search10

NIST continues to frame AI governance as a lifecycle risk-management activity and is developing a 2026 critical-infrastructure profile. citeturn533695search1turn533695search15
