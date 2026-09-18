import math
import unittest

from steelai.thermal_softening_analysis import (
    _hollomon_projection,
    _offset_proof_stress,
    _softening_fraction,
    assess_softening_method_readiness,
    load_softening_method_registry,
)
from tests.test_t74_thermal_simulation_features import double_hit_points, run_row


class SofteningMethodReadinessTests(unittest.TestCase):
    def test_registry_contains_approved_project_owner_selection(self):
        registry = load_softening_method_registry()
        self.assertEqual(registry["selected_method_id"], "offset_2p0_srx_focused")
        self.assertEqual(registry["sensitivity_method_id"], "fixed_true_strain_0p05")
        self.assertEqual(registry["selection_status"], "approved")
        self.assertEqual(registry["method_decision"]["reviewer_id"], "yjh")
        self.assertEqual(len(registry["methods"]), 4)

    def test_resolution_diagnostic_reports_selected_method_without_computing(self):
        run = run_row()
        result = assess_softening_method_readiness([run], double_hit_points(run))
        methods = {item["method_id"]: item for item in result["method_results"]}
        self.assertEqual(result["status"], "method_selected")
        self.assertFalse(result["formal_softening_computed"])
        self.assertEqual(methods["offset_0p2_total_softening"]["resolution_status"], "under_resolved")
        self.assertGreater(
            methods["offset_2p0_srx_focused"]["median_step_coverage"],
            methods["offset_0p2_total_softening"]["median_step_coverage"],
        )

    def test_two_percent_offset_intersection_is_interpolated_without_extrapolation(self):
        method = next(
            item for item in load_softening_method_registry()["methods"]
            if item["method_id"] == "offset_2p0_srx_focused"
        )
        curve = []
        for index in range(1, 21):
            strain = index * 0.005
            stress = 1000.0 * strain if strain <= 0.02 else 20.0 + 100.0 * (strain - 0.02)
            curve.append((strain, stress))
        result = _offset_proof_stress(curve, method, interval=1)
        self.assertEqual(result["status"], "passed")
        self.assertAlmostEqual(result["proof_true_strain"], 0.0422222222, places=8)
        self.assertAlmostEqual(result["proof_stress_mpa"], 22.2222222, places=7)
        self.assertAlmostEqual(result["fit_r_squared"], 1.0, places=12)

    def test_hollomon_projection_and_common_fraction(self):
        method = next(
            item for item in load_softening_method_registry()["methods"]
            if item["method_id"] == "fixed_true_strain_0p05"
        )
        curve = [(index / 100.0, 200.0 * (index / 100.0) ** 0.2) for index in range(5, 26)]
        result = _hollomon_projection(curve, method)
        self.assertAlmostEqual(result["projection_true_strain"], 0.30, places=12)
        self.assertAlmostEqual(result["projected_stress_mpa"], 200.0 * 0.30 ** 0.2, places=10)
        self.assertAlmostEqual(result["fit_r_squared"], 1.0, places=12)
        self.assertTrue(math.isclose(_softening_fraction(100.0, 50.0, 75.0), 0.5))


if __name__ == "__main__":
    unittest.main()
