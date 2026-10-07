# SHURY Progressive Agent Training Curriculum

SHURY remains in local training mode until capability evidence is earned on progressively harder, unseen tasks. The current curriculum is deliberately practical and avoids academic/open-world tasks before the foundations are reliable.

## Completed user-acceptance levels

- Level 1: workspace inventory — PASS
- Level 2: deterministic data analysis — PASS
- Level 3: requested-metric extraction and source verification — PASS
- Level 4: group aggregation → comparison → decision → verification — PASS

## Level 5 (current)

File organization is the first capability that changes filesystem state. It requires:

- observation from a single snapshot
- generic type classification
- explicit approval
- no overwrites
- state change
- SHA-256 conservation
- count conservation
- artifact creation and reread

The Level 5 acceptance task must be run by the user on a fresh workspace state. Passing the implementation tests alone does not close the training gate.

## Before Web/Telegram

The agent must later demonstrate transfer on unseen local tasks, composed workflows, recovery, and safety. Only after those gates pass should an external transport be allowed to submit goals to the canonical runtime. Telegram/Web will never receive a privileged execution path around Brain, Skills, policy, approval, verification, or memory ownership.
