import unittest

from steelai.physics import calculate_all


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

    def test_guardrail_warns(self):
        comp = dict(self.composition)
        comp["C"] = 0.8
        results = calculate_all(comp, set(comp))
        ms = next(r for r in results if r.key == "Ms")
        self.assertTrue(any("超出工作台审查范围" in warning for warning in ms.warnings))


if __name__ == "__main__":
    unittest.main()
