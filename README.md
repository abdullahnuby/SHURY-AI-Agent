# SHURY — V23 Company-2 / V27

SHURY is a deterministic cognitive agent with Arabic-first semantic retrieval, structured Brain
planning, governed tool execution, verification, learning, memory, research, RAG, and the
Company-2 organizational layer.

## Architecture

```text
User text
  -> language boundary
  -> Arabic-Retrieval-v1.0 semantic retrieval
  -> typed semantic frame
  -> canonical Brain
  -> deterministic planning
  -> governed tools
  -> verification / QA
  -> learning and memory
  -> final response
```

`omarelshehy/Arabic-Retrieval-v1.0` is used for semantic retrieval and embeddings. It is not a
response generator and is not used to grant execution authority.

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

`SHURY_NLP_MODE=required` fails closed when the configured retrieval model is unavailable.

## Run

CLI:

```powershell
py -m app.main
```

Web interface:

```powershell
py -m app.interfaces.web
```

The canonical structured Brain entry point is exposed through `app.api.run_brain` and
`app.api.run_structured_goal`.

## Company-2 V27

The current release includes the language-independent
`cross_department_sales_report_move` capability:

1. recursively inventory the workspace;
2. rank CSVs by average `sales`/`revenue`;
3. create `top_sales_analysis.md`;
4. move it safely to `selected_reports` without replacement;
5. reread the actual destination returned by the move;
6. run independent QA against source fingerprints and execution evidence.

See `docs/COMPANY2_V27_RELEASE.md` for the release verification and regression scope.

## Tests

```powershell
py -m pytest -q
```

The test suite uses hermetic temporary databases and can generate the synthetic 100K seed index
on demand. Runtime databases, logs, caches, benchmark outputs, and generated reports are not
part of the clean source release.

## Seed data

The portable seed corpus is under `data/seed/`. To generate the local SQLite FTS index used by
`/seed` and Brain bootstrap:

```powershell
py scripts/seed/generate.py
```

## Repository layout

```text
app/          runtime, Brain, planning, memory, learning, tools, services, web and CLI
benchmarks/   canonical benchmark input corpora needed by the evaluation tests
data/         portable seed data
scripts/      reproducible maintenance and evaluation utilities
tests/        regression and architecture tests
docs/         current architecture, contracts, release and operational documentation
workspace/    small local demo fixtures only
```
