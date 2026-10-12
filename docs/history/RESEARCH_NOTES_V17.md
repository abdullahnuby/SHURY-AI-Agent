# V17 Research Notes — Internet + RAG + Data + Development

Date: 2026-09-29

## Research reviewed

1. **Data Agents: Agentic Data Systems** (arXiv:2609.24137, 2026-09-21). Key ideas: semantic data organization, semantic operators, agentic orchestration, feedback-driven refinement, memory and proactive adaptation.
2. **Page-Aware RAG** (arXiv:2609.34776, 2026-09-28). Key idea: retrieval quality can depend on locating the correct page/section, not only semantic similarity.
3. **Fetch-then-Explore** (arXiv:2608.02097, 2026). Key idea: decouple selection from extraction and maintain a persistent workspace while the agent explores evidence.
4. **Retrieval as Reasoning / LLM-Wiki** (arXiv:2605.25480, 2026). Key idea: search/read/follow-link operations and persistent correction structures are closer to agent-native retrieval than flat lookup.
5. **Superintelligent Retrieval Agent** (arXiv:2605.06647, 2026-08-24). Key idea: query vocabulary enrichment and corpus statistics can improve lexical retrieval without retriever fine-tuning.
6. **The Tool Illusion** (COLM 2026 / arXiv:2604.03465). Key idea: tool use in web agents needs controlled, comparable evaluation; more tools do not automatically imply better behavior.
7. **Self-Evolving Coding Agents** (arXiv:2608.03392, 2026-08-04). Key idea: repository context, executable feedback and reusable experience are core signals for software-agent adaptation.
8. **Test-Driven Approaches to Software Engineering with LLMs** (arXiv:2609.12012, 2026-09-10). Key idea: test validity, feedback use and evaluation independence must be separated from “test passed”.
9. **Toward Secure LLM Agents** (arXiv:2606.10749, 2026-08-23). Key ideas: explicit trust boundaries, privilege control and provenance-aware persistent state.
10. **SafeSearch** (arXiv:2509.23694, published/updated 2026). Key idea: connecting agents to the internet creates a new threat surface; safe search needs independent evaluation and sandboxing.
11. **AgenticRAG / Adaptive Agentic RAG** GitHub implementations: hybrid retrieval, evidence gating, safe abstention, adaptive recovery.
12. **DataSpace** GitHub/evaluator: heterogeneous workspaces and exact verifiable evaluation for agent outputs.
13. **Agentic-R / Search-R1** GitHub: retrieval quality as an agentic objective with explicit retrieval rewards.

## V17 implementation decisions

- Add **public HTTP(S) GET** through a centralized gateway rather than allowing arbitrary network calls inside tools.
- Re-validate every redirect destination and block loopback/private/link-local/reserved addresses.
- Respect `robots.txt`, apply host rate limiting and hard response/latency/redirect budgets.
- Add first-class **arXiv** and **GitHub** research APIs so “newest research” and “learn from open-source projects” do not depend solely on general web search.
- Store all fetched sources with SHA-256 and URL provenance, then feed them into local deterministic RAG.
- Treat external documents as evidence; do not turn source rank into truth probability.
- Add deterministic repository inspection and manifest-derived build/test commands.
- Execute build/test commands without a shell and require approval because they can execute project code or mutate build artifacts.
- Make planner intent priority explicit so “search the internet/latest research” beats cheaper generic note/RAG matches when both match the phrase.

## Known limitation

The build environment used for verification has outbound DNS/network access disabled. Therefore the live network path is implemented but was validated with deterministic network fakes and security/unit tests, not by claiming a live external HTTP success from this environment. The real runtime performs public DNS resolution and HTTPS/HTTP requests on the user's machine/environment where networking is available.
