# V22 research-informed fixes

Sources consulted on 2026-09-29:
- Skill Is Not Document: query-conditioned skill routing and compatibility-aware two-stage retrieval (arXiv 2606.03565; latest version Aug 4 2026).
- Ratchet: outcome-driven retirement, active-cap and lifecycle hygiene for self-evolving skill libraries (arXiv 2605.22148; May 2026).
- MOSS: source-level self-evolution with replay validation and rollback (arXiv 2605.22794; May 2026).
- ATLAS / Adaptive Agentic RAG public implementations: hybrid retrieval, reranking, knowledge graph, evidence gates, fail-closed recovery and explicit evaluation harnesses.

Applied in V22:
1. Broader bilingual intent normalization and semantic capability fallback.
2. Fixed natural-language build/test routing and cwd path fallback.
3. Remote Skill manifest identity is now preserved through SkillBank import via `bank_key`.
4. Upstream content changes force quarantine and explicit re-approval.
5. Trust/status lifecycle is fail-closed; external skills cannot auto-promote.
6. Skill routing has a second-stage compatibility signal instead of pure trigger overlap.
7. Compound execution pipes outputs using explicit result/output language, not only Arabic positional cues.
8. Failed retries report total elapsed duration.
9. Resume audit duplicate removed.
