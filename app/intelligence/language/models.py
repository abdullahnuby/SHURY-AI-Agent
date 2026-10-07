from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LanguageInput:
    """Language-boundary representation produced before semantic interpretation.

    The Agent/Brain never needs to inspect language-specific normalization details.
    Downstream layers receive the canonical semantic contract instead.
    """

    original: str
    normalized: str
    language: str
    variant: str
    arabic_chars: int
    latin_chars: int
    digit_count: int
    token_count: int

    @property
    def is_arabic(self) -> bool:
        return self.language in {"ar", "mixed"}

    @property
    def is_english(self) -> bool:
        return self.language in {"en", "mixed"}
