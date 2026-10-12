# SHURY

SHURY is a deterministic cognitive agent with Arabic semantic retrieval as its natural-language layer.

## Semantic NLP

The runtime uses `omarelshehy/Arabic-Retrieval-v1.0` through Sentence Transformers for:

- semantic intent routing against audited intent exemplars
- local knowledge retrieval and evidence matching
- Arabic-first query/passage embeddings

The model is a retrieval/embedding model, not a response generator. SHURY therefore keeps planning, policy, execution, verification, learning, and answer rendering inside its deterministic Brain stack.

## Install

```powershell
py -m pip install -r requirements.txt
```

Recommended production configuration:

```text
SHURY_NLP_MODEL=omarelshehy/Arabic-Retrieval-v1.0
SHURY_NLP_MODE=required
SHURY_NLP_DEVICE=cpu
```

`SHURY_NLP_MODE=required` prevents a production deployment from silently falling back to lexical-only semantic routing when the configured model cannot be loaded.

## Run

```powershell
py -m app.interfaces.web
```

The canonical natural-language path is `app.runtime.cognitive_agent.run_cognitive`; it feeds a validated semantic frame into the canonical Brain.
