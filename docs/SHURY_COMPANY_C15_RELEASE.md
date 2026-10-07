# SHURY Company 17 — C15 Release

## Release

- Version: `25.4.0-alpha1-company17`
- Baseline: `SHURY-AI-Agent-COMPANY16-C14-FINAL.zip`
- Scope: Controlled Self-Improvement

## Implemented

1. Company change proposal ledger built on the canonical `LearningStore`.
2. Skill acquisition creates candidate-only entries; untrusted sources remain quarantined.
3. Promotion and deprecation require proposal state rather than direct lifecycle mutation.
4. Regression gate combines the Company Evaluation Suite with the existing Layer-5 self-improvement benchmark and change-specific evidence.
5. Independent reviewer-class security review and CEO approval are required before applying Company Skill changes.
6. Role/department/capability topology changes are staged proposals and cannot mutate the live catalog automatically.
7. Skill rollback uses the configured Company SkillBank and records the change in the canonical LearningStore.

## Verification

- Company suite: `125 passed`
- C15 focused tests: `10 passed`
- Layer-5 promotion tests: `12 passed`
- Skill lifecycle + recovery tests: `7 passed`
- `compileall`: PASS
- Company release gate: `company_ready=True`
- Self-improvement benchmark: `9/9 PASS`

The complete historical repository suite is not claimed here; unrelated legacy `/agent` NLP/planner tests remain outside the C15 gate.

## Safety contract

```text
learning signal
    -> candidate/proposal
    -> regression evidence
    -> independent security review
    -> CEO approval
    -> apply / stage
    -> monitor
    -> rollback when justified
```

No language-specific benchmark sentence is used to authorize a change. No new parallel memory or SkillBank is introduced.
