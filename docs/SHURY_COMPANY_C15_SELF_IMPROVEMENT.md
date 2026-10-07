# SHURY Company C15 — Controlled Self-Improvement

C15 adds an organizational change-control layer above the existing Layer-5 learning system.
Learning remains advisory. A learned Skill or organizational change becomes a durable Company
change only through a proposal, evidence, regression gate, independent security review, CEO approval,
and (for applicable Skills) an explicit apply step.

## Lifecycle

```text
experience
  -> Layer-5 candidate/evaluation
  -> Company change proposal
  -> regression gate
  -> independent security review
  -> CEO approval
  -> apply / stage
  -> monitor
  -> rollback when justified
```

## Supported change classes

- `skill_acquisition` — create a candidate Skill in the existing SkillBank; external or untrusted sources remain quarantined.
- `skill_promotion` — propose moving an existing candidate/approved Skill to active only after positive differential evidence and Company regressions.
- `skill_deprecation` — propose retiring an active Skill only when lifecycle evidence recommends demotion.
- `role_change`, `department_change`, `capability_change` — staged organizational proposals; they do not mutate the live organization catalog automatically.

## Safety invariants

- No proposal is applied from a learning signal alone.
- Regression evidence is required before CEO approval.
- Security review must be performed by a reviewer-class role and cannot be the producer.
- Only the Company CEO may approve a change.
- Untrusted acquired Skills cannot become active.
- Organizational topology changes are staged and require the catalog change process.
- Skill rollback preserves evidence in the canonical LearningStore.
- The existing SkillBank and LearningStore remain the sources of truth; no parallel lifecycle store is introduced.

## CLI

```text
/company-improve-skill <skill-key>
/company-acquire-skill <key>|<name>|<source>|<json-workflow>
/company-changes
/company-change-regression <proposal_id>
/company-change-review <proposal_id>|approve|<reason>
/company-change-approve <proposal_id>
/company-change-apply <proposal_id>
/company-skill-rollback <skill-key>
```

## Research alignment

Recent 2026 work on self-improving agents emphasizes controlled evolution, separating the update
operator from its evaluation signal, and preventing agents from optimizing weak harnesses. SkillOpt
shows that bounded, auditable Skill edits with validation and rejected-edit feedback can improve
agents without changing model weights. Studies of recursive self-improvement also show that repeated
local test success is not sufficient evidence that the target capability improved, so SHURY requires
Company regressions and lifecycle evidence in addition to candidate creation.
