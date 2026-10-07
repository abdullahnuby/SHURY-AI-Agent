# Company 15 — C13 Company Evaluation

- Added contract-level Company evaluation suite independent of named workflows.
- Added scenarios for single/two/three-department team formation and novel structured goals.
- Added fail-closed checks for wrong ownership, ambiguous ownership, and producer/reviewer collisions.
- Added evidence-backed failure/re-delegation evaluation.
- Added context saturation/isolation evaluation.
- Added unnecessary delegation metric and Company readiness release gate.
- Added canonical structured Brain delegation smoke to Company readiness.
- Added `/company-eval` CLI command.
- Declared organization ownership for research execution tools used by Company routing.

Gate: 10 Company contract scenarios + canonical Brain delegation, zero critical failures, and
unnecessary delegation rate <= 5%.
