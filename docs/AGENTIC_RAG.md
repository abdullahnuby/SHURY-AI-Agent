# Layer 3 — Agentic RAG

The Layer 3 subsystem treats retrieval as a bounded control loop rather than a single search.

```text
query
  -> route
  -> split information needs
  -> retrieve
  -> score evidence
  -> check coverage
  -> refine query / escalate source class
  -> repeat within budget
  -> detect conflicts
  -> extract from evidence
  -> independently verify every claim/citation
  -> answer | partial | abstain
```

Local semantic retrieval uses `Arabic-Retrieval-v1.0`. Synthesis is extractive: claims must be recoverable from retrieved evidence, and the final answer renderer cannot invent unsupported prose.

The design emphasizes iterative retrieval, query decomposition, corrective retrieval, bounded orchestration, and claim-level evidence verification.
