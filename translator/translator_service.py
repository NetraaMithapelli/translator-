"""
translator_service.py
-----------------------
The orchestrator. This is the one place that ties together config,
glossary, cache, field_mapper, and a TranslatorProvider into the
end-to-end "translate this compliance payload" operation.

Pipeline (mirrors spec section 6):
  1. Validate target_language against config.SUPPORTED_LANGUAGES.
  2. field_mapper.extract_translatable() walks the payload and returns a
     list of FieldRef -- every string the config says is human-readable,
     wherever it lives in the (possibly nested) structure.
  3. For each ref:
       - "enum" fields try glossary.lookup() first. A hit resolves
         immediately, no network call, guaranteed-correct terminology.
       - Everything else (glossary miss, or "text" mode) is checked
         against the cache next.
       - What's left after glossary+cache is the actual provider workload.
  4. The leftover strings are deduplicated and sent to the provider in
     ONE call (translate_batch), not one call per field -- this is the
     batching requirement in spec section 9. Results are cached for next
     time.
  5. field_mapper.apply_translations() writes everything back into a
     deep copy of the input, so the original request object is never
     mutated and every machine-readable field is passed through byte-for-
     byte because it was never extracted in the first place.
  6. Timing is measured around step 4 specifically (provider_latency_ms)
     and around the whole pipeline (backend_latency_ms), so a slow
     response can be diagnosed as "the provider was slow" vs "our own
     JSON walking was slow" (spec section 13).

Error handling: this function raises the provider's typed exceptions
(ProviderTimeoutError etc.) rather than swallowing them -- api.py is
responsible for turning those into the documented error codes. If ANY
provider call fails, apply_translations() is never reached, so we never
return a half-translated payload as if it succeeded (spec section 12).
"""

import time
from dataclasses import dataclass, field
from typing import Any, Optional

from . import config
from . import glossary
from . import field_mapper
from .cache import TranslationCache
from .providers.base import TranslatorProvider


class InvalidLanguageError(Exception):
    pass


class InvalidRequestError(Exception):
    pass


@dataclass
class TranslationResult:
    data: Any
    target_language: str
    provider_name: str
    total_backend_latency_ms: float
    provider_latency_ms: float
    fields_translated: int
    fields_from_cache: int
    fields_from_glossary: int
    provider_calls_made: int


class TranslationService:
    def __init__(
        self,
        provider: TranslatorProvider,
        cache: Optional[TranslationCache] = None,
        field_config: Optional[dict] = None,
    ):
        self.provider = provider
        self.cache = cache or TranslationCache(ttl_seconds=config.TRANSLATION_CACHE_TTL_SECONDS)
        self.field_config = field_config or config.FIELD_CONFIG

    async def translate(self, data: Any, target_language: str) -> TranslationResult:
        start = time.perf_counter()

        if target_language not in config.SUPPORTED_LANGUAGES:
            raise InvalidLanguageError(f"Unsupported target_language: {target_language!r}")
        if data is None:
            raise InvalidRequestError("`data` must not be null.")

        refs = field_mapper.extract_translatable(data, self.field_config)
        output = field_mapper.build_output_skeleton(data)

        # resolved maps id(ref) -> translated string, filled in as we go
        # through glossary -> cache -> provider, in that order of preference.
        resolved: dict[int, str] = {}
        from_glossary = 0
        from_cache = 0

        # --- Step 1: glossary (enum fields only, zero latency) ---
        remaining_refs = []
        for ref in refs:
            if ref.mode == "enum":
                hit = glossary.lookup(ref.original_value, target_language)
                if hit is not None:
                    resolved[id(ref)] = hit
                    from_glossary += 1
                    continue
            remaining_refs.append(ref)

        # --- Step 2: cache ---
        still_remaining = []
        for ref in remaining_refs:
            cached = self.cache.get(ref.original_value, target_language)
            if cached is not None:
                resolved[id(ref)] = cached
                from_cache += 1
            else:
                still_remaining.append(ref)

        # --- Step 3: provider, batched ---
        # De-duplicate identical source strings so e.g. the same rule
        # description repeated across two rules only costs one slot in
        # the batch, not two.
        unique_texts: list[str] = []
        text_to_refs: dict[str, list] = {}
        for ref in still_remaining:
            text_to_refs.setdefault(ref.original_value, []).append(ref)
        unique_texts = list(text_to_refs.keys())

        provider_latency_ms = 0.0
        provider_calls_made = 0
        if unique_texts:
            provider_start = time.perf_counter()
            translated_unique = await self.provider.translate_batch(unique_texts, target_language)
            provider_latency_ms = (time.perf_counter() - provider_start) * 1000
            provider_calls_made = 1

            for source_text, translated_text in zip(unique_texts, translated_unique):
                self.cache.set(source_text, target_language, translated_text)
                for ref in text_to_refs[source_text]:
                    resolved[id(ref)] = translated_text

        # Sanity check: every extracted ref must be resolved before we
        # touch the output. This should be unreachable if the above logic
        # is correct, but it's a cheap, important guard against ever
        # emitting a partially-translated payload.
        missing = [r for r in refs if id(r) not in resolved]
        if missing:
            raise RuntimeError(
                f"{len(missing)} field(s) were not resolved by glossary, cache, or provider "
                f"(e.g. {missing[0].field_name!r}) -- refusing to return partial output."
            )

        field_mapper.apply_translations(output, refs, resolved)

        total_backend_latency_ms = (time.perf_counter() - start) * 1000

        return TranslationResult(
            data=output,
            target_language=target_language,
            provider_name=self.provider.name,
            total_backend_latency_ms=total_backend_latency_ms,
            provider_latency_ms=provider_latency_ms,
            fields_translated=len(refs),
            fields_from_cache=from_cache,
            fields_from_glossary=from_glossary,
            provider_calls_made=provider_calls_made,
        )
