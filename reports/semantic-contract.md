# SHURY Unified Semantic Contract — Phase 3

## Status

**PHASE 3 RESULT — PASS**

The semantic layer exposes one typed `SemanticContract` as the boundary between retrieval-native semantic understanding and Brain consumers. The contract is produced by `SemanticContract.from_parse(SemanticParse)` and carries canonical fields plus extensible structured slots.

## Data flow

```text
USER MESSAGE
  ↓
semantic_understand(...)
  ↓
SemanticParse
  ↓
SemanticContract.from_parse(...)
  ↓
Brain / interface consumers
```

`omarelshehy/Arabic-Retrieval-v1.0` remains the intended semantic retrieval model. This phase does not add or replace any model.

## Canonical fields

| Field | Type | Producer | Consumer | Meaning |
|---|---|---|---|---|
| `version` | `str` | contract | all consumers | Contract schema version. |
| `text` | `str` | parser | Brain/debug | Original user utterance. |
| `normalized` | `str` | parser | semantic consumers | Normalized comparison form. |
| `language` | `str` | parser | Brain/response | Detected `ar`, `en`, `mixed`, or `other`. |
| `domain` | `str` | parser/top intent | Brain routing | Capability/domain family associated with the semantic result. |
| `conversation_class` | `str` | contract mapper | Brain/planner gate | High-level class such as `SOCIAL`, `MEMORY_WRITE`, `MEMORY_READ`, `RESEARCH`, `ANALYSIS`, `EXECUTION`, `TASK`, `INFORMATION`, `CLARIFICATION`. |
| `speech_act` | `str` | parser | Brain/response | Communicative act such as question, statement, command, request, correction. |
| `actionability` | `str` | parser | Brain | Whether the turn is informational, actionable, or corrective. |
| `intent` | `str` | top semantic intent | Brain | Canonical intent name after alias normalization. |
| `operation` | `str` | contract mapper | Brain executor/planner | Canonical executable/query operation. |
| `canonical_goal` | `str` | parser | Brain planning/context | Compact normalized goal representation. |
| `target` | `str` | contract mapper | Brain/task routing | Primary object or goal target. |
| `key` | `str` | contract mapper | memory/result tools | Canonical key for retrieval, stored result, fact, or correction. |
| `value` | `str` | contract mapper | memory/result tools | Canonical value associated with the key. |
| `expression` | `str` | slot producer / contract | calculator | Canonical arithmetic expression, without politeness/chaining text. |
| `reference` | `str` | contract mapper | reference/context layer | Primary resolved reference target when one exists. |
| `entities` | `tuple[dict[str, Any], ...]` | entity extractor | Brain/RAG/context | Typed entity mentions and provenance. |
| `references` | `tuple[dict[str, Any], ...]` | reference resolver | context/Brain | Structured conversational references and resolution state. |
| `temporal` | `tuple[dict[str, Any], ...]` | temporal extractor | planning/research | Structured temporal expressions. |
| `constraints` | `tuple[dict[str, Any], ...]` | constraint extractor | planning/execution | Structured conditions and operators. |
| `slots` | `tuple[tuple[str, str], ...]` | parser | Brain | Extensible semantic slot namespace; canonical fields take precedence downstream. |
| `uncertainty` | `tuple[str, ...]` | parser/contract | Brain | Combined ambiguity/required-information signals. |
| `required_information` | `tuple[str, ...]` | parser | clarification/planning | Information still required to proceed. |
| `ambiguity_reasons` | `tuple[str, ...]` | parser | Brain/debug | Machine-readable ambiguity causes. |
| `safety_signals` | `tuple[str, ...]` | parser | safety layer | Safety-relevant semantic signals. |
| `needs_clarification` | `bool` | parser | Brain | Whether semantic resolution requires clarification. |
| `clarification_question` | `str` | parser | user-facing response layer | Natural-language clarification prompt. |
| `confidence` | `float` | parser/top intent | routing/evaluation | Semantic confidence score. |
| `requires_fresh_data` | `bool` | parser | research/tool routing | Whether the request depends on current external data. |
| `source` | `str` | parser | observability/evaluation | Provenance of the semantic result; production parser uses `retrieval-nlp`. |

## Vocabulary rule

Intent aliases are canonicalized once in the semantic layer. For example, `skill_selection` is normalized to `skill_query`; downstream Brain consumers do not need legacy aliases.

Arithmetic expressions have a dedicated semantic producer. Once a validated expression exists, generic slot regexes cannot overwrite it with trailing politeness or mixed-language prose.

## Verification

Phase 3 focused regression suite:

```text
37 passed
0 failed
```

The focused contract test verifies Arabic, English, and Arabic-English mixed inputs expose the same canonical `intent`, `operation`, and `expression` semantics while preserving language classification.
