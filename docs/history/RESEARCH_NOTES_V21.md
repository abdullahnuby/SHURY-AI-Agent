# V21 Research Notes

Date: 2026-09-29

## Research-driven changes

1. **Repo-To-Skill / AREX-Skill (arXiv 2609.02749)**: repository know-how is distilled into compact, verified skills; the published library reports 5,000+ skills from 1,000 repositories and a progressive router. V21 adopts the supply-chain idea while keeping external skills quarantined.
2. **MUSE-Autoskill**: skills need creation, memory, management, evaluation, and refinement as a lifecycle. V21 adds admission/audit/refresh/trust state and durable provenance.
3. **SESA**: failures can be distilled into skill cards and used to drive future search. V21 prepares the acquisition layer so future runtime failures can feed candidate-skill generation without auto-activation.
4. **Agentic-R / SE-Search / RAGRouter-Bench / AutoSearch**: retrieval should be adaptive, iterative, and evaluated for answer-level utility and cost rather than similarity alone. V21 keeps discovery separate from execution and adds route-first progressive disclosure.
5. **OpenViking / agentic memory systems**: skills, memory, and knowledge benefit from structured hierarchical organization instead of one flat index. V21 records area/family routing metadata and keeps a durable skill registry.
6. **Data-analysis skills**: trustworthy analysis skills emphasize validation, traceability, reproducibility, and independent review. V21 does not invent workflow steps from prose; future data-analysis skill imports must pass the same schema/security gate.

## Safety boundary

Remote repository content is untrusted input. Acquisition is bounded, validation is mandatory, workflow execution is registry-gated, and trust promotion requires explicit approval.
