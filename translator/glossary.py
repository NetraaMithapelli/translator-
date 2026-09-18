"""
glossary.py
-----------
Fixed-vocabulary lookup for compliance status codes.

Why this exists:
Generic machine translation is fine for free prose, but compliance status
words are semantically load-bearing -- "NON_COMPLIANT" translated wrong
(e.g. drifting towards something meaning "needs review") is a factual
error, not a stylistic one. For a closed, small vocabulary like this, a
curated glossary is more reliable than trusting a general-purpose MT
model on every request, and it's also free and instant (no network call).

How it's used:
translator_service checks the glossary FIRST for any "enum" field. If the
target language has a curated entry, that entry is used directly and the
text never goes to the provider at all (saves latency + guarantees
correctness). If the language isn't curated yet, the service falls back
to sending the canonical English label through the normal provider/batch
pipeline -- so an untranslated language degrades to "provider does its
best" rather than silently returning English or a guess.

Honesty note: we only hand-curate the languages we can vouch for the
correctness of the terminology in (Hindi, Marathi here as a starting set).
Extending coverage to the remaining languages in config.SUPPORTED_LANGUAGES
should be done by someone who can verify the legal/technical terminology
is right for that language -- do NOT fill in placeholder guesses, since
that reintroduces the exact "meaning drift" problem this file exists to
prevent.
"""

from typing import Optional

# term -> {lang_code: translated_term}
# Add a new row here to hand-curate a new status/language pair.
GLOSSARY = {
    "COMPLIANT": {
        "hi": "अनुपालक",
        "mr": "अनुपालक",
    },
    "NON_COMPLIANT": {
        "hi": "गैर-अनुपालक",
        "mr": "गैर-अनुपालक",
    },
    "REVIEW_REQUIRED": {
        "hi": "समीक्षा आवश्यक",
        "mr": "पुनरावलोकन आवश्यक",
    },
    "NOT_APPLICABLE": {
        "hi": "लागू नहीं",
        "mr": "लागू नाही",
    },
    "FAILED": {
        "hi": "असफल",
        "mr": "अयशस्वी",
    },
    "PASSED": {
        "hi": "सफल",
        "mr": "यशस्वी",
    },
}


def lookup(term: str, target_language: str) -> Optional[str]:
    """
    Return the curated translation for `term` in `target_language`, or
    None if we don't have a hand-verified entry. `term` is matched
    case-sensitively against the exact enum value (e.g. "NON_COMPLIANT"),
    since that's the exact string the backend/database uses.
    """
    entry = GLOSSARY.get(term)
    if not entry:
        return None
    return entry.get(target_language)
