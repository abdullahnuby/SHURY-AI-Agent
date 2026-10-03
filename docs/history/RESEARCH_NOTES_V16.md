# Research Notes V16 — RAG, Algorithms, Data Analysis, Agents

Research reviewed on 2026-09-29.

## Key findings used in the implementation

### 1. Adaptive retrieval during reasoning
ReaLM-Retrieve (arXiv:2604.26649, Apr 2026) treats retrieval timing as a decision conditioned on uncertainty rather than a fixed pre-reasoning step. V16 translates the principle into evidence uncertainty and adaptive escalation after each retrieval strategy.

### 2. Adaptive query routing
AHR-style work (arXiv:2604.14222, Apr 2026) reports that no single retrieval paradigm dominates every query complexity tier. V16 therefore uses a deterministic portfolio instead of hard-coding one retriever for all queries.

### 3. Multi-hop and retriever/agent interaction
Agentic-R (arXiv:2601.11888, Jan 2026; GitHub 8421BCD/Agentic-R) optimizes retrieval for agentic multi-turn utility rather than only local similarity. V16 captures the local analogue with subquery decomposition, neighbor navigation, evidence gains, and strategy experience.

### 4. Current September 2026 RAG direction
KARE-RAG (Sep 2026 listings) emphasizes iterative evidence refinement, probes, and complementary passage selection. Q2D-Web (Sep 2026) focuses on evaluating first-stage retrieval for agentic RAG. Page-Aware RAG (arXiv:2609.34776, Sep 28 2026) reports that accurate page/chunk selection can matter more than semantic retrieval alone for document settings. V16 responds by treating structural/neighbor evidence as first-class retrieval strategies.

### 5. Agentic RAG with fail-closed verification
Adaptive Agentic RAG implementations on GitHub combine hybrid retrieval, reranking, evidence gating, targeted retry, and abstention. V16 keeps the same safety principle but implements it with local deterministic lexical/structural algorithms.

### 6. Data-agent evaluation
DataSpace (arXiv:2608.03451; GitHub HKUSTDial/DataSpace) emphasizes heterogeneous workspaces, complete evidence integration, deterministic evaluation, and the impact of harness/orchestration. V16 therefore records strategy, hop, evidence, and marginal gain as first-class trace data rather than reporting only a final answer.

## Deliberate non-adoptions

Dense embeddings, cross-encoders, LLM judges, RL fine-tuning, and external vector databases were not imported because the Personal Agent is intentionally model-free and standard-library-only. Their architectural lessons are translated into explicit local algorithms where possible.
