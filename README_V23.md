# SHURY V23 — Cognitive Core Alpha

V23 is an architectural reset: V22 remains the execution substrate, while cognition lives under `app/brain`.

## Core loop

```text
Perceive → State → Goal → Deliberate → Method/Plan → Act → Observe/Verify → Revise → Learn → Answer
```

The V23 core is deterministic. Natural-language semantics are provided by `Arabic-Retrieval-v1.0`; the model is used for semantic similarity/retrieval only, while planning and execution remain deterministic.

## Run

```powershell
py -m app.brain --act "احفظ اسمي عبدالله"
py -m app.brain --act "أنا مين؟"
py -m app.brain --act "احسب 25 * 16 واحفظ النتيجة باسم total"
py -m app.brain --act "ما الذي تستطيع فعله؟"
```

Browser:

```powershell
py -m app.interfaces.web
```

The browser uses V23 by default. `SHURY_USE_LEGACY_RUNTIME=1` exists only for compatibility diagnostics.

## Architecture boundaries

- `app/brain/`: cognition, belief state, semantic frame, inference, methods, state planning, observation, learning and self model.
- `app/runtime/`: V22 execution substrate and tool contracts.
- `app/interfaces/web/`: transport/UI boundary.
- `app/intelligence/semantic/retrieval.py`: Arabic-Retrieval-v1.0 adapter for semantic routing and retrieval.

## Strict implementation board

Read `docs/V23_STRICT_TODO.md`. A checkbox is not considered done without the executable acceptance gate recorded there.
