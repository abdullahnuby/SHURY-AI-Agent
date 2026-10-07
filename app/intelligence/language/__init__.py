"""Language boundary for SHURY.

Language-specific normalization and profiling terminate here. The rest of SHURY works
against language-neutral semantic contracts and agent capabilities.
"""

from .models import LanguageInput
from .processor import detect_language, detect_variant, normalize_text, prepare

__all__ = ["LanguageInput", "detect_language", "detect_variant", "normalize_text", "prepare"]
