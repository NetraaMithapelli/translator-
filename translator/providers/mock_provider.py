"""
providers/mock_provider.py
---------------------------
Deterministic, network-free provider. Used for:
  - local development without API keys
  - the automated test suite (tests must be able to verify batching
    behavior, error handling, etc. without depending on network access
    or a real vendor's uptime/quota)

It also intentionally supports simulating failures (timeout, rate limit,
generic error) via constructor flags, which the test suite uses to
exercise translator_service's error handling paths deterministically --
something that's hard to do reliably against a real network provider.
"""

import asyncio
from typing import List

from .base import TranslatorProvider, ProviderTimeoutError, ProviderRateLimitError, ProviderError


class MockProvider(TranslatorProvider):
    name = "mock"

    def __init__(self, fail_mode: str | None = None):
        """
        fail_mode: None | "timeout" | "rate_limit" | "error"
        When set, every call to translate_batch raises the corresponding
        provider exception instead of "translating".
        """
        self.fail_mode = fail_mode
        self.call_count = 0
        self.last_batch_size = 0

    async def translate_batch(self, texts: List[str], target_language: str) -> List[str]:
        self.call_count += 1
        self.last_batch_size = len(texts)

        if self.fail_mode == "timeout":
            raise ProviderTimeoutError("Simulated timeout")
        if self.fail_mode == "rate_limit":
            raise ProviderRateLimitError("Simulated rate limit")
        if self.fail_mode == "error":
            raise ProviderError("Simulated provider error")

        # Deterministic "translation": tag with the target language so
        # tests can assert on it, without needing real linguistic content.
        return [f"[{target_language}] {text}" for text in texts]
