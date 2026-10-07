# SHURY Agent Learning Curriculum

SHURY is treated as a newly initialized agent. Capability is accumulated through verified experience; passing a difficult task once does not imply mastery.

## Level 1 — Foundations

Use small, deterministic tasks that exercise one capability at a time:
- read a real local file
- inspect a project
- calculate
- perform a bounded web lookup
- save and retrieve a fact

Success requires actual execution and verification.

## Level 2 — Composed Work

After repeated verified Level-1 successes, use short multi-step tasks:
- inspect → test → report
- retrieve → summarize evidence → save artifact
- analyze → write report → verify artifact

The agent should learn workflow structure from verified outcomes rather than sentence examples.

## Level 3 — Research and Adaptive Work

Only after lower-level capabilities are stable, evaluate:
- multi-source research
- evidence comparison
- recovery and retries
- longer plans
- learned skill reuse

When evidence quality is insufficient, SHURY must report insufficiency or continue with a bounded recovery step. It must never claim completion from weak or irrelevant evidence.

## Level 4 — Generalization

Use unseen tasks, paraphrases, new entities, and new combinations of skills. Performance must be demonstrated on capability classes, not memorized prompts.
