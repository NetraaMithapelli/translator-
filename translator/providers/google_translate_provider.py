"""
providers/google_translate_provider.py
----------------------------------------
Default production provider: Google Cloud Translation API (Basic, v2,
REST/NMT). Chosen as the default because:

  - It's a dedicated, lightweight machine-translation model, not a general
    LLM -- the task explicitly says not to reach for a big LLM when a
    lightweight translation API is sufficient. A raw NMT call is
    typically tens of milliseconds of model time versus the noticeably
    higher latency of routing the same call through a large chat LLM.
  - The v2 REST endpoint accepts MULTIPLE `q` values in a single POST,
    i.e. true batching in one HTTP round trip -- exactly what section 9
    of the spec asks for ("batch the translatable strings into a single
    translation request").
  - It has first-class support for Hindi, Marathi, Bengali, Tamil,
    Telugu, Gujarati, Kannada, Malayalam, Punjabi -- 9 of our 10 target
    languages. Odia ("or") is NOT supported by Google Translate as of
    this writing; this is called out explicitly rather than silently
    failing, and languages/routing is centralized in config.py so a
    second provider can be plugged in for the languages this one lacks
    (see providers/base.py for how to add one).

Trade-offs to be upfront about (do not oversell this choice):
  - Being a generic MT model, it has no built-in awareness that this
    payload is "compliance data" -- that's exactly why glossary.py exists
    for the small fixed vocabulary, so the parts that must not drift in
    meaning don't depend on this provider's judgment at all.
  - Quality on domain-specific regulatory/legal phrasing in some
    lower-resource languages (e.g. Odia even if it were supported) is
    generally weaker than in Hindi/Marathi/Bengali. This is a real,
    documented limitation of generic NMT, not something this
    implementation can fix -- if higher fidelity is needed for a
    specific language, that's the case for swapping in an LLM-based
    provider (see providers/anthropic_provider.py) for that language only.
  - Requires network egress and an API key; if the key is missing/invalid
    or Google's endpoint is unreachable, this raises ProviderError so the
    caller can return a clean error instead of partial/corrupted output.
"""

import asyncio
from typing import List

import httpx

from .base import TranslatorProvider, ProviderTimeoutError, ProviderRateLimitError, ProviderError
from .. import config

GOOGLE_TRANSLATE_ENDPOINT = "https://translation.googleapis.com/language/translate2"

# Module-level client: reused across requests so TCP/TLS handshake cost is
# paid once per process, not once per API call ("connection reuse" from
# the spec). httpx.AsyncClient is safe to share across concurrent asyncio
# tasks.
_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=config.REQUEST_TIMEOUT_SECONDS)
    return _client


class GoogleTranslateProvider(TranslatorProvider):
    name = "google_translate_v2"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or config.GOOGLE_TRANSLATE_API_KEY
        if not self.api_key:
            # Fail fast at construction, not on first request, so a
            # misconfigured deployment is obvious immediately.
            raise ProviderError("GOOGLE_TRANSLATE_API_KEY is not configured.")

    async def translate_batch(self, texts: List[str], target_language: str) -> List[str]:
        if not texts:
            return []

        client = _get_client()
        params = {
            "key": self.api_key,
            "target": target_language,
            "format": "text",  # plain text, not HTML -- avoids the provider
                                 # trying to interpret markup in compliance text.
        }
        # httpx supports repeated query keys via a list value under "q",
        # which the v2 API treats as a batch -- one HTTP request for all
        # strings instead of N requests.
        data = {"q": texts}

        try:
            response = await client.post(GOOGLE_TRANSLATE_ENDPOINT, params=params, data=data)
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(str(exc)) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"Network error calling Google Translate: {exc}") from exc

        if response.status_code == 429:
            raise ProviderRateLimitError("Google Translate rate limit exceeded.")
        if response.status_code >= 500:
            raise ProviderError(f"Google Translate server error: {response.status_code}")
        if response.status_code != 200:
            raise ProviderError(
                f"Google Translate returned {response.status_code}: {response.text[:200]}"
            )

        try:
            payload = response.json()
            translations = payload["data"]["translations"]
            results = [t["translatedText"] for t in translations]
        except (KeyError, ValueError) as exc:
            raise ProviderError(f"Unexpected Google Translate response shape: {exc}") from exc

        if len(results) != len(texts):
            raise ProviderError("Google Translate returned a mismatched number of results.")
        return results
