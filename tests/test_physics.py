import unittest

from steelai.physics import (
    REQUIRED_REGISTRY_FIELDS,
    calculate_all,
    compare_versions,
    compare_with_experimental_observations,
    registry_models,
    validate_model_registry,
    version_comparison_markdown,
)


class PhysicsTests(unittest.TestCase):
    def setUp(self):
        self.composition = {
            "C": 0.20, "Si": 0.25, "Mn": 1.35, "Ni": 0.20,
            "Cr": 0.65, "Mo": 0.22, "V": 0.03, "Nb": 0.025,
            "Ti": 0.018, "Al": 0.035, "Cu": 0.08, "As": 0.01,
            "B": 0.0015, "W": 0.0,
        }

    def test_all_formulas_return_values(self):
        results = calculate_all(self.composition, set(self.composition))
        self.assertEqual({r.key for r in results}, {"Ms", "Ac1", "Ac3", "Tnr", "Ceq", "Pcm"})
        self.assertTrue(all(r.value is not None for r in results))

    def test_ms_known_calculation(self):
        result = next(r for r in calculate_all(self.composition, set(self.composition)) if r.key == "Ms")
        expected = 539 - 423*0.20 - 30.4*1.35 - 17.7*0.20 - 12.1*0.65 - 7.5*0.22
        self.assertAlmostEqual(result.value, expected, places=3)

    def test_missing_fields_warn(self):
        results = calculate_all({"C": 0.2}, {"C"})
        ms = next(r for r in results if r.key == "Ms")
        self.assertTrue(any("缺少成分字段" in warning for warning in ms.warnings))
        self.assertIsNone(ms.value)
        self.assertEqual(ms.status, "skipped_missing_inputs")

    def test_guardrail_warns(self):
        comp = dict(self.composition)
        comp["C"] = 0.8
        results = calculate_all(comp, set(comp))
        ms = next(r for r in results if r.key == "Ms")
        self.assertTrue(any("超出工作台审查范围" in warning for warning in ms.warnings))

    def test_registry_contract_covers_six_families_and_all_required_metadata(self):
        status = validate_model_registry()
        self.assertEqual(status["status"], "passed", status["problems"])
        self.assertEqual(status["model_count"], 10)
        models = registry_models()
        self.assertEqual({row["model_family"] for row in models}, {"Ms", "Ac1", "Ac3", "Tnr", "Ceq", "Pcm"})
        self.assertTrue(all(REQUIRED_REGISTRY_FIELDS <= set(row) for row in models))

    def test_formula_version_selection_and_comparison_are_non_destructive(self):
        baseline = calculate_all(self.composition, set(self.composition))
        alternate = calculate_all(
            self.composition,
            set(self.composition),
            {"Ms": "ms_andrews_nonlinear_1965"},
        )
        baseline_ms = next(row for row in baseline if row.key == "Ms")
        alternate_ms = next(row for row in alternate if row.key == "Ms")
        self.assertNotEqual(baseline_ms.model_id, alternate_ms.model_id)
        self.assertNotEqual(baseline_ms.value, alternate_ms.value)
        versions = compare_versions("Ms", self.composition, set(self.composition))
        self.assertEqual(len(versions), 2)
        report = version_comparison_markdown("B-DQ", "Ms", versions)
        self.assertIn("not experimental truth", report)
        self.assertIn("without fitting or overwriting", report)

    def test_experimental_model_and_residual_values_remain_separate(self):
        result = next(row for row in calculate_all(self.composition, set(self.composition)) if row.key == "Ms")
        rows = compare_with_experimental_observations(
            "B-DQ",
            [result],
            [{
                "sample_id": "B-DQ",
                "observation_id": "OBS-BDQ-MS-01",
                "quantity": "Ms",
                "value": "400",
                "unit": "°C",
                "measurement_type": "experimental",
                "source_status": "instrument_export",
            }],
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["experimental_value"], 400.0)
        self.assertEqual(rows[0]["model_value"], result.value)
        self.assertEqual(rows[0]["residual_model_minus_experimental"], round(result.value - 400.0, 3))


if __name__ == "__main__":
    unittest.main()
