# Research Notes — V22.5.0 Layer 2 Semantic Understanding

## Research themes used

- Multilingual coreference: CRAC 2026 work demonstrates both lightweight structured coreference and LLM-based approaches; this release uses a deterministic structured baseline with an optional model fallback.
- Temporal semantics: recent 2026 work on temporal semantic memory and temporal-hierarchical memory motivates explicit temporal expressions and validity-aware context rather than treating time as raw text.
- Semantic routing: current agent-routing designs commonly use a cascade from deterministic rules to semantic similarity and finally an LLM classifier; this release implements the safe deterministic/model boundary but intentionally keeps embeddings optional for now.
- Clarification: recent research treats ambiguity resolution as an explicit decision problem and recommends asking the minimum useful question when unresolved references or parameters would materially change execution.
- Structured outputs: current model APIs support JSON-schema-constrained outputs, which are used for the optional semantic-model fallback.

## Scope decision

Layer 2 does not execute tools, does not grant permissions and does not replace the existing runtime policy. It converts natural-language input into a typed semantic contract that Layer 1 Cognitive Core and deterministic planning can consume.

## Validation

- Semantic benchmark: 50/50.
- Full regression suite: 270/270.
- Real-user semantic acceptance cases cover Arabic, English, mixed identifiers, temporal requests, ambiguous references, corrections, compound pipelines, web-vs-RAG routing and memory statements.
