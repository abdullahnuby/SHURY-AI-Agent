# SHURY Company — C12 Governance Release

## Release

`25.1.0-alpha1-company14`

## Scope

C12 makes governance a deterministic runtime authority layer between Company assignment/context authorization and tool execution.

## Implemented

- `app/organization/governance.py` — fail-closed action authorization.
- Risk classes: `low`, `medium`, `high`, `critical`.
- Governance action classes: `read-only`, `state-producing`, `controlled-side-effect`, `destructive`, `external-publication`, `privileged`, `financial`.
- CEO-origin, department, specialist, skill and capability consistency checks.
- Reviewer registry and reviewer-class validation.
- Producer/reviewer separation enforcement.
- Medium/high/critical actions require an independent security reviewer.
- High/critical actions require an explicit human approval contract.
- `requires_approval`, `proposes`, `escalates`, and controlled action classes require human approval.
- Approval requests carry SHA-256 action fingerprints over `(task_id, tool, args)`.
- Governance denial occurs before `tool.fn()` is invoked.
- Governance rejection is represented as an explicit refusal and cannot silently become a generic replan/redelegation opportunity.
- Canonical Brain trace events record decisions, approval requests, grants and denials.
- `/company-governance <goal>` inspects governance decisions before execution.
- Existing source registry now includes current OWASP and Microsoft governance references.

## Verification

- Company + organization + canonical runtime regressions: **124/124 PASS**.
- AST parsing: **449 Python files, 0 syntax errors**.
- Modified-module `py_compile`: PASS.
- Governance integration: high-impact denied before tool execution; approved controlled action executes and records approval events.

## Environment note

The full repository `compileall` sweep was not used as the release claim because the installed environment's sweep exceeded its execution limit. No syntax errors were found in the complete 449-file AST sweep, and all modified modules compile successfully.

The broader legacy full suite still contains pre-existing `/agent` NLP/planner failures outside the C12 governance surface; they are not hidden or counted as Company 12 passes.

## Design anchors

OWASP recommends minimum task-specific tool access, explicit authorization for sensitive operations, and controls against high-impact action abuse and approval manipulation. citeturn533695search2turn533695search13

Microsoft's 2026 Agent Control Specification and agent guidance emphasize runtime policy enforcement, per-action authorization, human approval for consequential actions, and evidence of what happened. citeturn533695search5turn533695search6turn533695search10

NIST continues to frame AI governance as a lifecycle risk-management function and is developing a 2026 trustworthy-AI critical-infrastructure profile. citeturn533695search1turn533695search15
