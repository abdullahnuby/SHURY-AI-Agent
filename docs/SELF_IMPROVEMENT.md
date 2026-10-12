# Self-Improvement — Layer 5

Layer 5 is an evidence-driven learning subsystem. It records execution experiences, diagnoses failures, extracts bounded lessons, generates candidate procedural skills from repeated verified workflows, replays candidates counterfactually, and promotes only when multiple evidence gates pass.

## Runtime loop

```text
run
  -> observe experience
  -> diagnose
  -> compare success/failure trajectories
  -> create advisory lesson
  -> repeat-verified workflow
  -> candidate skill
  -> counterfactual replay
  -> promotion gate
  -> active
  -> monitor
  -> rollback if needed
```

## Safety invariants

- Learned guidance is untrusted advisory context.
- Skills never bypass policy, approval, tool contracts, verification, or trust level.
- Replay never executes side-effecting tools.
- Candidate triggers are derived from normalized task families, not one-off argument values.
- Workflow dependencies are preserved when a trajectory becomes a candidate skill.
- Credential-like values are redacted from durable experience goals and task signatures.
- Reflection lessons require failed-step evidence; success-only reflections are retired.
- Promotion needs repeated verified success, contextual evidence, positive replay benefit, and no regression.
- Active evolving skills can be rolled back without deleting their evidence.

## Public surfaces

```text
/learning-status
/learning <goal>
/evolve <skill-key>
/rollback <skill-key>
/self-improvement-benchmark
```

## Storage

`AGENT_LEARNING_DB` stores experiences, lessons, replay evaluations, and evolution events. `AGENT_SKILLS_DB` stores the SkillBank. Set both explicitly in tests and deployments to isolate runtime state.

## Evaluation

Layer 5 is validated by full regression, failure→success real-user acceptance, procedural candidate generation, counterfactual replay, promotion/rollback gates, legacy lesson reconciliation, and the self-improvement benchmark.
