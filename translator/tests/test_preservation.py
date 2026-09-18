import sys, os, asyncio, unittest
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from translator.translator_service import TranslationService
from translator.providers.mock_provider import MockProvider
from translator.cache import TranslationCache

FIELD_CONFIG = {
    "product_name": "text",
    "status": "enum",
    "description": "text",
}

SAMPLE = {
    "product_id": "LOCAL_SNACK_002",
    "product_name": "Demo Local Snack",
    "status": "NON_COMPLIANT",
    "rules_checked": 12,
    "rules_passed": 5,
    "rules_failed": 5,
    "rules_review_required": 0,
    "rules_not_applicable": 2,
    "generated_at": "2026-09-15T12:30:00Z",
}


def run(coro):
    return asyncio.run(coro)


class TestPreservation(unittest.TestCase):
    def setUp(self):
        self.service = TranslationService(
            provider=MockProvider(),
            cache=TranslationCache(),
            field_config=FIELD_CONFIG,
        )

    def test_ids_numbers_timestamps_unchanged(self):
        result = run(self.service.translate(dict(SAMPLE), "hi"))
        out = result.data
        self.assertEqual(out["product_id"], "LOCAL_SNACK_002")
        self.assertEqual(out["rules_checked"], 12)
        self.assertEqual(out["rules_passed"], 5)
        self.assertEqual(out["rules_failed"], 5)
        self.assertEqual(out["rules_review_required"], 0)
        self.assertEqual(out["rules_not_applicable"], 2)
        self.assertEqual(out["generated_at"], "2026-09-15T12:30:00Z")

    def test_status_enum_meaning_preserved(self):
        # NON_COMPLIANT must remain exactly NON_COMPLIANT, with a
        # companion translated field, never replaced/altered.
        result = run(self.service.translate(dict(SAMPLE), "hi"))
        self.assertEqual(result.data["status"], "NON_COMPLIANT")
        self.assertIn("status_translated", result.data)
        # Glossary-curated for hi -> must be the exact curated term.
        self.assertEqual(result.data["status_translated"], "गैर-अनुपालक")

    def test_output_is_json_serializable(self):
        import json
        result = run(self.service.translate(dict(SAMPLE), "hi"))
        json.dumps(result.data, ensure_ascii=False)  # must not raise

    def test_original_input_not_mutated(self):
        original_copy = dict(SAMPLE)
        run(self.service.translate(original_copy, "hi"))
        self.assertEqual(original_copy, SAMPLE)


if __name__ == "__main__":
    unittest.main()
