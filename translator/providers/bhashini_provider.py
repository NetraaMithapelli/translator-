"""
providers/bhashini_provider.py
---------------------------------
Free alternative to Google Translate: Bhashini (National Language
Translation Mission, meity.gov.in / bhashini.gov.in). No billing account
required -- registration at bhashini.gov.in gives you a `user_id` and
`ulca_api_key` at no cost.

Why this is a genuinely good fit here, not just "the free one":
  - It's purpose-built for Indian languages specifically (AI4Bharat /
    IndicTrans models under the hood), so language coverage for our 10
    target languages is generally stronger than a general-purpose MT
    vendor's.
  - Its inference call natively accepts an array of input strings and
    returns them in the same order -- true batching in one HTTP call,
    same as the Google provider, so translator_service's batching logic
    (dedupe -> one translate_batch() call) needs no changes to use this.

How Bhashini's API differs from a normal single-call REST API (important
for understanding the code below):

  1. "Pipeline config" call (meity-auth.ulcacontrib.org) -- given a
     source/target language pair, returns which underlying model
     (serviceId) to use AND a short-lived inference API key + the actual
     inference endpoint URL to call next.
  2. "Pipeline compute" call (the dhruva-api.bhashini.gov.in endpoint
     returned by step 1) -- the actual translation call, authenticated
     with the key from step 1.

Step 1 is NOT the fast path and doesn't need to happen on every request:
its result (serviceId + inference key + endpoint) is cached per target
language for the process lifetime, refreshed only if a compute call
comes back unauthorized. This keeps the per-request latency down to just
step 2, which is the only genuinely per-translation network call --
directly serving the "minimal network calls" / "low latency" requirement.

Caveat, stated plainly: this implementation follows Bhashini's documented
pipeline flow, but Bhashini does not publish a single frozen REST
contract the way Google's v2 API does -- the pipelineId and exact
response shape have changed as the platform evolved, and this file
could not be exercised against the live API in this environment (no
network access here). Treat this as a solid starting implementation to
validate against your own Bhashini account/credentials, not as
guaranteed-current wire-format.
"""

import time
from typing import List

import httpx

from .base import TranslatorProvider, ProviderTimeoutError, ProviderRateLimitError, ProviderError
from .. import config

ULCA_CONFIG_URL = "https://meity-auth.ulcacontrib.org/ulca/apis/v0/model/getModelsPipeline"

# Bhashini's published pipeline ID for the standard ASR+Translation+TTS /
# translation-only pipeline. Overridable via env in case Bhashini issues
# a new one -- do not assume this literal stays correct forever.
DEFAULT_PIPELINE_ID = "64392f96daac500b55c543cd"

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=config.REQUEST_TIMEOUT_SECONDS)
    return _client


class BhashiniProvider(TranslatorProvider):
    name = "bhashini"

    def __init__(
        self,
        user_id: str | None = None,
        ulca_api_key: str | None = None,
        pipeline_id: str | None = None,
        source_language: str = "en",
    ):
        self.user_id = user_id or config.BHASHINI_USER_ID
        self.ulca_api_key = ulca_api_key or config.BHASHINI_ULCA_API_KEY
        self.pipeline_id = pipeline_id or config.BHASHINI_PIPELINE_ID or DEFAULT_PIPELINE_ID
        self.source_language = source_language
        if not self.user_id or not self.ulca_api_key:
            raise ProviderError("BHASHINI_USER_ID / BHASHINI_ULCA_API_KEY are not configured.")

        # Per-target-language cache of (service_id, callback_url, auth_header_name, auth_header_value).
        # This is what avoids paying the "pipeline config" round trip on
        # every single translation request.
        self._pipeline_cache: dict[str, tuple[str, str, str, str]] = {}

    async def _get_pipeline_config(self, target_language: str) -> tuple[str, str, str, str]:
        cached = self._pipeline_cache.get(target_language)
        if cached is not None:
            return cached

        client = _get_client()
        body = {
            "pipelineTasks": [
                {
                    "taskType": "translation",
                    "config": {
                        "language": {
                            "sourceLanguage": self.source_language,
                            "targetLanguage": target_language,
                        }
                    },
                }
            ],
            "pipelineRequestConfig": {"pipelineId": self.pipeline_id},
        }
        headers = {"userID": self.user_id, "ulcaApiKey": self.ulca_api_key}

        try:
            response = await client.post(ULCA_CONFIG_URL, json=body, headers=headers)
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(str(exc)) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"Network error during Bhashini pipeline config call: {exc}") from exc

        if response.status_code == 429:
            raise ProviderRateLimitError("Bhashini pipeline config call rate-limited.")
        if response.status_code != 200:
            # TEMP DEBUG: print Bhashini's actual error body so we can see
            # exactly why the config call was rejected. Remove this print
            # once the root cause is found.
            print("BHASHINI CONFIG CALL FAILED:", response.status_code, response.text)
            raise ProviderError(f"Bhashini pipeline config call failed: {response.status_code} {response.text[:200]}")
        try:
            payload = response.json()
            translation_config = payload["pipelineResponseConfig"][0]["config"][0]
            service_id = translation_config["serviceId"]
            endpoint_info = payload["pipelineInferenceAPIEndPoint"]
            callback_url = endpoint_info["callbackUrl"]
            auth_name = endpoint_info["inferenceApiKey"]["name"]
            auth_value = endpoint_info["inferenceApiKey"]["value"]
        except (KeyError, IndexError, ValueError) as exc:
            raise ProviderError(f"Unexpected Bhashini pipeline config response shape: {exc}") from exc

        result = (service_id, callback_url, auth_name, auth_value)
        self._pipeline_cache[target_language] = result
        return result

    async def translate_batch(self, texts: List[str], target_language: str) -> List[str]:
        if not texts:
            return []

        service_id, callback_url, auth_name, auth_value = await self._get_pipeline_config(target_language)

        client = _get_client()
        body = {
            "pipelineTasks": [
                {
                    "taskType": "translation",
                    "config": {
                        "language": {
                            "sourceLanguage": self.source_language,
                            "targetLanguage": target_language,
                        },
                        "serviceId": service_id,
                    },
                }
            ],
            # Bhashini accepts a LIST of {"source": text} objects here --
            # this is the single batched call, same principle as Google's
            # repeated `q` params.
            "inputData": {"input": [{"source": t} for t in texts]},
        }
        headers = {auth_name: auth_value}

        try:
            response = await client.post(callback_url, json=body, headers=headers)
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(str(exc)) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"Network error during Bhashini compute call: {exc}") from exc

        if response.status_code == 401:
            # Cached inference key expired -- drop the cache entry so the
            # *next* request re-runs the config call, but fail this one
            # cleanly rather than silently retrying mid-request.
            self._pipeline_cache.pop(target_language, None)
            raise ProviderError("Bhashini inference key expired/unauthorized; will refresh on next request.")
        if response.status_code == 429:
            raise ProviderRateLimitError("Bhashini compute call rate-limited.")
        if response.status_code != 200:
            raise ProviderError(f"Bhashini compute call failed: {response.status_code} {response.text[:200]}")

        try:
            payload = response.json()
            outputs = payload["pipelineResponse"][0]["output"]
            results = [o["target"] for o in outputs]
        except (KeyError, IndexError, ValueError) as exc:
            raise ProviderError(f"Unexpected Bhashini compute response shape: {exc}") from exc

        if len(results) != len(texts):
            raise ProviderError("Bhashini returned a mismatched number of results.")
        return results
