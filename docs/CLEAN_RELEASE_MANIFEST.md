# SHURY Clean Release Manifest

## Included

- `app/` — canonical application source, Brain, planning, semantic layer, tools, services, CLI and web interface
- `tests/` — regression, architecture and evaluation tests
- `scripts/` — reproducible maintenance, seed and evaluation utilities
- `data/seed/` — portable synthetic seed corpus and manifest
- `benchmarks/dialogues/` — benchmark input corpora required by the evaluation tests
- `workspace/` — two small deterministic demo inputs
- `docs/` — current architecture, contracts, operational notes and V27 release documentation
- root runtime metadata: `.env.example`, `.gitignore`, `requirements.txt`, `pytest.ini`, `VERSION`, `README.md`

## Explicitly excluded

- Python bytecode and pytest caches
- SQLite runtime databases and network caches
- application logs
- generated benchmark results, failures, reports and runtime traces
- generated evaluation reports and scenario dumps
- historical phase/release dump files
- legacy generative runtime files (`app/integrations/llm.py`, `app/runtime/react.py`, `app/intelligence/semantic/llm.py`)
- temporary/editor artifacts

## Company Core v1 / V27 status

- Company/architecture regression: 36/36 passing
- compileall: passing
- V27 structured workflow: independently verified
- Windows/POSIX workspace path normalization regression: covered
- safe destination collision and dynamic reread destination: covered

## Company Core v1 additions

- `app/organization/registry.py` — structured ownership and specialist routing
- `CompanyTask`, `CompanyHandoff`, `CompanyCoordination` — typed organizational coordination
- tool organizational metadata in `app/runtime/registry.py` and selected tool declarations
- canonical Brain company authorization gate before tool execution
- `docs/SHURY_COMPANY_ORGANIZATION_CORE.md` and `docs/SHURY_COMPANY_ROADMAP.md`
- `tests/test_organization_core_v1.py` — registry, ownership, handoff and authorization regressions
