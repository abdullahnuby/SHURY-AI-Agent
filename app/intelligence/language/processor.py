from __future__ import annotations

import re
import unicodedata

from .models import LanguageInput

_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
_ALEF_VARIANTS = str.maketrans("إأآٱ", "اااا")
_PERSIAN_VARIANTS = str.maketrans("كی", "كي")
_ARABIC_MARKS = re.compile(r"[\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06ed\u0640]")
_ARABIC_RE = re.compile(r"[\u0600-\u06ff]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u0600-\u06ff]+", re.UNICODE)

# These are language/dialect indicators only. They do not represent agent intents.
# Keeping them here prevents downstream skill/brain code from needing Arabic-specific
# vocabulary just to know which language profile processed the input.
_EGYPTIAN_MARKERS = {
    "ايه", "إيه", "فين", "ازاي", "إزاي", "ليه", "عايز", "عايزين", "عاوز", "عايزه", "مش", "كده",
    "دلوقتي", "فاكر", "بشتغل", "شغال", "بتاع", "بتاعة", "احنا", "انتو", "ممكن",
}


def normalize_text(text: str) -> str:
    value = unicodedata.normalize("NFKC", str(text or ""))
    value = value.translate(_ARABIC_DIGITS).translate(_ALEF_VARIANTS).translate(_PERSIAN_VARIANTS)
    value = _ARABIC_MARKS.sub("", value)
    # Normalize common Arabic punctuation to ASCII equivalents for downstream parsers.
    value = value.translate(str.maketrans({"؟": "?", "،": ",", "؛": ";"}))
    value = re.sub(r"[!?]{3,}", "?", value)
    value = re.sub(r"\s+", " ", value).strip().lower()
    # Collapse obvious chat elongation without changing normal doubled letters.
    value = re.sub(r"(.)\1{2,}", r"\1", value, flags=re.UNICODE)
    return value


def detect_language(text: str) -> str:
    value = str(text or "")
    # File paths, URLs, repository slugs, and other opaque identifiers are payload data,
    # not reliable evidence of the user's natural language. Mask them before script counts.
    probe = re.sub(r"https?://\S+", " ", value, flags=re.I)
    probe = re.sub(r"(?:[A-Za-z]:[\\/]|\./|/)[^\s]+", " ", probe)
    probe = re.sub(r"\b[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\b", " ", probe)
    ar = len(_ARABIC_RE.findall(probe))
    en = len(_LATIN_RE.findall(probe))
    if ar and en and ar >= 2 and en >= 2:
        return "mixed"
    if ar:
        return "ar"
    if en:
        return "en"
    return "other"


def detect_variant(normalized: str, language: str) -> str:
    if language == "mixed":
        return "mixed-ar-en"
    if language == "en":
        return "en"
    if language != "ar":
        return "other"
    tokens = set(_TOKEN_RE.findall(normalized))
    if len(tokens & _EGYPTIAN_MARKERS) >= 2:
        return "ar-eg"
    return "ar-general"


def prepare(text: str) -> LanguageInput:
    original = str(text or "").strip()
    normalized = normalize_text(original)
    language = detect_language(original)
    variant = detect_variant(normalized, language)
    return LanguageInput(
        original=original,
        normalized=normalized,
        language=language,
        variant=variant,
        arabic_chars=len(_ARABIC_RE.findall(original)),
        latin_chars=len(_LATIN_RE.findall(original)),
        digit_count=len(re.findall(r"\d", original)),
        token_count=len(_TOKEN_RE.findall(normalized)),
    )
