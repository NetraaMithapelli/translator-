"""
config.py
---------
Central configuration for the translation service.

Why this file exists:
The task explicitly requires that the set of translatable fields and the
list of supported languages NOT be hardcoded throughout the application.
Every other module (field_mapper, translator_service, api) imports its
settings from here, so changing a language or a field name means editing
one place, not grepping the codebase.

Everything here can be overridden with environment variables so ops can
tune behavior (timeouts, cache TTL, provider choice) without a code change.
"""

import os
from pathlib import Path

# Load a .env file if python-dotenv is available. This is optional so the
# module still works in environments where env vars are injected directly
# (e.g. containers, CI).
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Supported languages
# ---------------------------------------------------------------------------
# Code -> display name. This is the single source of truth for "is this
# language code valid". Adding a language here does NOT guarantee provider
# support -- see providers/*.py docstrings for provider-specific coverage
# notes. We deliberately do not claim uniform quality across languages.
SUPPORTED_LANGUAGES = {
    "hi": "Hindi",
    "mr": "Marathi",
    "bn": "Bengali",
    "ta": "Tamil",
    "te": "Telugu",
    "gu": "Gujarati",
    "kn": "Kannada",
    "ml": "Malayalam",
    "pa": "Punjabi",
    "or": "Odia",
}


# ---------------------------------------------------------------------------
# Translatable field configuration
# ---------------------------------------------------------------------------
# This is an ALLOW-LIST, not a deny-list. Only field names listed here are
# ever touched by the translator. Anything not listed (product_id,
# rules_checked, generated_at, any future field the frontend team adds)
# passes through completely untouched by construction -- there is no way
# for a new machine-readable field to get "accidentally" translated,
# because it simply isn't in this map.
#
# mode="text"  -> the field's value is human prose. It is translated and
#                 the field is REPLACED in place (there is no separate
#                 "machine meaning" to preserve for free text).
# mode="enum"  -> the field's value is a fixed, machine-significant code
#                 (e.g. status strings). The original value is preserved
#                 untouched and a sibling "<field>_translated" key is
#                 added. This is what lets a NON_COMPLIANT status remain
#                 exactly "NON_COMPLIANT" for any downstream logic while
#                 still giving the user a localized label.
#
# This dict is intentionally editable/extensible -- in a larger system it
# could be loaded from a JSON/YAML file or a database table instead of
# being a Python literal. Keeping it a plain dict here keeps the sample
# project dependency-free.
DEFAULT_FIELD_CONFIG = {
    "product_name": "text",
    "status": "enum",
    "status_display": "text",
    "rule_description": "text",
    "description": "text",
    "failure_explanation": "text",
    "review_explanation": "text",
    "recommendation": "text",
    "message": "text",
    "label": "text",
    "title": "text",
    "reason": "text",
    "notes": "text",
}


def _load_field_config() -> dict:
    """
    Allow ops to override the field list via env var without touching code:
    TRANSLATABLE_FIELDS_ENUM="status,severity"
    TRANSLATABLE_FIELDS_TEXT="product_name,description"
    Falls back to DEFAULT_FIELD_CONFIG if not set.
    """
    enum_fields = os.getenv("TRANSLATABLE_FIELDS_ENUM")
    text_fields = os.getenv("TRANSLATABLE_FIELDS_TEXT")
    if not enum_fields and not text_fields:
        return dict(DEFAULT_FIELD_CONFIG)

    config = {}
    for f in (enum_fields or "").split(","):
        f = f.strip()
        if f:
            config[f] = "enum"
    for f in (text_fields or "").split(","):
        f = f.strip()
        if f:
            config[f] = "text"
    return config


FIELD_CONFIG = _load_field_config()


# ---------------------------------------------------------------------------
# Provider / networking / performance settings
# ---------------------------------------------------------------------------
TRANSLATION_PROVIDER = os.getenv("TRANSLATION_PROVIDER", "mock")  # google | bhashini | anthropic | libretranslate | mock
GOOGLE_TRANSLATE_API_KEY = os.getenv("GOOGLE_TRANSLATE_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Bhashini (bhashini.gov.in) -- free, no billing account required. Sign up
# to get a user_id and ulca_api_key. See providers/bhashini_provider.py.
BHASHINI_USER_ID = os.getenv("BHASHINI_USER_ID", "")
BHASHINI_ULCA_API_KEY = os.getenv("BHASHINI_ULCA_API_KEY", "")
BHASHINI_PIPELINE_ID = os.getenv("BHASHINI_PIPELINE_ID", "")  # optional override

LIBRETRANSLATE_URL = os.getenv("LIBRETRANSLATE_URL", "http://localhost:5000")
LIBRETRANSLATE_API_KEY = os.getenv("LIBRETRANSLATE_API_KEY", "")

MYMEMORY_EMAIL = os.getenv("MYMEMORY_EMAIL", "")

REQUEST_TIMEOUT_SECONDS = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "5"))
TRANSLATION_CACHE_TTL_SECONDS = int(os.getenv("TRANSLATION_CACHE_TTL_SECONDS", "3600"))

# When true, the API includes internal timing breakdowns (provider_latency_ms,
# backend_latency_ms) in the response. Useful in dev/staging to find the
# bottleneck; you may want this off in prod to keep responses small.
EXPOSE_TIMING_BREAKDOWN = os.getenv("EXPOSE_TIMING_BREAKDOWN", "true").lower() == "true"

BASE_DIR = Path(__file__).resolve().parent
