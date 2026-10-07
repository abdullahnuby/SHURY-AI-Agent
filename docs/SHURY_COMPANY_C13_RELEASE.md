# SHURY Company 15 — C13 Company Evaluation

## Purpose

C13 is the first release gate that evaluates the organization as an organization rather than by a
named workflow. The suite exercises the Company contracts directly and keeps its oracles independent
of workflow names.

## Evaluation coverage

1. Single-department team formation.
2. Two-department coordination.
3. Three-department coordination.
4. Novel goal with structured capability requirements.
5. Wrong-owner governance denial.
6. Ambiguous capability ownership denial.
7. Producer/reviewer independence denial.
8. Evidence-backed failure and re-delegation.
9. Context saturation and dependency isolation.
10. Unnecessary delegation measurement.
11. Canonical structured Brain → Company delegation smoke.

## Readiness gate

Company readiness requires:

- 100% scenario pass rate.
- Zero governance safety violations.
- Zero ambiguous-ownership failures.
- Zero reviewer-independence failures.
- Zero recovery failures.
- Zero context-isolation failures.
- Unnecessary delegation rate <= 5%.

## Observed result for this release

```text
Cases:                       11
Passed:                      11
Pass rate:                   1.00
Mean score:                  1.00
Safety violations:           0
Ambiguous ownership failures:0
Reviewer failures:           0
Recovery failures:            0
Context failures:            0
Unnecessary delegation rate: 0.00
Company ready:               TRUE
Release allowed:             TRUE
```

## Interpretation

C13 does not claim that every natural-language goal is already solved. It proves that the
organization layer has a machine-checkable readiness gate and that its current contracts hold under
representative single- and multi-department conditions. Full NLP `/agent` end-to-end readiness remains
a separate environment-dependent gate because `sentence-transformers` / Arabic-Retrieval-v1.0 must be
present in the user's authoritative runtime.
