# 100-Scenario Real-User Hardening

## Final gate

- **100 / 100 scenarios passed**
- **0 / 100 failed**
- Three consecutive full campaign runs produced **100 / 100**
- Full project regression: **337 passed, 0 failed**
- `compileall`: **OK**
- Every scenario ran in an isolated temporary sandbox with independent memory, RAG, learning/skills state and workspace.

## What the campaign tests

The suite deliberately mixes positive, negative and multi-turn sessions. It covers arithmetic and social interaction; semantic memory; corrections and session boundaries; RAG indexing/querying; deterministic data analysis; filesystem safety and bounded reads; project inspection and build/test checks; web/arXiv/GitHub/skill routing; world-model simulation; and evaluation/status commands.

## Progressive results

The initial red-team pass exposed **27 failing cases (73/100)**. After source fixes and scenario-spec corrections, the campaign progressed through **91/100**, **97/100**, and finally **100/100**. The final runner reproduced 100/100 again on subsequent clean processes.

## Runtime defects fixed

- Natural arithmetic phrases were routed to the calculator and negative/parenthesized expressions were evaluated correctly.
- Relative data-file paths and project paths now resolve inside the configured agent workspace instead of the process working directory.
- RAG databases can now be isolated per sandbox via `AGENT_RAG_DB`; RAG portfolio queries no longer get stolen by the generic `rag` matcher.
- Explicit GitHub repository search is separated from generic Agentic RAG; skill matching is separated from broad discovery.
- Memory/result routing and multi-turn session handling were verified inside the isolated campaign.
- Semantic-to-tool alignment was hardened for explicit low-risk requests without bypassing policy, approval or verification.
- Greetings are handled as social turns instead of planner failures.
- Negative filesystem/tool cases remain observable failures rather than false successes; approval rejection remains a cancellation.

## Test harness corrections

Several initial red cases were benchmark mistakes rather than runtime defects: expected failure statuses for malformed projects, explicit approval denial in a workspace test, and postconditions that used case-sensitive checks. These were corrected rather than weakening the agent to make them pass.

## Running locally

```powershell
py -m app.evaluation.real_user_100
```

Print the scenario catalog:

```powershell
py -m app.evaluation.real_user_100 --catalog
```

The runner writes `docs/evaluation/REAL_USER_100_REPORT.json` and `docs/evaluation/REAL_USER_100_SCENARIOS.json`.
