# Personal Agent V17 Verification

Date: 2026-09-29
Version: 17.0.0

## Regression
- Full pytest suite: 135 passed, 0 failed.
- Python compileall: passed.

## Historical benchmarks
- V10: 5/5
- V11: 5/5
- V12: 5/5
- V13: 7/7
- V14: 6/6
- V15: 6/6
- V16: 6/6
- V17: 10/10

## V17 routing checks
- `Search For The Newest Research For RAG and Algorithms and Data Analysis And Agents in Web and Github` -> `internet_research`
- `search the internet for latest RAG research` -> `web_research`
- `أحدث أبحاث RAG` -> `arxiv_research`
- `github research HKUSTDial/DataSpace` -> `github_research`
- `rag what requires approval` -> `rag_query`
- `search notes deployment` -> `search_notes`

## Security / execution boundaries
- Network gateway permits HTTP(S) public endpoints only.
- Ports restricted to 80/443.
- Private, loopback, link-local, multicast, reserved and unspecified addresses rejected.
- Redirect targets are revalidated before following.
- robots.txt checked before fetch; crawl-delay honored where present.
- Host-level rate limiting and bounded timeout/response size are enforced.
- Dataset downloads require approval.
- Project build/test execution requires approval and uses shell=False with manifest-derived commands.
- External web/GitHub/arXiv content is treated as untrusted evidence, not executable instructions.

## Network verification limitation
The build sandbox used for this verification has outbound DNS/network disabled. Therefore live external fetches could not be executed from the sandbox. The network implementation was validated with deterministic fake gateways plus URL/SSRF/security tests. Production execution requires a runtime environment with outbound HTTPS/DNS access.

## Clean-room package
The final package is built from the cleaned project tree without runtime RAG/network databases, caches, pytest caches, or Python bytecode.
