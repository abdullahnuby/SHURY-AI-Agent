# SHURY identity

SHURY is the stable product identity of the personal AI agent.

The identity is Egyptian-inspired in name and character, while remaining a modern AI product identity. It defines how the agent communicates and reasons; it does not grant permissions or represent a human person.

Identity is deliberately separated from the runtime and memory systems:
- `models.py` contains the typed identity contract.
- `profile.py` contains the default product persona and behavioral principles.

Identity must never grant tool permissions, mutate memory directly, or override policy.
User memories remain in the memory subsystem and are not copied into the identity profile.
