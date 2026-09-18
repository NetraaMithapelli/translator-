"""
providers/libretranslate_provider.py
---------------------------------------
Free, no-approval-process alternative: LibreTranslate.
"""

import logging
from typing import List

import httpx

from .base import TranslatorProvider, ProviderTimeoutError, ProviderRateLimitError, ProviderError
from .. import config

logger = logging.getLogger("translator.providers.libretranslate")

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=config.REQUEST_TIMEOUT_SECONDS)
    return _client


class LibreTranslateProvider(TranslatorProvider):
    name = "libretranslate"

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        source_language: str = "en",
    ):
        self.base_url = (base_url or config.LIBRETRANSLATE_URL or "http://localhost:5000").rstrip("/")
        self.api_key = api_key or config.LIBRETRANSLATE_API_KEY
        self.source_language = source_language

    async def translate_batch(self, texts: List[str], target_language: str) -> List[str]:
        if not texts:
            return []

        client = _get_client()
        body = {
            "q": texts,
            "source": self.source_language,
            "target": target_language,
            "format": "text",
        }
        if self.api_key:
            body["api_key"] = self.api_key

        try:
            response = await client.post(f"{self.base_url}/translate", json=body)
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(str(exc)) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"Network error calling LibreTranslate at {self.base_url}: {exc}. "
                f"If self-hosting, confirm the server is running (`libretranslate`)."
            ) from exc

        if response.status_code == 429:
            raise ProviderRateLimitError("LibreTranslate rate limit exceeded.")
        if response.status_code == 400:
            raise ProviderError(
                f"LibreTranslate rejected the request (400): {response.text[:200]} -- "
                f"this often means '{target_language}' isn't installed on this instance. "
                f"Check GET {self.base_url}/languages."
            )
        if response.status_code >= 500:
            raise ProviderError(f"LibreTranslate server error: {response.status_code}")
        if response.status_code != 200:
            raise ProviderError(f"LibreTranslate returned {response.status_code}: {response.text[:200]}")

        try:
            payload = response.json()
            translated = payload["translatedText"]
        except (KeyError, ValueError) as exc:
            raise ProviderError(f"Unexpected LibreTranslate response shape: {exc}") from exc

        if isinstance(translated, list):
            if len(translated) != len(texts):
                raise ProviderError("LibreTranslate returned a mismatched number of results.")
            return translated

        if len(texts) == 1:
            return [translated]

        logger.warning(
            "LibreTranslate at %s does not support batched `q` arrays; falling back to "
            "%d sequential calls. Consider upgrading the instance for better latency.",
            self.base_url, len(texts),
        )
        results = [translated]
        for text in texts[1:]:
            single_body = dict(body, q=text)
            resp = await client.post(f"{self.base_url}/translate", json=single_body)
            if resp.status_code != 200:
                raise ProviderError(f"LibreTranslate returned {resp.status_code} during fallback call.")
            results.append(resp.json()["translatedText"])
        return results