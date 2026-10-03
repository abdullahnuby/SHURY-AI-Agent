"""Short-term conversational state, separate from persistent memory."""
from dataclasses import dataclass, field
from app.intelligence.understanding import Understanding

@dataclass
class Session:
    turns: list[Understanding] = field(default_factory=list)
    last_goal: str = ""
    last_outputs: dict = field(default_factory=dict)

    def observe(self, u: Understanding, goal: str, outputs: dict | None = None):
        self.turns.append(u)
        self.turns = self.turns[-12:]
        self.last_goal = goal
        if outputs is not None:
            self.last_outputs = dict(outputs)

    def recent_intents(self):
        return [u.top_intent.name for u in self.turns if u.top_intent]
