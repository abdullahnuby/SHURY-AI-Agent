# Codebase Map

## Where new memory code belongs

```text
app/knowledge/
  memory.py                 # durable storage + lifecycle orchestration
  memory_models.py          # typed memory records
  memory_extraction.py     # conservative extraction + privacy gate
  memory_retrieval.py      # retrieval/ranking only
  memory_consolidation.py  # stability/retention helpers
  temporal_memory.py       # temporal projections

app/tools/memory/
  memory.py                # fact/note language tools
  advanced.py              # search/profile/history/graph/forget/consolidate
  benchmark.py             # offline memory benchmark adapter

app/evaluation/memory_benchmark.py  # memory acceptance suite
```

Storage belongs in `knowledge`, executable adapters belong in `tools`, and evaluation belongs in `evaluation`. Do not add new `memory_v23.py`, `memory_v24.py`, or version-numbered runtime modules.


## Layer 1 Cognitive Core

- `app/intelligence/cognitive/context.py` — bounded runtime context assembly.
- `app/intelligence/cognitive/schemas.py` — JSON schemas for cognitive analysis/reflection.
- `app/intelligence/cognitive/reasoning.py` — provider-backed structured reasoning.
- `app/intelligence/cognitive/controller.py` — cognitive orchestration boundary.
- `app/runtime/cognitive_agent.py` — public runtime entrypoint for the cognitive loop.


## Layer 2 Semantic Understanding

```text
app/intelligence/semantic/
  models.py       # typed semantic records
  schemas.py      # structured-output contract for model fallback
  parser.py       # orchestration, normalization, safe model merge
  intents.py      # paraphrase/context semantic routing
  entities.py     # entity mentions
  references.py   # grounded references/coreference
  temporal.py     # relative/absolute dates and times
  constraints.py  # limits, deadlines, ordering and other constraints
  slots.py        # structured task parameters
  retrieval.py    # Arabic-Retrieval-v1.0 semantic retrieval adapter
```

Evaluation: `app/evaluation/semantic_benchmark.py` and `tests/test_semantic_layer2.py` / `tests/test_semantic_real_user.py`.

Do not add versioned semantic modules such as `semantic_v23.py`; extend these responsibility-owned modules instead.

## Layer 3
- `app/knowledge/agentic_rag/`: adaptive retrieval planner, evidence models, provenance/conflict checks, orchestration, and grounded synthesis.
- `app/services/agentic_rag_service.py`: service facade.
- `app/tools/knowledge/agentic_rag.py`: governed tool entry point.
- `app/evaluation/agentic_rag_benchmark.py`: deterministic Layer 3 benchmark.


## Layer 4 — World Model

```text
app/world/
  models.py        # typed entities, relations, observations, diffs, predictions
  model.py         # consequence prediction, observation, state comparison, assessment
  store.py         # session-scoped world snapshot persistence

app/tools/system/world.py              # read-only action consequence simulation
app/evaluation/world_model_benchmark.py # deterministic Layer 4 benchmark
```

The canonical executable state remains `app/domain/world.py`; `app/world/` owns modeling, observation and prediction logic around that state. Never treat model-generated text or arbitrary tool output as trusted state.


## Layer 5 — Self-Improvement

```text
app/learning/
  models.py       # experience, lesson, evaluation and evolution decision records
  diagnosis.py    # task signatures, failure classification, reward and contrastive lessons
  store.py        # durable experiences, lessons, replay evaluations and evolution events
  replay.py       # counterfactual candidate-skill replay; never executes tools
  promotion.py    # evidence-based promotion gates
  manager.py      # observe → diagnose → guide → candidate → replay → promote/rollback

app/evaluation/self_improvement_benchmark.py
tests/test_layer5.py
tests/test_layer5_real_user.py
tests/test_cli_layer5.py
```

Learning data is advisory. Runtime policy, approval, verification, and SkillBank trust remain authoritative. Legacy reflection lessons without failed-step evidence are retired but their evidence remains auditable.
