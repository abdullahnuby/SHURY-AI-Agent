# Personal Agent V17 Architecture — Internet, Research, Data Acquisition & Development

V17 gives the deterministic agent a bounded public-network capability and connects it to the existing RAG/data/development loop.

```text
User Goal
   ↓
Intent-aware Planner
   ├─ local RAG
   ├─ web research
   ├─ arXiv research
   ├─ GitHub discovery/research
   ├─ direct HTTP fetch
   ├─ bounded dataset download
   └─ project inspect/build/test
   ↓
Network Policy Boundary
   ├─ HTTPS/HTTP only
   ├─ DNS resolution + private/reserved IP blocking
   ├─ explicit port limits (80/443)
   ├─ redirect re-validation
   ├─ robots.txt policy
   ├─ per-host rate limit
   ├─ response/time/redirect budgets
   └─ immutable hash + URL provenance
   ↓
Acquisition
   ├─ Web search → fetch candidates
   ├─ arXiv API → newest-first papers
   ├─ GitHub API → repo metadata/tree/raw files
   └─ Remote CSV/JSON/text download
   ↓
Normalization
   ├─ HTML → text
   ├─ JSON → canonical text
   └─ GitHub/ArXiv records → provenance-rich documents
   ↓
Knowledge Integration
   └─ local deterministic RAG
       ├─ lexical indexing
       ├─ adaptive retrieval portfolio
       ├─ evidence set-cover
       ├─ evidence gate
       └─ citation-bound extraction
   ↓
Learning
   ├─ retrieval strategy experience
   ├─ source/fetch history
   └─ persistent research knowledge
   ↓
Development Loop
   ├─ inspect repository manifests
   ├─ derive safe build/test commands
   ├─ git status / diff-check
   └─ execution feedback becomes durable evidence
```

## Security boundary

The network layer is intentionally read-oriented. It does not execute remote code, submit forms, authenticate to third-party accounts, bypass robots restrictions, scan networks, or follow redirects into private/reserved address space. Dataset download is bounded and approval-gated because it changes local storage. Build/test execution is approval-gated and uses argv with `shell=False`; commands are selected from detected project manifests.

## Learning boundary

External content is treated as **evidence**, not truth. RAG indexes URL, title, source type, SHA-256 and fetch metadata. Strategy learning can reuse operational history, but live evidence remains the primary signal. Build/test success is verified from exit codes and non-empty check reports; network retrieval success does not imply factual correctness.

## Why this architecture

Recent research increasingly treats retrieval as an adaptive reasoning process, persistent workspace exploration, and evidence-aware control rather than a single retrieve-then-answer call. V17 implements these ideas in a model-free way where possible: explicit strategy routing, provenance, bounded retries, deterministic ranking, and executable validation.
