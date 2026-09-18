import sys, os, unittest
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from translator import field_mapper

FIELD_CONFIG = {
    "product_name": "text",
    "status": "enum",
    "description": "text",
}


class TestFieldMapping(unittest.TestCase):
    def test_flat_extraction(self):
        data = {
            "product_id": "LOCAL_SNACK_002",
            "product_name": "Demo Local Snack",
            "status": "NON_COMPLIANT",
            "rules_checked": 12,
        }
        refs = field_mapper.extract_translatable(data, FIELD_CONFIG)
        names = {r.field_name for r in refs}
        self.assertEqual(names, {"product_name", "status"})
        # machine fields must never appear as refs
        self.assertNotIn("product_id", names)
        self.assertNotIn("rules_checked", names)

    def test_nested_list_extraction(self):
        data = {
            "product_name": "Snack",
            "rules": [
                {"rule_id": "R1", "description": "Rule one failed"},
                {"rule_id": "R2", "description": "Rule two passed"},
            ],
        }
        refs = field_mapper.extract_translatable(data, FIELD_CONFIG)
        desc_refs = [r for r in refs if r.field_name == "description"]
        self.assertEqual(len(desc_refs), 2)
        self.assertEqual(desc_refs[0].path, ["rules", 0, "description"])
        self.assertEqual(desc_refs[1].path, ["rules", 1, "description"])

    def test_empty_string_skipped(self):
        data = {"product_name": "", "status": "NON_COMPLIANT"}
        refs = field_mapper.extract_translatable(data, FIELD_CONFIG)
        names = {r.field_name for r in refs}
        self.assertNotIn("product_name", names)

    def test_reinsertion_text_mode_replaces_in_place(self):
        data = {"product_name": "Snack"}
        refs = field_mapper.extract_translatable(data, FIELD_CONFIG)
        output = field_mapper.build_output_skeleton(data)
        translations = {id(refs[0]): "स्नैक"}
        result = field_mapper.apply_translations(output, refs, translations)
        self.assertEqual(result["product_name"], "स्नैक")

    def test_reinsertion_enum_mode_adds_sibling_key(self):
        data = {"status": "NON_COMPLIANT"}
        refs = field_mapper.extract_translatable(data, FIELD_CONFIG)
        output = field_mapper.build_output_skeleton(data)
        translations = {id(refs[0]): "गैर-अनुपालक"}
        result = field_mapper.apply_translations(output, refs, translations)
        self.assertEqual(result["status"], "NON_COMPLIANT")  # untouched
        self.assertEqual(result["status_translated"], "गैर-अनुपालक")

    def test_deep_copy_does_not_mutate_input(self):
        data = {"product_name": "Snack", "nested": {"description": "text here"}}
        refs = field_mapper.extract_translatable(data, FIELD_CONFIG)
        output = field_mapper.build_output_skeleton(data)
        translations = {id(r): "TRANSLATED" for r in refs}
        field_mapper.apply_translations(output, refs, translations)
        self.assertEqual(data["product_name"], "Snack")  # original untouched
        self.assertEqual(data["nested"]["description"], "text here")


if __name__ == "__main__":
    unittest.main()
