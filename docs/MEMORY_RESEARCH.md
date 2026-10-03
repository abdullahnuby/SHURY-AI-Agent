# Memory Research Basis — 2026

The V22.2 memory implementation was shaped by recent agent-memory work rather than a single framework.

## Design inputs

1. **Agent-native memory systems (2026)** — decomposes memory into representation/storage, extraction, retrieval/routing, and maintenance; reports workload-dependent trade-offs and favors localized maintenance over global reorganization for cost control.
   - https://arxiv.org/abs/2606.24775

2. **AgeMem (2026)** — treats STM/LTM management as agent actions: store, retrieve, update, summarize, discard. This informed the explicit lifecycle operations in this implementation.
   - https://arxiv.org/abs/2601.01885

3. **LongMemEval-V2 (2026)** — evaluates static state recall, dynamic state tracking, workflow knowledge, environment gotchas, and premise awareness. These became acceptance targets for the benchmark added here.
   - https://arxiv.org/abs/2605.12493

4. **Agent Memory Techniques (2026)** — practical taxonomy covering working, semantic, episodic, procedural, graph, routing, consolidation, forgetting/decay, and production/evaluation patterns.
   - https://github.com/NirDiamant/Agent_Memory_Techniques

5. **Zep / Graphiti** — motivates temporal relationships, episode provenance, valid/invalid intervals, and history-aware graph memory.
   - https://arxiv.org/abs/2501.13956
   - https://github.com/getzep/graphiti

6. **A-MEM / MemoryAgentBench** — motivates dynamic memory organization, evolving links/notes, test-time learning, accurate retrieval, long-range understanding and selective forgetting.
   - https://arxiv.org/abs/2502.12110
   - https://arxiv.org/abs/2507.05257

## Deliberate constraints

The core implementation remains standard-library-only and model/provider-independent. It therefore does not claim neural semantic understanding. Retrieval uses a hybrid deterministic ranker and keeps the interface isolated so an embedding provider can be introduced later without changing memory storage, provenance, lifecycle or tool contracts.
