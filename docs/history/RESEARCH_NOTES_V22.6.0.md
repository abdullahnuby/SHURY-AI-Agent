# Research Notes — V22.6.0 Layer 3

Reviewed directions:

1. Microsoft Research AgenticRAG (May 2026): search/find/open/summarize tools, iterative retrieval,
   navigation, multi-query retrieval, and an agentic harness over existing search infrastructure.
2. "From Retrieval to Action: A Survey of Agentic RAG" (Sep 2026): large 2026 corpus; frames the
   field around planning retrieval, external tools, evidence verification, and self-correction.
3. "Agent-Orchestrated Adaptive RAG" (Jun 2026): dynamic decomposition + iterative retrieval +
   bounded reflection; emphasizes that agentic enhancements should be cost-aware and selective.
4. CRAG: lightweight retrieval evaluation followed by corrective actions and web fallback when
   retrieved evidence is weak.
5. Verified-citation implementations and EviGraph (2026): citations should be verified at the
   claim level, evidence provenance should be explicit, conflicts should remain visible, and
   evidence state should drive the control flow.
6. RAGChecker (2024): retrieval and generation need separate, fine-grained diagnostics.
7. GraphRAG (Microsoft): graph structures help with global/relational questions over corpora.

Implementation consequences for this project:

- keep the existing deterministic retrieval backend;
- add an explicit agentic orchestration layer around it;
- route to local/web/hybrid sources adaptively instead of always doing the same work;
- track coverage per information need;
- preserve source hashes and provenance;
- refuse unsupported model claims;
- surface contradictions rather than silently resolving them;
- keep hard budgets and fail-closed behavior.

Limitations intentionally left for later layers/iterations:

- no mandatory dense embeddings or cross-encoder dependency;
- no multimodal/page-layout graph yet;
- no learned retrieval policy;
- no full semantic entailment model unless an external provider is available.
