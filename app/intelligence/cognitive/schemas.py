COGNITIVE_BRIEF_SCHEMA = {
  "type": "object",
  "properties": {
    "goal": {"type": "string"},
    "task_type": {"type": "string"},
    "success_criteria": {"type": "array", "items": {"type": "string"}},
    "constraints": {"type": "array", "items": {"type": "string"}},
    "ambiguities": {"type": "array", "items": {"type": "string"}},
    "assumptions": {"type": "array", "items": {"type": "string"}},
    "subgoals": {"type": "array", "items": {"type": "string"}},
    "information_gaps": {"type": "array", "items": {"type": "string"}},
    "hypotheses": {"type": "array", "items": {
      "type": "object",
      "properties": {
        "statement": {"type": "string"},
        "evidence_needed": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number"}
      },
      "required": ["statement", "evidence_needed", "confidence"],
      "additionalProperties": False
    }},
    "strategy": {"type": "string", "enum": ["deterministic", "hybrid", "reactive", "research_first", "clarify"]},
    "risk": {"type": "string", "enum": ["low", "medium", "high"]},
    "confidence": {"type": "number"},
    "needs_clarification": {"type": "boolean"},
    "clarification_question": {"type": "string"},
    "first_action_hint": {"type": "string"}
  },
  "required": [
    "goal", "task_type", "success_criteria", "constraints", "ambiguities",
    "assumptions", "subgoals", "information_gaps", "hypotheses",
    "strategy", "risk", "confidence", "needs_clarification",
    "clarification_question", "first_action_hint"
  ],
  "additionalProperties": False
}

COGNITIVE_REFLECTION_SCHEMA = {
  "type": "object",
  "properties": {
    "progress": {"type": "number"},
    "goal_status": {"type": "string", "enum": ["progressing", "achieved", "blocked", "ambiguous"]},
    "new_facts": {"type": "array", "items": {"type": "string"}},
    "changed_assumptions": {"type": "array", "items": {"type": "string"}},
    "information_gaps": {"type": "array", "items": {"type": "string"}},
    "failure_class": {"type": "string"},
    "should_replan": {"type": "boolean"},
    "next_objective": {"type": "string"},
    "rationale_summary": {"type": "string"},
    "confidence": {"type": "number"}
  },
  "required": [
    "progress", "goal_status", "new_facts", "changed_assumptions",
    "information_gaps", "failure_class", "should_replan",
    "next_objective", "rationale_summary", "confidence"
  ],
  "additionalProperties": False
}


COGNITIVE_FINAL_SCHEMA = {
  "type": "object",
  "properties": {
    "goal_status": {"type": "string", "enum": ["achieved", "blocked", "ambiguous"]},
    "answer_supported": {"type": "boolean"},
    "missing_information": {"type": "array", "items": {"type": "string"}},
    "user_question": {"type": "string"},
    "rationale_summary": {"type": "string"},
    "confidence": {"type": "number"}
  },
  "required": ["goal_status", "answer_supported", "missing_information", "user_question", "rationale_summary", "confidence"],
  "additionalProperties": False
}
