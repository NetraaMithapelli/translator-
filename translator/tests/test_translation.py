import sys, os, asyncio, unittest
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from translator.translator_service import (
    TranslationService, InvalidLanguageError, InvalidRequestError,
)
from translator.providers.mock_provider import MockProvider
from translator.providers.base import ProviderTimeoutError, ProviderRateLimitError, ProviderError
from translator.cache import TranslationCache

FIELD_CONFIG = {
    "product_name": "text",
    "status": "enum",
    "description": "text",
    "recommendation": "text",
}


def run(coro):
    return asyncio.run(coro)


class TestNormalTranslation(unittest.TestCase):
    def test_translates_configured_fields(self):
        provider = MockProvider()
        service = TranslationService(provider, TranslationCache(), FIELD_CONFIG)
        data = {"product_name": "Demo Local Snack", "status": "NON_COMPLIANT"}
        result = run(service.translate(data, "hi"))
        self.assertEqual(result.data["product_name"], "[hi] Demo Local Snack")
        self.assertEqual(result.data["status_translated"], "गैर-अनुपालक")  # glossary, not mock provider

    def test_multiple_languages_supported(self):
        provider = MockProvider()
        service = TranslationService(provider, TranslationCache(), FIELD_CONFIG)
        for lang in ["hi", "mr", "bn", "ta", "te", "gu", "kn", "ml", "pa", "or"]:
            result = run(service.translate({"product_name": "Snack"}, lang))
            self.assertEqual(result.data["product_name"], f"[{lang}] Snack")


class TestBatching(unittest.TestCase):
    def test_multiple_fields_use_a_single_provider_call(self):
        provider = MockProvider()
        service = TranslationService(provider, TranslationCache(), FIELD_CONFIG)
        data = {
            "product_name": "Demo Local Snack",
            "description": "Rule failed because of X",
            "recommendation": "Add nutrition label",
        }
        result = run(service.translate(data, "hi"))
        self.assertEqual(provider.call_count, 1)
        self.assertEqual(provider.last_batch_size, 3)
        self.assertEqual(result.provider_calls_made, 1)

    def test_duplicate_strings_deduplicated_in_batch(self):
        provider = MockProvider()
        service = TranslationService(provider, TranslationCache(), FIELD_CONFIG)
        data = {
            "description": "Same text",
            "recommendation": "Same text",
        }
        result = run(service.translate(data, "hi"))
        self.assertEqual(provider.last_batch_size, 1)  # deduplicated
        self.assertEqual(result.data["description"], "[hi] Same text")
        self.assertEqual(result.data["recommendation"], "[hi] Same text")


class TestCaching(unittest.TestCase):
    def test_second_call_hits_cache_not_provider(self):
        provider = MockProvider()
        cache = TranslationCache()
        service = TranslationService(provider, cache, FIELD_CONFIG)
        run(service.translate({"product_name": "Demo Local Snack"}, "hi"))
        self.assertEqual(provider.call_count, 1)
        result2 = run(service.translate({"product_name": "Demo Local Snack"}, "hi"))
        self.assertEqual(provider.call_count, 1)  # unchanged: no second provider call
        self.assertEqual(result2.fields_from_cache, 1)


class TestErrorHandling(unittest.TestCase):
    def test_unsupported_language_raises(self):
        provider = MockProvider()
        service = TranslationService(provider, TranslationCache(), FIELD_CONFIG)
        with self.assertRaises(InvalidLanguageError):
            run(service.translate({"product_name": "Snack"}, "xx"))

    def test_null_data_raises(self):
        provider = MockProvider()
        service = TranslationService(provider, TranslationCache(), FIELD_CONFIG)
        with self.assertRaises(InvalidRequestError):
            run(service.translate(None, "hi"))

    def test_provider_timeout_propagates(self):
        provider = MockProvider(fail_mode="timeout")
        service = TranslationService(provider, TranslationCache(), FIELD_CONFIG)
        with self.assertRaises(ProviderTimeoutError):
            run(service.translate({"product_name": "Snack"}, "hi"))

    def test_provider_failure_does_not_return_partial_success(self):
        provider = MockProvider(fail_mode="error")
        service = TranslationService(provider, TranslationCache(), FIELD_CONFIG)
        with self.assertRaises(ProviderError):
            run(service.translate({"product_name": "Snack"}, "hi"))

    def test_rate_limit_propagates(self):
        provider = MockProvider(fail_mode="rate_limit")
        service = TranslationService(provider, TranslationCache(), FIELD_CONFIG)
        with self.assertRaises(ProviderRateLimitError):
            run(service.translate({"product_name": "Snack"}, "hi"))


class TestEmptyAndNullFields(unittest.TestCase):
    def test_empty_and_missing_fields_handled_safely(self):
        provider = MockProvider()
        service = TranslationService(provider, TranslationCache(), FIELD_CONFIG)
        data = {"product_name": "", "status": "NON_COMPLIANT", "description": None}
        result = run(service.translate(data, "hi"))
        self.assertEqual(result.data["product_name"], "")  # untouched, nothing to translate
        self.assertIsNone(result.data.get("description"))
        self.assertEqual(result.data["status_translated"], "गैर-अनुपालक")

    def test_glossary_miss_falls_back_to_provider(self):
        # "or" (Odia) has no curated glossary entry -> should fall back
        # to translating the canonical English enum label via provider.
        provider = MockProvider()
        service = TranslationService(provider, TranslationCache(), FIELD_CONFIG)
        result = run(service.translate({"status": "NON_COMPLIANT"}, "or"))
        self.assertEqual(result.data["status"], "NON_COMPLIANT")
        self.assertEqual(result.data["status_translated"], "[or] NON_COMPLIANT")
        self.assertEqual(provider.call_count, 1)


if __name__ == "__main__":
    unittest.main()
