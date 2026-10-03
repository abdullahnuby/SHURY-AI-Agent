# SHURY — Arabic Retrieval Migration

## Target architecture

SHURY no longer has a generative-language runtime dependency. The natural-language layer is built around:

```text
User text
  -> deterministic normalization / extraction
  -> Arabic-Retrieval-v1.0 semantic similarity
  -> audited intent exemplars
  -> typed semantic frame
  -> canonical Brain
  -> deterministic planning / policy / execution / verification / learning
```

`Arabic-Retrieval-v1.0` is a Sentence Transformer retrieval model. SHURY uses it for semantic embeddings and similarity, not for response generation or tool selection by free-form text generation.

## Model contract

Default model:

```text
omarelshehy/Arabic-Retrieval-v1.0
```

Production mode defaults to `required` so an unavailable model is surfaced instead of silently downgrading semantic routing.

Environment:

```text
SHURY_NLP_MODEL=omarelshehy/Arabic-Retrieval-v1.0
SHURY_NLP_MODE=required
SHURY_NLP_DEVICE=cpu
```

The adapter follows the model card's retrieval format and sends user queries with `<query>:` and indexed text with `<passage>:` prefixes.

## Retrieval roles

### Semantic intent routing

Intent families contain audited exemplars. Semantic retrieval can recover paraphrases that do not share exact keywords with an exemplar. The result is merged with deterministic lexical/context evidence and converted into a typed `IntentCandidate`.

The semantic model cannot create a new executable intent name, bypass policy, or directly execute a tool.

### Local RAG

Local chunks now carry:

- the embedding bytes
- the embedding model name

RAG combines lexical ranking with semantic similarity. Final answers remain extractive and citation/evidence-bound.

### Agentic RAG

Agentic RAG keeps iterative retrieval, coverage checking, source escalation, conflict detection, and claim verification. Synthesis is explicitly `extractive`.

## Removed legacy components

These runtime modules were removed:

```text
app/integrations/llm.py
app/runtime/react.py
app/intelligence/semantic/llm.py
```

The public cognitive path no longer accepts a provider argument.

## Verification

The migration was verified with:

- 98 core acceptance tests: passed
- 47 memory regression tests: passed
- 21 focused semantic/RAG/learning tests: passed
- Python `compileall`: passed
- active `app/` scan: no provider/generative-runtime references remain

The sandbox did not contain `sentence-transformers`, and outbound package installation was unavailable, so the real Hugging Face weights could not be loaded here. The retrieval adapter was tested against a fake Sentence Transformer that verifies the query/passage prefixes, normalization, semantic ranking, and SHURY integration. Install `requirements.txt` before enabling production `required` mode.
