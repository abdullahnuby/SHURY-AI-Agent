# Research Notes — V20 — 2026-09-29

## Research signals incorporated

1. **Agentic-R (ACL Findings 2026)** treats passage utility as more than query similarity: local relevance and downstream answer utility are both important, with iterative improvement of retrieval. V20 translates the idea into transparent operational evidence scoring and source-use telemetry rather than model training. Source: ACL Anthology, `2026.findings-acl.785`.

2. **AgenticRAG (2026)** reports gains from iterative search, document navigation and targeted multi-query retrieval. V20 therefore treats research as a bounded multi-source acquisition loop rather than a single fixed retriever call.

3. **SPARKLE (ACL 2026)** separates retrieval policy from the generator/retriever and uses structured retrieval control. V20 introduces a deterministic source-policy layer, independent from the underlying fetch/RAG engines.

4. **AutoSearch (2026)** emphasizes minimal sufficient search depth and penalizing unnecessary search. V20 records novelty and source utility so future research can stop earlier when it is no longer acquiring new evidence.

5. **Anything2Skill (2026)** separates declarative evidence from procedural skill contracts and stores reusable procedural knowledge in a persistent SkillBank. V20 preserves that separation and adds a separate ResearchMemory so raw evidence does not pollute executable Skill state.

6. **SkillOpt (Microsoft Research, 2026)** frames skills as external trainable parameters and accepts edits only when evaluation improves. V20 keeps the same experimental principle: research-derived skills stay candidates and rely on differential evidence before lifecycle promotion.

7. **Agent Skills specification (agentskills.io)** uses `SKILL.md`, optional resources and progressive disclosure. V20 remains compatible with that package model and does not infer executable workflows from arbitrary web prose.

8. **Scientific Agent Skills (2026)** demonstrates a large procedural library organized as versioned skills with references and scripts. V20 uses the same separation of procedural knowledge, references and evidence provenance while keeping external skills quarantined.

## Implementation policy

- Current source evidence outranks historical source utility.
- Research memory is not a truth store; it is provenance-rich evidence memory.
- Novelty is a routing/efficiency signal, not correctness.
- External text cannot silently authorize commands, shell access or file mutation.
- A research candidate cannot become active merely because many pages repeat the same text; differential runtime evidence is still required.
