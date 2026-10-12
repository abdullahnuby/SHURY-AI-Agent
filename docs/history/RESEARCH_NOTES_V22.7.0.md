# Research Notes — V22.7.0 Layer 4

Layer 4 is informed by 2026 work on state-centric world-model evaluation, action-conditioned transition prediction, long-horizon web simulators, and behavior/state consistency.

Key design decisions:
- Keep a typed explicit state representation instead of pretending a text transcript is the world.
- Treat observations as evidence and compare predicted vs actual transitions.
- Make foresight an explicit tool and keep it separate from execution authority.
- Measure state consistency and behavior consequences, not only single-step textual similarity.
- Keep learned/model-based prediction optional and fail-safe.

Primary references:
- AutoWorldModel-Bench (arXiv:2608.11216, 2026)
- WebWorld (arXiv:2602.14721, 2026)
- Computer-Using World Model, ICLR'26 Workshop
- Current Agents Fail to Leverage World Model as Tool for Foresight (arXiv:2601.03905, 2026)
- Beyond State Consistency: Behavior Consistency in Text-Based World Models (2026)
- Agent World Model, ICML 2026
