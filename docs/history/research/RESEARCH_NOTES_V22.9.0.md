# Research Notes V22.9.0 — Evaluation Lab

The evaluation design follows current 2026 practices observed in AgentCompass, Inspect, OpenAI agent-evaluation guidance, Odysseys, TUA-Bench, ATBench, and SWE-Bench Pro Verified. Common themes are: trajectory-level evidence, deterministic checks before model judges, realistic long-horizon tasks, repeated trials for stochastic agents, environment isolation/frame-condition checks, safety-focused scoring, explicit failure attribution, and benchmark/task versioning.

External research reviewed for this release:
- OpenAI agent workflow evaluation guidance: traces + graders + datasets + eval runs.
- Inspect AI: multi-turn/tool-use evaluation, versioned evals, retries, sample IDs and reproducible runs.
- Odysseys (2026): long-horizon web tasks need graded rubrics and trajectory efficiency, not binary pass/fail alone.
- TUA-Bench (2026): execution-based evaluation in deterministic real terminal environments across broad workflows.
- ATBench (2026): trajectory-level safety evaluation across risk source, failure mode, and harm dimensions.
- SWE-Bench Pro Verified (2026): anti-hacking controls and task-quality verification are necessary for trustworthy agent benchmarks.
