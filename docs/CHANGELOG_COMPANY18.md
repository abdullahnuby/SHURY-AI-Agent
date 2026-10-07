# SHURY Company 18 — C15 Hardening Pass

Version: `25.4.0-alpha2-company18`
Base: Company 17 / C15 FINAL (`25.4.0-alpha1-company17`)

## Scope

This patch is limited to the requested C15 hardening items. No C16 features were introduced.

### 1. Trust self-grant
- `propose_skill_acquisition` no longer accepts `trust_level`.
- Newly proposed Skills are always `quarantined`.
- Trust elevation to `local`/`trusted` requires `grant_skill_trust(...)`, a reviewer-class actor, and a non-empty reason.
- The trust grant is recorded in canonical `LearningStore` evolution events.
- `apply` accepts acquisition trust only when that governed trust-grant event exists.
- Regression test: `test_acquisition_cannot_self_grant_trust`, `test_trust_grant_requires_independent_reviewer_reason_and_event`, `test_apply_requires_governed_trust_even_if_skill_field_was_tampered`.

### 2. Producer/reviewer/approver separation
- All `propose_*` APIs now require a `producer` role key.
- Producer must exist in the Company registry and cannot be reviewer-class.
- Producer is persisted in every proposal payload.
- `security_review` and `approve` reject producer identity collisions and record rejection events.
- Missing/invalid producer fails closed.
- Regression test: `test_missing_producer_is_fail_closed_and_self_review_is_logged`.

### 3. Governed rollback
- `rollback_skill(key, *, actor, reason)` now requires Company CEO or `security:reviewer` and a reason.
- Rollback creates a canonical Company Change Proposal ledger record with `change_kind=skill_rollback`, `status=applied`, and before/after snapshots.
- Unauthorized actors receive `PermissionError`.
- Regression test: `test_rollback_requires_authority_and_creates_applied_change_record`.

### 4. Post-apply monitoring
- `apply` records a baseline Company evaluation and Skill success/failure snapshot.
- Applied proposals enter `monitoring` rather than silently ending at `applied`.
- `monitor_change(proposal_id)` compares the stored baseline with current Company/Skill performance and returns `keep` or `recommend_rollback`.
- Monitoring never performs rollback automatically.
- Regression test: `test_apply_enters_monitoring_and_monitor_never_rolls_back`.

### 5. Change-specific regression gate
- `skill_acquisition` now requires executable verification cases embedded in the Skill's `verification` contract.
- Verification cases execute against the runtime Tool registry in isolation.
- No verification cases or any failed case blocks the change.
- Regression records separate change-specific evidence plus Company evaluation before/after candidate activation.
- The gate requires both general Company release criteria and change-specific criteria.
- Regression tests: `test_regression_requires_executable_verification_cases`, `test_regression_records_change_specific_and_company_before_after`.

### 6. Smaller hardening fixes
- `apply` recomputes the approved payload fingerprint and rejects post-approval mutation.
- Company QA review no longer branches on operation names. Workflow-specific checks are selected from declared tools/assignments/reviewers, allowing a newly named operation to use the same contract without a sentence/operation allowlist.
- Pytest now redirects production database defaults into `tmp_path` and includes a runtime-artifact guard for `app/data/*.db`.
- Regression tests: `test_apply_rejects_tampered_payload_after_approval`, `test_review_uses_assignments_not_operation_name`, `test_company_suite_does_not_write_db_files_into_app_data`.

## Canonical storage preserved

No new learning/memory/skill store was introduced. The patch continues to use the existing `LearningStore`, `SkillBank`, and `CompanyGovernance` authorities.

## C16 status

C16 was not started by this patch.
