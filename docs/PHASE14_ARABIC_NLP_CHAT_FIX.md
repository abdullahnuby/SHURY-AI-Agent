# SHURY — Arabic NLP Chat Fix

## Problem
The browser Brain runtime was not consuming the retrieval-native Arabic semantic parser. Natural statements such as `انا اسمي عبدالله` and `أنا من الأقصر` fell through the legacy perception path as generic `statement`, producing `goal_or_capability` clarification.

The web client also rendered the internal cognitive diagnostics directly inside every assistant message.

## Fix
- The canonical Brain perception path now consumes `app.intelligence.semantic.semantic_understand()` as the primary semantic source, with the legacy perception path retained only as deterministic fallback.
- Arabic memory namespaces (`fact:name`, `fact:origin`, `fact:city`, `recall:key`) are normalized into the Brain slot contract.
- `remember_fact` / `remember_memory` route to the canonical `remember` Brain operation.
- `recall_fact` routes to `query_identity` for `name` and `query_memory` for other keys.
- `knowledge_query` routes to the canonical `query_knowledge` operation.
- Recall-key evidence now has priority over declarative memory matching, preventing `أنا من فين؟` from being interpreted as `أنا من ...` statement.
- User-facing memory responses are concise and conversational.
- Cognitive diagnostics are now debug-only (`?debug=1`) and are not rendered in normal chat.

## Validation
- Arabic NLP / Brain bridge / semantic / cognitive-loop targeted suite: **37 passed**.
- Web interface tests: **4 passed**.
- Identity / package / hotfix import tests: **7 passed**.
- Python compileall: **passed**.
- Browser JavaScript syntax check (`node --check`): **passed**.
- No LLM/provider references were found under `app/`.
