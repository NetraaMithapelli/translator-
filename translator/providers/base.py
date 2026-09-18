"""
providers/base.py
------------------
Abstract interface every translation backend must implement.

Why an interface at all:
The task requires the provider to be swappable without rewriting the API
layer. translator_service only ever talks to this interface, never to
(say) "requests to googleapis.com" directly -- so replacing Google
Translate with a different vendor, or with an LLM-based provider, means
writing one new class here and flipping the TRANSLATION_PROVIDER env var.

Custom exceptions (rather than letting arbitrary library exceptions
bubble up) let translator_service/api.py map failures to the specific
error codes the spec requires (TRANSLATION_TIMEOUT, PROVIDER_ERROR,
RATE_LIMITED) regardless of which concrete provider raised them.
"""

from abc import ABC, abstractmethod
from typing import List


class ProviderTimeoutError(Exception):
    """Raised when the provider did not respond within REQUEST_TIMEOUT_SECONDS."""


class ProviderRateLimitError(Exception):
    """Raised when the provider signals a rate limit / quota error."""


class ProviderError(Exception):
    """Raised for any other provider-side failure (5xx, bad response, auth, etc)."""


class TranslatorProvider(ABC):
    """
    Contract: translate a batch of independent strings into one target
    language in as few network round-trips as possible.

    Implementations MUST:
      - preserve list order (result[i] corresponds to texts[i])
      - return exactly len(texts) results
      - raise the exceptions above rather than leaking library-specific
        exceptions, so the service layer can map errors consistently
      - not mutate the input list
    """

    name: str = "base"

    @abstractmethod
    async def translate_batch(self, texts: List[str], target_language: str) -> List[str]:
        ...
