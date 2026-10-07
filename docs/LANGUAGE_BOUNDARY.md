# SHURY Language Boundary

SHURY treats Arabic, English, and mixed-language text as input-layer concerns. The language boundary produces a `LanguageInput` containing the original text, canonical normalized text, language, and a coarse variant profile.

The semantic layer converts that language-bound input into `SemanticParse` and then the canonical `SemanticContract`. Brain, Skills, planning, tools, verification, memory, and learning consume structured semantic fields rather than language-specific sentence rules.

The boundary is intentionally modest: it normalizes orthographic variation, detects script mix, identifies a coarse Egyptian-Arabic profile, and masks opaque technical identifiers for language detection. It does not attempt to solve every Arabic dialect or every linguistic phenomenon. Capability understanding remains the responsibility of the semantic layer, and task execution remains the responsibility of the Agent core.
