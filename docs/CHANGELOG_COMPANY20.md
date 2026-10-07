# SHURY Company 20 — C17 Evidence-Calibrated Workforce

Version: `25.6.0-alpha1-company20`
Base: `25.5.0-alpha1-company19`

## C15 maintenance closure

Before: the legacy CLI still called governed C15 self-improvement APIs without the mandatory producer/authority inputs introduced by C15 Hardening.
After: promotion and acquisition commands require and pass `producer`; trust elevation is exposed as a separate governed CLI step; rollback requires explicit `actor` and `reason`. The command banner documents the governed forms.

No governance rule was bypassed and no hidden default producer/actor was introduced.

## C17 scope

C17 calibrates specialist competence from the canonical `LearningStore.company_delegation_evidence` table and uses that calibrated evidence only as a secondary team-selection signal.

### 1. Conservative competency profiles

Each specialist/capability/tool evidence row is converted into a profile containing attempts, verified successes/failures, observed success rate, conservative rate, and evidence state.

The conservative rate uses a 95% Wilson lower confidence bound. Sparse evidence therefore remains `insufficient_evidence` and cannot be treated as equivalent to repeated evidence.

### 2. Canonical-store discipline

C17 uses the existing `LearningStore`, `SkillBank`, and Company organization registry. No new persistence store was introduced.

The calibrator fails closed when a canonical learning store is not supplied.

### 3. Team-selection integration

When calibrated organizational evidence exists for a candidate, it is blended into the existing history score. Team size, capability coverage, and structured ownership remain primary; C17 evidence is only a quality tie-breaker.

C17 does not modify ownership, authority, reviewer policy, or SkillBank lifecycle state.

### 4. Operational surface

Added `/company-competency [capability]|[specialist]` to inspect the calibrated profiles from the canonical LearningStore.

### Safety boundary

C17 is advisory calibration plus deterministic selection scoring. It cannot promote, demote, trust, approve, rollback, or rewrite organizational ownership.

## Verification

- Company suite: `125 passed in 26.08s`
- Organization Core: `8 passed in 10.28s`
- Layer-5 canonical runtime: `1 passed in 9.96s`
- Real skill lifecycle: `4 passed in 7.83s`
- C18 + C16 + C15 CLI hardening + C17 + team regression: `34 passed in 15.48s`
- source compilation: `SOURCE_COMPILE_PASS`
- runtime DB artifacts: `APP_DATA_DB_CLEAN`

The full sequential runner timed out after the Company wildcard; all remaining gates were rerun individually and passed.
