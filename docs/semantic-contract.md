# SHURY Unified Semantic Contract v1.0

## Producer

`app.intelligence.semantic.SemanticInterpreter.parse()` produces the retrieval-native `SemanticParse`. It uses the configured `omarelshehy/Arabic-Retrieval-v1.0` for semantic similarity when available and deterministic semantic rules around that retrieval layer; it does not generate responses.

`app.intelligence.semantic.contract.from_parse()` is the single translation point from `SemanticParse` into the typed `SemanticContract` consumed by the Brain boundary.

## Consumer

The canonical consumer is the V23 Brain (`app.brain.kernel.CognitiveKernel`). Phase 4 makes that consumption explicit and regression-tested.

## Canonical fields

| Field | Type | Producer | Consumer | Meaning |
|---|---|---|---|---|
| `intent` | `str` | semantic parser | Brain | highest-ranked semantic intent |
| `operation` | `str` | contract adapter | Brain | executable semantic operation, currently equal to `intent` at Layer 3 |
| `entities` | tuple[dict] | entity extractor | Brain/planner | typed entity mentions |
| `references` | tuple[dict] | reference resolver | Brain | grounded/unresolved conversational references |
| `speech_act` | `str` | semantic parser | Brain | greeting/question/command/request/statement/correction |
| `language` | `str` | semantic parser | Brain | `ar`, `en`, `mixed`, or `other` |
| `conversation_class` | `str` | contract adapter | Brain routing | coarse conversation/task class |
| `canonical_goal` | `str` | semantic parser | Brain planner | compact normalized goal |
| `target` | `str` | contract adapter | Brain planner | object/query/reference target |
| `key` | `str` | slot extractor/contract adapter | Brain memory/tool args | memory/result key |
| `value` | `str` | slot extractor/contract adapter | Brain memory/tool args | user-provided value |
| `expression` | `str` | slot extractor/contract adapter | calculator path | arithmetic expression |
| `reference` | `str` | contract adapter | Brain/reference path | active reference target |
| `slots` | tuple[(str,str)] | slot extractor | Brain | extensible typed slot carrier |
| `temporal` | tuple[dict] | temporal extractor | Brain | grounded temporal expressions |
| `constraints` | tuple[dict] | constraint extractor | Brain | explicit constraints |
| `required_information` | tuple[str] | ambiguity layer | Brain | information required before safe execution |
| `ambiguity_reasons` | tuple[str] | ambiguity layer | Brain | why the semantic parse is uncertain |
| `safety_signals` | tuple[str] | safety layer | Brain/policy | instruction-like or safety-relevant signals |
| `needs_clarification` | `bool` | semantic layer | Brain routing | safe clarification gate |
| `clarification_question` | `str` | semantic layer | response layer | user-facing clarification request |
| `confidence` | `float` | semantic layer | Brain | normalized semantic confidence |
| `requires_fresh_data` | `bool` | semantic layer | routing | request needs current/external evidence |
| `source` | `str` | semantic layer | diagnostics | semantic provenance |

## Invariants

1. User-language understanding is represented once through the `SemanticParse → SemanticContract` boundary.
2. `slots` is extensible, but canonical decision fields have explicit names and meanings.
3. No generative LLM is part of this contract.
4. Unresolved references and required information remain explicit; consumers must not silently invent them.
5. Arabic, English, and mixed-language turns use the same field names and types.
