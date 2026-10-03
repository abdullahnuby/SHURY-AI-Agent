# V12 Research Notes

## What changed in the research basis
1. DSAgentBench (2026) emphasizes end-to-end data-science workflows in real environments and deterministic evaluation of analytical correctness, visual outputs, and model performance. We translate the deterministic-evaluator principle into local evidence verification.
2. DataSpace (KDD 2026) emphasizes heterogeneous workspaces and verifiable tabular results. V12 keeps the local file boundary explicit and fingerprints every dataset.
3. DataMind/DataPRM (2026) highlights silent analytical errors that do not raise interpreter exceptions. V12 adds independent statistical cross-checks and sanity-oriented evidence, not LLM judging.
4. CIPHER (2026) decouples exploration from selection. V12 applies this idea as an algorithm portfolio: several audited methods exist, then the data-dependent selector chooses the appropriate one.
5. MLEvolve (2026) uses graph search, retrospective memory, and progressive exploration/exploitation. V12 imports only the general search/experience idea without any LLM or generated code; existing agent planning remains deterministic.
6. EvoDS (KDD 2026) treats skills and context as evolving capabilities. V12 advances the local analogue through explicit reusable analysis methods and provenance.

## Deliberately not adopted
- LLM-based skill synthesis, code generation, or model-generated critique.
- External vector databases or embeddings.
- Stochastic online learning in the critical execution path.

The goal is a reproducible, inspectable, model-free agent rather than a simulated LLM agent.
