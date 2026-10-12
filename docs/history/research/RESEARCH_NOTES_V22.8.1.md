# V22.8.1 Research Notes — Self-Improvement

Layer 5 follows current 2026 findings that self-improvement should be evidence-driven rather than append-only: experiential reflection can produce transferable heuristics; skill evolution benefits from explicit verification and comparison of successful/failed trajectories; lifelong skill benchmarks show that usage alone does not imply utility; contrastive and replay-based evolution helps reduce harmful or overfit updates; and recent work emphasizes safe, staged promotion with rollback.

Primary references reviewed:
- SkillForge, arXiv:2608.24747 — continuously verified skills and evidence-based verification.
- SkillHEX, arXiv:2608.05628 — hypothesis-driven exploration and exploitation with falsifiable tests.
- GSE, arXiv:2608.06153 — skill relation graph, consolidation, replay-driven verification/generalization.
- SkillCAT, arXiv:2606.13317 — contrastive causal extraction, assessment-augmented evolution, topology-aware loading.
- TRACE, arXiv:2608.22793 — trajectory-contrastive evolution and consistency/limit awareness.
- SkillFlow, arXiv:2604.17308 — lifelong skill discovery/evolution benchmark and negative transfer observations.
- OpenSkill, arXiv:2606.06741 — open-world self-evolution with self-built verification anchors.
- PAST-Bench, arXiv:2608.04003 — tests whether retained experience actually improves future fresh-session tasks.
- BenchTrace, arXiv:2605.29225 — reflection diagnosis is a bottleneck; failures include forgetting and negative transfer.
- EDV, arXiv:2606.24428 — Execute-Distill-Verify separation to reduce self-confirmation bias.
- ICPO, ICLR 2026 — in-context policy optimization using multi-round feedback without weight updates.

## September 2026 refresh
- Agent Skill Evaluation and Evolution survey (arXiv:2606.11435): frames skill evolution as evaluation-driven across execution feedback, trajectory distillation, compression, and reinforcement learning; emphasizes richer skill-centric benchmarks.
- Ratchet / Self-Evolving Agents reference implementation: uses evaluation-before-training, snapshots, retirement, and persistence-gated rollback; retired skills retain evidence for rollback.
- SkillEvolBench: frozen deployment and context-shift tests show that experience-to-skill abstraction can discard useful contextual cues; more skills can also introduce procedural clutter.
- OpenSkill: open-world skill evolution constructs verification anchors and evaluates freshly initialized target agents rather than only the creator run.
- RethinkSkill: evidence suggests selected evolved skills frequently benefit from failed trajectories, while validation, robustness, test, and transfer rankings can disagree; promotion therefore requires multiple gates rather than one score.
