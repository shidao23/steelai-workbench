import unittest

from steelai.v01_adapter import evaluate, is_available


class V01AdapterTests(unittest.TestCase):
    @unittest.skipUnless(is_available(), "本机未配置 WearSteel-AI v0.1")
    def test_connects_all_v01_models_without_filling_unknowns(self):
        rows, composition, metadata = evaluate("B")
        self.assertEqual(len(rows), 13)
        self.assertIsNone(composition["W"])
        self.assertEqual(metadata["verification_status"], "verified_from_source_note")
        self.assertTrue(any(row["status"] == "SKIPPED" for row in rows))


if __name__ == "__main__":
    unittest.main()
