"""T86 CALPHAD phase-fraction adapter: gates, units, provenance and blocking behaviour.

pycalphad is deliberately **not** installed and no TDB exists in this repository, so these
tests verify the contract around the calculation: every blocking gate, the unit/output-basis
declarations, the Fe-balance confirmation, element coverage, the worker-output validation and
the fact that the existing Physics formulas keep working without the optional adapter.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import unittest
import uuid
from pathlib import Path

from steelai.calphad_adapter import (
    ADAPTER_VERSION,
    BATCH_SOLVER_MODE,
    INDEPENDENT_SOLVER_MODE,
    MATRIX_ACKNOWLEDGEMENT_TEXT,
    PORTFOLIO_DEMO_FLAGS,
    PORTFOLIO_DEMO_POLICY_PATH,
    PORTFOLIO_DEMO_REQUIRED_PHASES,
    PORTFOLIO_STATUS_COMPLETE,
    PORTFOLIO_STATUS_PENDING_SIGNATURE,
    PORTFOLIO_ACCEPTANCE_INDEX_PATH,
    OWNER_ACCEPTANCE_PATH,
    OWNER_ACCEPTANCE_RECORD_ID,
    SCIENTIFIC_STATUS_BLOCKED,
    PROHIBITED_RESULT_LABELS,
    REQUIRED_MATRIX_ELEMENTS,
    REQUIRED_MATRIX_PHASES,
    REQUIRED_TDB_FIELDS,
    RESULT_LABEL_MATRIX,
    approved_exclusions_for,
    assess_composition,
    calphad_feature_status,
    feature_enabled,
    load_adapter_config,
    load_exclusion_policy,
    load_portfolio_demo_policy,
    load_reduced_system_policy,
    load_tdb_registry,
    owner_acceptance_status,
    phase_fraction_csv,
    phase_fraction_curve_markdown,
    phase_fraction_rows,
    preview_phase_fraction_curve,
    preview_portfolio_demo,
    probe_isolated_environment,
    run_phase_fraction_curve,
    select_database,
    status_row,
    summarize_phase_amounts,
    validate_adapter_registry,
    validate_exclusion_policy,
    validate_owner_acceptance,
    validate_portfolio_demo_policy,
    validate_reduced_system_policy,
    validate_tdb_registration,
    validate_tdb_template,
)
from steelai.model_lab import MODEL_REGISTRY, model_statuses
from steelai.governance.serialization import digest_value
from steelai.paths import OUTPUTS, ROOT
from steelai.physics import calculate_all


#: Scratch lives inside the workspace (``outputs/`` is git-ignored) because the
#: platform temporary directory cannot always be cleaned up on Windows.
SCRATCH_ROOT = OUTPUTS / "_t86_scratch"


COVERED_ELEMENTS = [
    "Fe", "C", "Si", "Mn", "Cr", "Ni", "Mo", "Nb", "V", "Ti",
    "Al", "Cu", "P", "S", "N", "B", "O", "W",
]
#: Mirrors the registered community database: As/Sn/Sb are NOT covered, B/N/P/S are.
COVERED_ELEMENTS_WITH_AS_SN_SB = COVERED_ELEMENTS + ["As", "Sn", "Sb"]
#: The fixed phase profile must exist in the registered database.
COVERED_PHASES = [
    "LIQUID", "FCC_A1", "BCC_A2", "CEMENTITE", "M23C6", "M7C3", "M6C",
    "ALN", "BN_HP4", "FE4N", "M2B", "FEB", "M2P", "M3P", "SIGMA", "GRAPHITE",
]
COMPOSITION = {
    "C": 0.19, "Si": 0.25, "Mn": 1.35, "Ni": 0.20, "Cr": 0.65, "Mo": 0.22,
    "V": 0.03, "Nb": 0.025, "Ti": 0.018, "Al": 0.035, "Cu": 0.08,
    "P": 0.012, "S": 0.005, "N": 0.004, "B": 0.0015,
    # Mirrors the registered B-DQ semantics: As/Sn/Sb measured as exactly zero,
    # O/W declared as columns with no measured value (never treated as zero).
    "As": 0.0, "Sn": 0.0, "Sb": 0.0, "O": None, "W": None,
}
#: The committed phase-4 reduced-system policy; the tests exercise the real file.
REDUCED_POLICY_PATH = ROOT / "config" / "calphad_reduced_system_v1.0.json"
REDUCED_APPROVAL = {
    "reduced_system_reviewer_id": "unit-test-reviewer",
    "reduced_system_approved_at": "2026-09-25",
    "reduced_system_approval_reason": "unit-test reduced-system approval",
    "reduced_system_acknowledged": True,
}
READY_ENVIRONMENT = {
    "status": "ready",
    "interpreter": sys.executable,
    "pycalphad_version": "0.11.2",
    "installed": True,
    "detail": "test double",
}
COMPATIBILITY_PASSED = {
    "status": "passed",
    "pinned_pycalphad_version": "0.11.2",
    "python": "CPython 3.12.14",
    "checked_at": "2026-09-25",
    "checked_with": "scripts/calphad_compatibility_gate.py",
    "evidence": "unit-test fixture",
}
#: The production notice, taken from the committed policy so the tests exercise the real wording.
COMMITTED_LIMITATION_NOTICE = json.loads(
    (ROOT / "config" / "calphad_exclusion_policy_v1.2.json").read_text(encoding="utf-8")
)["limitation_notice"]
#: Database identity the currently committed exclusion policy is bound to.
COMMITTED_POLICY_DATABASE_ID = "MATCALC-MC-FE-V2062-COMMUNITY-CLEAN-19B1164"
#: SHA-256 of the registered community derivative candidate.
COMMUNITY_CANDIDATE_SHA256 = "7cf37dd423e14264ee67467011b6cb0ea90647fc365823899c29f7e827a12042"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


class _AdapterCase(unittest.TestCase):
    """Shared helpers for temporary TDB registries and fake isolated workers."""

    def setUp(self) -> None:
        self.temp = SCRATCH_ROOT / f"case-{uuid.uuid4().hex}"
        self.temp.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, self.temp, ignore_errors=True)

    def write_tdb(self, *, content: bytes = b"$ test database\n") -> Path:
        path = self.temp / "authorized_steel.tdb"
        path.write_bytes(content)
        return path

    def write_registry(self, entry_overrides: dict | None = None, *, tdb_content: bytes = b"$ test database\n") -> Path:
        tdb_path = self.write_tdb(content=tdb_content)
        entry = {
            "database_id": "TEST-TDB-V1",
            "path": str(tdb_path),
            "sha256": _sha256_file(tdb_path),
            "format": "thermo-calc_tdb",
            "provider": "unit-test provider",
            "version_or_date": "2026-01-01",
            "license_or_authorization": "written authorization recorded by the test fixture",
            "authorization_status": "user_confirmed_authorized_for_this_steel_grade",
            "authorized_by": "unit-test-reviewer",
            "authorized_at": "2026-09-24",
            "applicable_steel_grades": ["unit-test steel"],
            "covered_elements": list(COVERED_ELEMENTS),
            "covered_phases": list(COVERED_PHASES),
            "declared_temperature_range_C": [500, 1200],
            "declared_pressure_Pa": 101325,
            "citation": "unit-test fixture, not a real database",
            "notes": "not a real thermodynamic database",
            "pycalphad_compatibility": dict(COMPATIBILITY_PASSED),
        }
        entry.update(entry_overrides or {})
        registry_path = self.temp / "calphad_tdb.local.json"
        registry_path.write_text(
            json.dumps(
                {
                    "registry_id": "SteelAI-CALPHAD-TDB-Local-v1.0",
                    "schema_version": "1.0",
                    "databases": [entry],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return registry_path

    def write_policy(
        self,
        *,
        sample_id: str = "B-DQ",
        database_id: str = "TEST-TDB-V1",
        approved_exclusions: list[dict] | None = None,
        extra: dict | None = None,
    ) -> Path:
        policy = {
            "policy_id": "SteelAI-CALPHAD-Exclusion-Policy-v1.0",
            "schema_version": "1.0",
            "approved_at": "2026-09-25",
            "approved_by": "unit-test-reviewer",
            "database_scope": {"database_id": database_id, "version": "2026-01-01"},
            "generic_element_ignore_switch": False,
            "requires_named_confirmer": True,
            "allowed_categories": {
                "database_not_covered": "not in the database",
                "measured_zero": "measured as zero",
                "input_unknown": "no measured value",
                "capacity_reduction": "measured but excluded by the fixed reduced-system profile",
            },
            "reduced_system_policy": {
                "policy_file": "config/calphad_reduced_system_v1.0.json",
                "component_profile_id": "steel_matrix_equilibrium_v1",
                "phase_profile_id": "steel_matrix_major_carbides_v1",
            },
            "approved_exclusions": approved_exclusions if approved_exclusions is not None else [
                {"sample_id": sample_id, "elements": ["O", "W"], "category": "input_unknown", "reason": "no measured value"},
                {"sample_id": sample_id, "elements": ["As", "Sn", "Sb"], "category": "measured_zero", "reason": "measured as zero"},
                {"sample_id": sample_id, "elements": ["B", "N", "P", "S"], "category": "capacity_reduction",
                 "reason": "fixed reduced-system profile keeps the component list inside the solver capacity limit"},
            ],
            "limitation_notice": dict(COMMITTED_LIMITATION_NOTICE),
        }
        policy.update(extra or {})
        path = self.temp / f"exclusion_policy_{uuid.uuid4().hex[:8]}.json"
        path.write_text(json.dumps(policy, ensure_ascii=False), encoding="utf-8")
        return path

    @staticmethod
    def reduced_defaults() -> dict:
        """The phase-4 fixed-profile approval that every real-sample preview needs."""
        return {"reduced_system_policy_path": REDUCED_POLICY_PATH, **REDUCED_APPROVAL}

    def write_reduced_policy(self, mutate=None) -> Path:
        """A copy of the committed reduced-system policy with an optional mutation applied."""
        policy = json.loads(REDUCED_POLICY_PATH.read_text(encoding="utf-8"))
        if mutate is not None:
            mutate(policy)
        path = self.temp / f"reduced_policy_{uuid.uuid4().hex[:8]}.json"
        path.write_text(json.dumps(policy, ensure_ascii=False), encoding="utf-8")
        return path

    def preview_direct(self, composition, **kwargs):
        """Call the adapter with the phase-4 defaults unless the caller overrides them."""
        merged = {**self.reduced_defaults(), **kwargs}
        return preview_phase_fraction_curve(composition, **merged)

    def preview(self, **overrides):
        kwargs = {
            "sample_id": "B-DQ",
            "temperature_min_C": 600,
            "temperature_max_C": 700,
            "step_C": 50,
            "fe_balance_confirmed_by": "unit-test-reviewer",
            "controlled_exclusions_confirmed_by": "unit-test-reviewer",
            "registry_path": self.write_registry(),
            "exclusion_policy_path": self.write_policy(),
            "environment": READY_ENVIRONMENT,
        }
        kwargs.update(overrides)
        return self.preview_direct(COMPOSITION, **kwargs)

    def write_demo_policy(self, registry_path: Path | None = None, mutate=None) -> Path:
        """A copy of the committed portfolio-demo policy bound to the fixture registry hash."""
        policy = json.loads(PORTFOLIO_DEMO_POLICY_PATH.read_text(encoding="utf-8"))
        if registry_path is not None:
            entry = json.loads(Path(registry_path).read_text(encoding="utf-8"))["databases"][0]
            policy["database"]["sha256"] = entry["sha256"]
        if mutate is not None:
            mutate(policy)
        path = self.temp / f"demo_policy_{uuid.uuid4().hex[:8]}.json"
        path.write_text(json.dumps(policy, ensure_ascii=False), encoding="utf-8")
        return path

    def demo_registry(self) -> Path:
        return self.write_registry({"declared_temperature_range_C": [400, 1727]})

    def demo_preview(self, **overrides):
        registry_path = overrides.pop("registry_path", None) or self.demo_registry()
        kwargs = {
            "registry_path": registry_path,
            "demo_policy_path": self.write_demo_policy(registry_path),
            "environment": READY_ENVIRONMENT,
        }
        kwargs.update(overrides)
        return preview_portfolio_demo(**kwargs)

    @staticmethod
    def codes(preview) -> list[str]:
        return [gate.code for gate in preview.gates]

    @staticmethod
    def fake_runner(overrides: dict | None = None):
        """A single-point worker double: one call per temperature, phases alternate by call order."""
        calls = {"count": 0}

        def runner(request, *, interpreter, workdir, timeout_seconds):
            temperatures = [float(value) for value in request["temperature"]["values_C"]]
            points = []
            for offset, temperature in enumerate(temperatures):
                index = calls["count"] + offset
                fractions = {"BCC_A2": 1.0} if index == 0 else {"FCC_A1": 1.0}
                points.append({
                    "temperature_C": temperature,
                    "temperature_K": round(temperature + 273.15, 6),
                    "total_moles": 1.0,
                    "phase_fractions_mole": fractions,
                    "raw_phase_amounts_mole": fractions,
                    "phases_present": sorted(fractions),
                })
            calls["count"] += len(temperatures)
            payload = {
                "worker_schema_version": "1.1",
                "status": "ok",
                "pycalphad_version": request["pycalphad_version"],
                "python_version": "3.12.14",
                "phases": list(request.get("phases", [])),
                "components": list(request.get("components", [])),
                # The worker always adds the vacancy species; the single-point contract checks it.
                "pycalphad_components": list(request.get("components", [])) + ["VA"],
                "component_profile_id": (request.get("component_profile") or {}).get("profile_id"),
                "phase_profile_id": (request.get("phase_profile") or {}).get("profile_id"),
                "solver_mode": request.get("solver_mode"),
                "single_point_process": bool(request.get("single_point_process")),
                "point_index": request.get("point_index"),
                "point_count": request.get("point_count"),
                "points": points,
                "warnings": [],
                "elapsed_s": 0.25,
            }
            payload.update(overrides or {})
            return {"returncode": 0, "payload": payload, "stdout_tail": "", "stderr_tail": ""}

        return runner


class RegistrationTests(_AdapterCase):
    def test_committed_adapter_registry_passes_and_pins_pycalphad(self):
        report = validate_adapter_registry()
        self.assertEqual(report["status"], "passed", report["problems"])
        self.assertEqual(report["component_version"], "0.11.2")
        self.assertEqual(report["pin_status"], "pinned_and_installed_in_isolated_environment")
        self.assertTrue(report["authorized_database_present"])

    def test_registration_records_official_source_license_and_hashes(self):
        component = load_adapter_config()["component"]
        self.assertEqual(component["name"], "pycalphad")
        self.assertEqual(component["license_spdx"], "MIT")
        self.assertEqual(component["license_status"], "verified_osi")
        self.assertEqual(component["official_repo"], "https://github.com/pycalphad/pycalphad")
        self.assertIn("0.11.2", component["release_url"])
        self.assertIn("0.11.2", component["license_url"])
        self.assertEqual(len(component["source_ref"]), 40)
        self.assertEqual(
            component["artifacts"]["cp312_win_amd64"]["sha256"],
            "53f6547738d02abb7349606548cce11747e22fc8a1308a1b866fb627e713ac58",
        )

    def test_pycalphad_is_not_a_core_dependency(self):
        for name in ("requirements.txt", "requirements-dev.txt", "requirements-enterprise.txt"):
            text = (ROOT / name).read_text(encoding="utf-8").lower()
            self.assertNotIn("pycalphad", text, name)
        self.assertFalse(load_adapter_config()["isolated_environment"]["main_requirements_modified"])

    def test_tdb_template_carries_every_required_field(self):
        report = validate_tdb_template()
        self.assertEqual(report["status"], "passed", report["problems"])
        template = json.loads((ROOT / "config" / "calphad_tdb.example.json").read_text(encoding="utf-8"))
        self.assertTrue(REQUIRED_TDB_FIELDS <= set(template["databases"][0]))
        self.assertFalse(load_adapter_config()["database"]["registered_databases"])

    def test_modified_registry_fails_closed(self):
        registry = load_adapter_config()
        registry["component"]["code_imported"] = True
        path = self.temp / "bad_registry.json"
        path.write_text(json.dumps(registry, ensure_ascii=False), encoding="utf-8")
        report = validate_adapter_registry(path)
        self.assertEqual(report["status"], "failed")
        self.assertIn("第三方代码不得复制入仓库", " ".join(report["problems"]))


class EnvironmentGateTests(_AdapterCase):
    def test_default_state_is_blocked_without_environment_or_database(self):
        environment = {"status": "not_configured", "detail": "无隔离解释器", "interpreter": None}
        status = calphad_feature_status(environment=environment, registry_path=self.temp / "missing.json")
        self.assertEqual(status["state"], "blocked")
        self.assertTrue(status["enabled"])
        self.assertIn("不影响既有物理计算", status["headline"])
        self.assertEqual(status["result_type"], "model_prediction_not_experimental_measurement")

    def test_feature_can_be_switched_off_and_physics_still_runs(self):
        os.environ["STEELAI_CALPHAD_ENABLED"] = "false"
        self.addCleanup(os.environ.pop, "STEELAI_CALPHAD_ENABLED", None)
        self.assertFalse(feature_enabled())
        preview = self.preview_direct(COMPOSITION, sample_id="B-DQ")
        self.assertEqual(preview.state, "disabled")
        self.assertEqual(self.codes(preview), ["CALPHAD-DISABLED-001"])
        self.assertIsNone(preview.request)
        status = calphad_feature_status()
        self.assertEqual(status["state"], "disabled")
        self.assertFalse(status["enabled"])

        # The empirical Physics path needs a complete input set, so O/W are supplied here; the
        # CALPHAD composition above deliberately leaves them unmeasured.
        physics_composition = {**COMPOSITION, "O": 0.002, "W": 0.0}
        results = calculate_all(physics_composition, set(physics_composition))
        self.assertEqual(len(results), 6)
        self.assertTrue(all(result.value is not None for result in results))

    def test_missing_configured_interpreter_blocks_before_any_calculation(self):
        os.environ["STEELAI_CALPHAD_PYTHON"] = str(self.temp / "no-such-python.exe")
        self.addCleanup(os.environ.pop, "STEELAI_CALPHAD_PYTHON", None)
        environment = probe_isolated_environment(
            {"source": "environment_variable", "path": os.environ["STEELAI_CALPHAD_PYTHON"], "exists": False},
            "0.11.2",
        )
        self.assertEqual(environment["status"], "interpreter_missing")
        preview = self.preview_direct(COMPOSITION, environment=environment, registry_path=self.write_registry())
        self.assertEqual(preview.state, "blocked")
        self.assertIn("CALPHAD-ENV-001", self.codes(preview))
        self.assertIsNone(preview.request)

    def test_missing_dependency_in_a_real_interpreter_is_detected(self):
        configuration = {"source": "test", "path": sys.executable, "exists": True}
        environment = probe_isolated_environment(configuration, "0.11.2")
        self.assertIn(environment["status"], {"dependency_missing", "version_mismatch"})
        if environment["status"] == "dependency_missing":
            self.assertFalse(environment["installed"])
            self.assertIn("CALPHAD-ENV-002", self.codes(self.preview_direct(
                COMPOSITION, environment=environment, registry_path=self.write_registry()
            )))

    def test_version_mismatch_blocks(self):
        environment = {**READY_ENVIRONMENT, "status": "version_mismatch", "pycalphad_version": "0.10.4"}
        preview = self.preview_direct(COMPOSITION, environment=environment, registry_path=self.write_registry())
        self.assertIn("CALPHAD-ENV-003", self.codes(preview))

    def test_adapter_never_imports_pycalphad_into_the_main_process(self):
        status_row()
        calphad_feature_status(environment=READY_ENVIRONMENT, registry_path=self.temp / "missing.json")
        self.assertNotIn("pycalphad", sys.modules)


class DatabaseGateTests(_AdapterCase):
    def test_missing_registry_file_blocks(self):
        preview = self.preview_direct(
            COMPOSITION, environment=READY_ENVIRONMENT, registry_path=self.temp / "absent.json"
        )
        self.assertEqual(preview.state, "blocked")
        self.assertIn("CALPHAD-TDB-000", self.codes(preview))
        self.assertIn("calphad_tdb.example.json", preview.gates[0].message)

    def test_hash_mismatch_blocks(self):
        registry_path = self.write_registry(
            {"sha256": "0" * 64},
        )
        preview = self.preview_direct(
            COMPOSITION, environment=READY_ENVIRONMENT, registry_path=registry_path
        )
        self.assertIn("CALPHAD-TDB-001", self.codes(preview))
        self.assertIn("SHA-256", " ".join(preview.database["problems"]))
        self.assertIsNone(preview.request)

    def test_missing_file_blocks(self):
        registry_path = self.write_registry({"path": str(self.temp / "gone.tdb")})
        report = validate_tdb_registration(json.loads(registry_path.read_text(encoding="utf-8"))["databases"][0])
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["file_status"], "missing")

    def test_unauthorized_database_blocks(self):
        registry_path = self.write_registry({
            "authorization_status": "unknown",
            "authorized_by": "",
            "license_or_authorization": "",
        })
        entry = json.loads(registry_path.read_text(encoding="utf-8"))["databases"][0]
        report = validate_tdb_registration(entry)
        self.assertEqual(report["status"], "failed")
        text = " ".join(report["problems"])
        self.assertIn("授权状态", text)
        self.assertIn("authorized_by", text)
        self.assertIn("许可或书面授权依据", text)

    def test_invalid_registry_json_blocks(self):
        path = self.temp / "broken.json"
        path.write_text("{not json", encoding="utf-8")
        loaded = load_tdb_registry(path)
        self.assertEqual(loaded["status"], "invalid")
        preview = self.preview_direct(
            COMPOSITION, environment=READY_ENVIRONMENT, registry_path=path
        )
        self.assertIn("CALPHAD-TDB-001", self.codes(preview))

    def test_unknown_database_id_blocks(self):
        preview = self.preview_direct(
            COMPOSITION,
            database_id="NOPE",
            environment=READY_ENVIRONMENT,
            registry_path=self.write_registry(),
        )
        self.assertIn("CALPHAD-TDB-006", self.codes(preview))


class CompositionGateTests(_AdapterCase):
    def test_uncovered_nonzero_element_blocks_without_any_override(self):
        registry_path = self.write_registry({"covered_elements": ["Fe", "C", "Mn", "Si"]})
        preview = self.preview_direct(
            COMPOSITION,
            environment=READY_ENVIRONMENT,
            registry_path=registry_path,
            fe_balance_confirmed_by="unit-test-reviewer",
        )
        self.assertEqual(preview.state, "blocked")
        self.assertIn("CALPHAD-COMP-002", self.codes(preview))
        message = next(gate.message for gate in preview.gates if gate.code == "CALPHAD-COMP-002")
        self.assertIn("Cr", message)
        self.assertIn("不省略、不补零", message)
        self.assertIsNone(preview.request)

    def test_zero_valued_uncovered_elements_are_recorded_not_zero_filled(self):
        registry_path = self.write_registry({
            "covered_elements": [element for element in COVERED_ELEMENTS if element not in {"As", "Sn", "Sb"}],
        })
        preview = self.preview_direct(
            COMPOSITION, sample_id="B-DQ", environment=READY_ENVIRONMENT, registry_path=registry_path,
            exclusion_policy_path=self.write_policy(),
            fe_balance_confirmed_by="unit-test-reviewer",
            controlled_exclusions_confirmed_by="unit-test-reviewer",
        )
        self.assertEqual(preview.state, "ready", self.codes(preview))
        composition = preview.composition
        self.assertEqual(composition["zero_wt_pct_elements"], ["As", "Sb", "Sn"])
        self.assertEqual(composition["uncovered_zero_elements"], ["As", "Sb", "Sn"])
        self.assertEqual(composition["uncovered_nonzero_elements"], [])
        excluded = composition["excluded_elements"]
        for element in ("As", "Sn", "Sb"):
            self.assertEqual(excluded[element], "declared_zero_wt_pct_and_not_in_database")
        self.assertTrue(any("已记录为排除项" in warning for warning in preview.warnings))
        self.assertNotIn("As", preview.request["component_mole_fractions"])
        controlled = {item["element"]: item for item in preview.request["controlled_exclusions"]}
        self.assertEqual(controlled["As"]["category"], "measured_zero")
        self.assertEqual(controlled["As"]["value_status"], "measured")
        self.assertEqual(controlled["As"]["value_wt_pct"], 0.0)

    def test_controlled_exclusion_replaces_the_legacy_declaration(self):
        """Unmeasured elements are only excluded through the versioned policy plus a named confirmer."""
        composition = {**COMPOSITION, "O": None, "W": None}

        # 1. No policy approval for these elements -> strict block, exactly as before.
        strict_policy = self.write_policy(approved_exclusions=[])
        strict = self.preview_direct(
            composition, sample_id="B-DQ", environment=READY_ENVIRONMENT,
            registry_path=self.write_registry(),
            exclusion_policy_path=strict_policy,
            fe_balance_confirmed_by="unit-test-reviewer",
            controlled_exclusions_confirmed_by="unit-test-reviewer",
        )
        self.assertIn("CALPHAD-COMP-001", self.codes(strict))
        message = next(gate.message for gate in strict.gates if gate.code == "CALPHAD-COMP-001")
        self.assertIn("没有数值，未按 0 处理", message)
        self.assertIn("O", message)

        # 2. Policy approves the exclusion but the run has no named confirmer.
        unconfirmed = self.preview_direct(
            composition, sample_id="B-DQ", environment=READY_ENVIRONMENT,
            registry_path=self.write_registry(),
            exclusion_policy_path=self.write_policy(),
            fe_balance_confirmed_by="unit-test-reviewer",
        )
        self.assertNotIn("CALPHAD-COMP-001", self.codes(unconfirmed))
        self.assertIn("CALPHAD-COMP-011", self.codes(unconfirmed))
        self.assertIsNone(unconfirmed.request)

        # 3. Policy + named confirmer -> the run proceeds and records every exclusion.
        declared = self.preview_direct(
            composition,
            sample_id="B-DQ",
            environment=READY_ENVIRONMENT,
            registry_path=self.write_registry(),
            exclusion_policy_path=self.write_policy(),
            fe_balance_confirmed_by="unit-test-reviewer",
            controlled_exclusions_confirmed_by="unit-test-reviewer",
        )
        self.assertEqual(declared.state, "ready", self.codes(declared))
        basis = declared.request["composition_basis"]
        self.assertEqual(basis["unprovided_elements"], ["O", "W"])
        self.assertFalse(basis["missing_values_are_zero"])
        controlled = {item["element"]: item for item in declared.request["controlled_exclusions"]}
        self.assertEqual(sorted(controlled),
                         ["As", "B", "N", "O", "P", "S", "Sb", "Sn", "W"])
        self.assertEqual(controlled["O"]["category"], "input_unknown")
        self.assertEqual(controlled["B"]["category"], "capacity_reduction")
        self.assertEqual(controlled["As"]["category"], "measured_zero")
        self.assertNotIn("As", declared.request["component_mole_fractions"])
        self.assertNotIn("B", declared.request["component_mole_fractions"])
        for element in ("O", "W"):
            self.assertEqual(controlled[element]["category"], "input_unknown")
            self.assertEqual(controlled[element]["value_status"], "missing")
            self.assertIsNone(controlled[element]["value_wt_pct"])
        self.assertTrue(declared.request["reduced_component_system"])

    def test_fe_balance_requires_a_named_user_confirmation(self):
        blocked = self.preview_direct(
            COMPOSITION, environment=READY_ENVIRONMENT, registry_path=self.write_registry(),
            exclusion_policy_path=self.write_policy(),
            fe_balance_confirmed_by="",
        )
        self.assertIn("CALPHAD-COMP-003", self.codes(blocked))
        self.assertIn("Fe = 100 - Σ其他元素", " ".join(gate.message for gate in blocked.gates))
        self.assertIsNone(blocked.request)

        confirmed = self.preview()
        self.assertEqual(confirmed.state, "ready", self.codes(confirmed))
        basis = confirmed.request["composition_basis"]
        self.assertEqual(basis["fe_source"], "balance")
        self.assertEqual(basis["fe_balance_confirmed_by"], "unit-test-reviewer")
        self.assertAlmostEqual(
            basis["fe_balance_wt_pct"],
            100.0 - sum(value for value in COMPOSITION.values() if value is not None),
            places=5,
        )
        self.assertAlmostEqual(basis["effective_wt_pct"]["Fe"], basis["fe_balance_wt_pct"], places=6)

    def test_fe_not_covered_by_the_database_blocks_like_any_other_element(self):
        registry_path = self.write_registry({
            "covered_elements": [element for element in COVERED_ELEMENTS if element != "Fe"],
        })
        preview = self.preview_direct(
            COMPOSITION, environment=READY_ENVIRONMENT, registry_path=registry_path
        )
        self.assertIn("CALPHAD-COMP-002", self.codes(preview))
        message = next(gate.message for gate in preview.gates if gate.code == "CALPHAD-COMP-002")
        self.assertIn("Fe", message)

    def test_declared_fe_without_value_is_not_replaced_by_the_balance(self):
        composition = {**COMPOSITION, "Fe": None}
        preview = self.preview_direct(
            composition, environment=READY_ENVIRONMENT, registry_path=self.write_registry()
        )
        self.assertIn("CALPHAD-COMP-006", self.codes(preview))

    def test_invalid_composition_values_block(self):
        composition = {**COMPOSITION, "Cr": -0.5, "Ni": "abc"}
        preview = self.preview_direct(
            composition, environment=READY_ENVIRONMENT, registry_path=self.write_registry()
        )
        message = next(gate.message for gate in preview.gates if gate.code == "CALPHAD-COMP-004")
        self.assertIn("Cr", message)
        self.assertIn("Ni", message)

    def test_temperature_range_gates(self):
        for kwargs in (
            {"temperature_min_C": 900, "temperature_max_C": 600},
            {"temperature_min_C": 600, "temperature_max_C": 700, "step_C": 0},
            {"temperature_min_C": 100, "temperature_max_C": 700},
            {"temperature_min_C": 600, "temperature_max_C": 700, "step_C": 0.1},
            {"temperature_min_C": 600, "temperature_max_C": 700, "step_C": "abc"},
        ):
            preview = self.preview(**kwargs)
            self.assertIn("CALPHAD-RANGE-001", self.codes(preview), kwargs)
            self.assertIsNone(preview.request)

    def test_range_outside_the_registered_database_range_only_warns(self):
        registry_path = self.write_registry({"declared_temperature_range_C": [700, 800]})
        preview = self.preview_direct(
            COMPOSITION, sample_id="B-DQ", environment=READY_ENVIRONMENT, registry_path=registry_path,
            exclusion_policy_path=self.write_policy(),
            temperature_min_C=600, temperature_max_C=900, step_C=100,
            fe_balance_confirmed_by="unit-test-reviewer",
            controlled_exclusions_confirmed_by="unit-test-reviewer",
        )
        self.assertEqual(preview.state, "ready", self.codes(preview))
        self.assertTrue(any("外推" in warning for warning in preview.warnings))


class UnitAndClaimTests(_AdapterCase):
    def test_request_declares_units_output_basis_and_no_phase_diagram_claim(self):
        preview = self.preview()
        self.assertEqual(preview.state, "ready", self.codes(preview))
        request = preview.request
        self.assertEqual(request["units"]["composition_input"], "wt_pct")
        self.assertEqual(request["units"]["temperature_input"], "degC")
        self.assertEqual(request["units"]["temperature_internal"], "K")
        self.assertEqual(request["units"]["output_phase_fraction"], "mole_fraction_of_phase")
        self.assertEqual(request["pressure_Pa"], 101325)
        self.assertIn("mole_fraction_of_phase", request["output_phase_fraction_basis"])
        self.assertIn("不是质量分数", request["output_phase_fraction_basis_note"])
        self.assertFalse(request["claims"]["is_complete_phase_diagram"])
        self.assertFalse(request["claims"]["writes_back_formal_experimental_data"])
        self.assertFalse(request["composition_basis"]["missing_values_are_zero"])
        self.assertEqual(request["temperature"]["values_C"], [600.0, 650.0, 700.0])
        self.assertEqual(request["temperature"]["values_K"], [873.15, 923.15, 973.15])
        self.assertEqual(preview.to_dict()["state"], "ready")

    def test_request_carries_the_database_source_and_hash(self):
        preview = self.preview()
        entry = json.loads(Path(preview.database["registry_path"]).read_text(encoding="utf-8"))["databases"][0]
        self.assertEqual(preview.request["database"]["database_id"], "TEST-TDB-V1")
        self.assertEqual(preview.request["database"]["sha256"], entry["sha256"])
        self.assertEqual(preview.request["database"]["authorization_status"], entry["authorization_status"])
        self.assertEqual(preview.request["database"]["authorized_by"], "unit-test-reviewer")
        self.assertEqual(preview.request["pycalphad_version"], "0.11.2")
        self.assertEqual(preview.request["request_schema_version"], "1.1")

    def test_component_mole_fractions_are_normalised_over_included_elements(self):
        preview = self.preview()
        fractions = preview.request["component_mole_fractions"]
        self.assertGreater(len(fractions), 5)
        self.assertTrue(all(0.0 <= value < 1.0 for value in fractions.values()))
        self.assertLess(sum(fractions.values()), 1.0)
        self.assertTrue(all(name.isupper() for name in fractions))


class CurveExecutionTests(_AdapterCase):
    def test_blocked_preview_never_invokes_the_worker(self):
        calls = []

        def runner(*args, **kwargs):  # pragma: no cover - must not be called
            calls.append(args)
            raise AssertionError("worker must not run for a blocked preview")

        preview = self.preview_direct(
            COMPOSITION, environment=READY_ENVIRONMENT, registry_path=self.temp / "absent.json"
        )
        record = run_phase_fraction_curve(preview, runner=runner, scratch_root=self.temp / "scratch")
        self.assertEqual(record["status"], "blocked")
        self.assertEqual(calls, [])
        self.assertFalse(record["writes_back_formal_experimental_data"])
        self.assertFalse(record["is_complete_phase_diagram"])

    def test_computed_curve_is_labelled_a_model_prediction_pending_review(self):
        preview = self.preview()
        record = run_phase_fraction_curve(
            preview, runner=self.fake_runner(), scratch_root=self.temp / "scratch"
        )
        self.assertEqual(record["status"], "computed")
        self.assertEqual(record["state"], "needs_human_review")
        self.assertEqual(record["result_type"], "model_prediction_not_experimental_measurement")
        self.assertEqual(record["review_status"], "pending_human_review")
        self.assertFalse(record["is_complete_phase_diagram"])
        self.assertFalse(record["writes_back_formal_experimental_data"])
        self.assertFalse(record["formal_data_write"])
        self.assertEqual(record["adapter_version"], ADAPTER_VERSION)
        self.assertEqual(record["database"]["sha256"], preview.request["database"]["sha256"])
        self.assertEqual(record["pycalphad_version"], "0.11.2")
        self.assertEqual(record["phases"], ["BCC_A2", "FCC_A1"])
        self.assertEqual(len(record["points"]), 3)
        self.assertEqual(len(record["curve"]), 6)
        self.assertEqual(len(record["result_digest"]), 64)
        self.assertFalse((self.temp / "scratch").exists(), "scratch directory must be removed")

        rows = phase_fraction_rows(record)
        self.assertEqual(len(rows), 3)
        self.assertIn("温度 (°C)", rows[0])
        self.assertIn("BCC_A2（相摩尔分数）", rows[0])

        markdown = phase_fraction_curve_markdown(record)
        self.assertIn("不是完整相图", markdown)
        self.assertIn("wt.%", markdown)
        self.assertIn("各相摩尔分数", markdown)
        self.assertIn("待人工复核", markdown)
        self.assertIn("model_prediction_not_experimental_measurement", markdown)
        self.assertIn(preview.request["database"]["sha256"], markdown)
        self.assertIn("TEST-TDB-V1", markdown)

    def test_worker_output_is_validated_before_it_is_accepted(self):
        preview = self.preview()
        mismatched_version = run_phase_fraction_curve(
            preview,
            runner=self.fake_runner({"pycalphad_version": "0.10.4"}),
            scratch_root=self.temp / "scratch_a",
        )
        self.assertEqual(mismatched_version["status"], "failed")
        self.assertEqual(mismatched_version["error"]["code"], "CALPHAD-RUN-002")
        self.assertIn("版本", mismatched_version["error"]["message"])

        def bad_totals(request, *, interpreter, workdir, timeout_seconds):
            payload = self.fake_runner()(request, interpreter=interpreter, workdir=workdir, timeout_seconds=timeout_seconds)
            for point in payload["payload"]["points"]:
                point["phase_fractions_mole"] = {"FCC_A1": 0.5, "BCC_A2": 0.2}
            return payload

        wrong_totals = run_phase_fraction_curve(
            preview, runner=bad_totals, scratch_root=self.temp / "scratch_b"
        )
        self.assertEqual(wrong_totals["status"], "failed")
        self.assertEqual(wrong_totals["error"]["code"], "CALPHAD-RUN-002")

    def test_worker_error_payload_becomes_a_bounded_failure(self):
        preview = self.preview()

        def failing_runner(request, *, interpreter, workdir, timeout_seconds):
            return {
                "returncode": 2,
                "payload": {
                    "worker_schema_version": "1.0",
                    "status": "error",
                    "error_code": "CALPHAD-WORKER-TDB-004",
                    "error_message": "TDB SHA-256 与登记不一致，拒绝计算。",
                },
                "stdout_tail": "",
                "stderr_tail": "CALPHAD-WORKER-TDB-004: hash mismatch",
            }

        record = run_phase_fraction_curve(preview, runner=failing_runner, scratch_root=self.temp / "scratch")
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["error"]["code"], "CALPHAD-RUN-001")
        self.assertEqual(record["error"]["worker_error"]["error_code"], "CALPHAD-WORKER-TDB-004")
        self.assertEqual(record["points"], [])

    def test_composition_set_names_must_be_aggregated_by_the_worker(self):
        preview = self.preview()

        def unaggregated(request, *, interpreter, workdir, timeout_seconds):
            payload = self.fake_runner()(request, interpreter=interpreter, workdir=workdir, timeout_seconds=timeout_seconds)
            payload["payload"]["points"][0]["phase_fractions_mole"] = {"FCC_A1": 0.6, "FCC_A1#2": 0.4}
            return payload

        record = run_phase_fraction_curve(preview, runner=unaggregated, scratch_root=self.temp / "scratch")
        self.assertEqual(record["status"], "failed")
        self.assertIn("未聚合的相成分集", record["error"]["message"])


class SummarizeTests(unittest.TestCase):
    def test_composition_sets_are_summed_per_base_phase(self):
        summary = summarize_phase_amounts(
            ["FCC_A1", "FCC_A1#2", "BCC_A2", "", None, "LIQUID"],
            [0.5, 0.25, 0.25, 0.9, 0.9, 0.0],
        )
        self.assertAlmostEqual(summary["phase_fractions_mole"]["FCC_A1"], 0.75, places=12)
        self.assertAlmostEqual(summary["phase_fractions_mole"]["BCC_A2"], 0.25, places=12)
        self.assertNotIn("LIQUID", summary["phase_fractions_mole"])
        self.assertEqual(summary["phases_present"], ["BCC_A2", "FCC_A1"])
        self.assertAlmostEqual(sum(summary["phase_fractions_mole"].values()), 1.0, places=12)
        self.assertIn("FCC_A1#2", summary["raw_phase_amounts_mole"])

    def test_negative_and_non_numeric_amounts_are_ignored(self):
        summary = summarize_phase_amounts(["A", "B", "C", "D"], [1.0, -1.0, "x", 1.0])
        self.assertEqual(summary["phases_present"], ["A", "D"])
        self.assertAlmostEqual(summary["phase_fractions_mole"]["A"], 0.5, places=12)

    def test_no_positive_amount_yields_no_fractions(self):
        summary = summarize_phase_amounts(["A", "B"], [0.0, 0.0])
        self.assertEqual(summary["phase_fractions_mole"], {})
        self.assertEqual(summary["total_moles"], 0.0)


class ModelRegistryIntegrationTests(_AdapterCase):
    def test_model_registry_still_declares_pycalphad_as_database_required(self):
        entry = next(item for item in MODEL_REGISTRY if item["model"] == "pycalphad")
        self.assertEqual(entry["readiness"], "database_required")
        self.assertEqual(entry["license"], "MIT (database separate)")
        self.assertEqual(entry["repository"], "https://github.com/pycalphad/pycalphad")

    def test_model_statuses_reports_the_isolated_environment_state(self):
        rows = {row["model"]: row for row in model_statuses()}
        self.assertIn("pycalphad", rows)
        self.assertIn(
            rows["pycalphad"]["local_status"],
            {
                "isolated_install_pending",
                "isolated_environment_missing",
                "isolated_environment_probe_failed",
                "isolated_version_mismatch",
                "feature_disabled",
                "isolated_environment_and_database_ready_pending_human_review",
                "blocked_CALPHAD_TDB_007",
                "blocked_CALPHAD_TDB_000",
            },
        )
        self.assertIn("headline", rows["pycalphad"])

    def test_status_row_never_raises_without_environment(self):
        row = status_row()
        self.assertIn(row["state"], {"blocked", "disabled", "ready"})
        self.assertIn("local_status", row)
        self.assertIn("has_authorized_database", row)


class Phase2EnvironmentAndGateTests(_AdapterCase):
    """T86 phase 2: isolated environment, database provenance, gates and export limits."""

    def test_lock_file_pins_the_registered_wheel_hash(self):
        lock = (ROOT / "requirements-calphad-win-py312.lock").read_text(encoding="utf-8")
        entries = [line for line in lock.splitlines() if line.strip() and not line.startswith("#")]
        self.assertGreaterEqual(len(entries), 30)
        for line in entries:
            self.assertRegex(line, r"^[A-Za-z0-9_.\-]+==\S+ --hash=sha256:[0-9a-f]{64}$")
        component = load_adapter_config()["component"]
        wheel_hash = component["artifacts"]["cp312_win_amd64"]["sha256"]
        self.assertIn(f"pycalphad=={component['version']} --hash=sha256:{wheel_hash}", entries)
        for name in ("requirements.txt", "requirements-dev.txt", "requirements-enterprise.txt"):
            self.assertNotIn("pycalphad", (ROOT / name).read_text(encoding="utf-8").lower())

    def test_committed_gate_evidence_records_the_exact_failures(self):
        evidence = json.loads((ROOT / "config" / "calphad_gate_evidence_v1.0.json").read_text(encoding="utf-8"))
        self.assertEqual(evidence["result"], "blocked_gate1_parse_failed")
        self.assertEqual(evidence["environment"]["pycalphad_version"], "0.11.2")
        self.assertEqual(
            evidence["database"]["sha256"],
            "aa02077eac3f602dd7479cbeafb09b450e282716752b3ae2b1fc3a57d9c64865",
        )
        attempts = evidence["gate1_parse"]["attempts"]
        self.assertEqual(attempts[0]["exception_type"], "UnicodeDecodeError")
        self.assertIn("gbk", attempts[0]["message"])
        self.assertEqual(attempts[1]["line"], 180)
        self.assertEqual(attempts[1]["keyword"], "REFERENCE_ELEMENT")
        self.assertIn("Invalid TDB syntax", attempts[1]["message"])
        for item in evidence["keyword_probe"]["results"]:
            self.assertEqual(item["status"], "failed")
        self.assertIn("No keyword was removed", " ".join(evidence["not_done_deliberately"]))

    def test_local_registration_declares_the_gate_verdict(self):
        """The local (git-ignored) registry is optional, so this test tolerates its absence."""
        registry = load_tdb_registry()
        if registry["status"] != "loaded":
            self.skipTest("local (git-ignored) TDB registration is not present in this checkout")
        selected = select_database(registry["databases"])
        self.assertEqual(selected["database_id"], COMMITTED_POLICY_DATABASE_ID)
        self.assertEqual(selected["sha256"], COMMUNITY_CANDIDATE_SHA256)
        validation = validate_tdb_registration(selected)
        self.assertEqual(validation["status"], "passed", validation["problems"])
        compatibility = validation["compatibility"]
        self.assertEqual(compatibility["status"], "passed")
        self.assertTrue(compatibility["pinned_version_match"])
        self.assertEqual(compatibility["unsupported_commands"], [])
        # The vendor original is kept for provenance and must stay non-selectable.
        original = [item for item in registry["databases"]
                    if item["database_id"] == "MATCALC-MC-FE-V2062"]
        self.assertEqual(len(original), 1)
        self.assertEqual(original[0]["pycalphad_compatibility"]["status"], "failed")
        self.assertIn("REFERENCE_ELEMENT",
                      original[0]["pycalphad_compatibility"]["unsupported_commands"])

    def test_feature_status_agrees_with_the_registered_verdict(self):
        """The reported state must follow the actually registered verdict, not a hard-coded one."""
        status = calphad_feature_status()
        registry = load_tdb_registry()
        if registry["status"] != "loaded":
            self.assertEqual(status["state"], "blocked")
            return
        entry = select_database(registry["databases"])
        verdict = (entry.get("pycalphad_compatibility") or {}).get("status")
        codes = [item["code"] for item in status["blocking"]]
        if verdict == "passed":
            self.assertEqual(status["state"], "ready", codes)
            self.assertEqual(codes, [])
            self.assertEqual(status_row()["state"], "ready")
        else:
            self.assertEqual(status["state"], "blocked")
            self.assertIn("CALPHAD-TDB-007", codes)
            self.assertEqual(status_row()["local_status"], "blocked_CALPHAD_TDB_007")

    def test_failed_compatibility_verdict_blocks_even_when_everything_else_is_ready(self):
        registry_path = self.write_registry({
            "pycalphad_compatibility": {**COMPATIBILITY_PASSED, "status": "failed",
                                        "blocked_reason": "unit-test: parser rejects MatCalc keywords"},
        })
        preview = self.preview_direct(
            COMPOSITION, sample_id="B-DQ", environment=READY_ENVIRONMENT,
            registry_path=registry_path, exclusion_policy_path=self.write_policy(),
            fe_balance_confirmed_by="unit-test-reviewer",
            controlled_exclusions_confirmed_by="unit-test-reviewer",
        )
        self.assertEqual(preview.state, "blocked")
        self.assertEqual(self.codes(preview), ["CALPHAD-TDB-007"])
        self.assertIsNone(preview.request)

    def test_compatibility_verdict_recorded_for_a_different_pycalphad_version_is_stale(self):
        registry_path = self.write_registry({
            "pycalphad_compatibility": {**COMPATIBILITY_PASSED, "pinned_pycalphad_version": "0.10.4"},
        })
        entry = json.loads(registry_path.read_text(encoding="utf-8"))["databases"][0]
        validation = validate_tdb_registration(entry)
        self.assertEqual(validation["status"], "failed")
        self.assertIn("不一致", " ".join(validation["problems"]))

    def test_committed_exclusion_policy_is_enumerated_and_versioned(self):
        report = validate_exclusion_policy()
        self.assertEqual(report["status"], "passed", report["problems"])
        self.assertEqual(report["approved_exclusion_count"], 18)
        policy = load_exclusion_policy()
        self.assertFalse(policy["generic_element_ignore_switch"])
        self.assertTrue(policy["requires_named_confirmer"])
        self.assertEqual(policy["database_scope"]["database_id"], COMMITTED_POLICY_DATABASE_ID)
        self.assertEqual(policy["supersedes"], "SteelAI-CALPHAD-Exclusion-Policy-v1.1")
        self.assertIn("缩减成分体系", policy["limitation_notice"]["zh"])
        samples = {entry["sample_id"] for entry in policy["approved_exclusions"]}
        self.assertEqual(samples, {"B-DQ", "R-DQ"})
        for entry in policy["approved_exclusions"]:
            self.assertIn(entry["category"], {"database_not_covered", "measured_zero",
                                              "input_unknown", "capacity_reduction"})
            self.assertNotIn("*", entry["elements"])
        # The committed policy must not leak measured composition values.
        self.assertNotRegex(json.dumps(policy), r"0\.0[0-9]{3,}")

    def test_capacity_reduction_is_bound_to_the_fixed_profile(self):
        """B/N/P/S are measured and covered, so they may only be dropped by the fixed profile."""
        policy = load_exclusion_policy()
        scope = policy["capacity_reduction_scope"]
        self.assertEqual(sorted(scope["elements"]), ["B", "N", "P", "S"])
        self.assertTrue(scope["not_a_free_choice"])
        self.assertEqual(policy["reduced_system_policy"]["component_profile_id"],
                         "steel_matrix_equilibrium_v1")
        for sample in ("B-DQ", "R-DQ"):
            approvals = approved_exclusions_for(policy, sample,
                                                {"database_id": COMMITTED_POLICY_DATABASE_ID})
            for element in ("B", "N", "P", "S"):
                self.assertEqual(approvals[element], "capacity_reduction")
            self.assertNotIn("C", approvals)

    def test_policy_approval_is_bound_to_the_database_identity(self):
        policy = load_exclusion_policy()
        matching = approved_exclusions_for(policy, "R-DQ", {"database_id": COMMITTED_POLICY_DATABASE_ID})
        self.assertEqual(matching.get("As"), "database_not_covered")
        other = approved_exclusions_for(policy, "R-DQ", {"database_id": "SOME-OTHER-TDB"})
        self.assertEqual(other, {})
        unknown_sample = approved_exclusions_for(policy, "X-DQ", {"database_id": COMMITTED_POLICY_DATABASE_ID})
        self.assertEqual(unknown_sample, {})

    def test_a_wildcard_exclusion_policy_fails_closed(self):
        policy_path = self.write_policy(approved_exclusions=[
            {"sample_id": "B-DQ", "elements": ["*"], "category": "database_not_covered", "reason": "nope"},
        ])
        report = validate_exclusion_policy(policy_path)
        self.assertEqual(report["status"], "failed")
        text = " ".join(report["problems"])
        self.assertIn("通配符", text)


class Phase2ExportLimitTests(_AdapterCase):
    """The limitation must be inside every export, not only in the documentation."""

    def _record(self) -> dict:
        preview = self.preview()
        self.assertEqual(preview.state, "ready", self.codes(preview))
        record = run_phase_fraction_curve(
            preview, runner=self.fake_runner(), scratch_root=self.temp / "scratch"
        )
        self.assertEqual(record["status"], "computed")
        return record

    def test_computed_record_carries_the_phase2_flags_and_notice(self):
        record = self._record()
        self.assertTrue(record["reduced_component_system"])
        # The fixture database covers B/N/P/S and does not cover As/Sn/Sb, so the excluded set is
        # As/Sn/Sb (measured zero) + O/W (no value) + B/N/P/S (capacity reduction).
        self.assertEqual(sorted(record["excluded_elements"]),
                         ["As", "B", "N", "O", "P", "S", "Sb", "Sn", "W"])
        self.assertEqual(record["controlled_exclusions_confirmed_by"], "unit-test-reviewer")
        self.assertEqual(record["database_compatibility"]["status"], "passed")
        notice = record["limitation_notice"]
        self.assertIn("缩减成分体系", notice["zh"])
        self.assertIn("B、N、P、S", notice["zh"])
        self.assertIn("As、Sn、Sb", notice["zh"])
        self.assertIn("O、W", notice["zh"])
        self.assertIn("偏聚", notice["zh"])
        self.assertIn("12-component reduced-system", notice["en"])
        self.assertIn("B, N, P and S", notice["en"])

    def test_markdown_export_embeds_the_limitation_and_the_exclusion_table(self):
        text = phase_fraction_curve_markdown(self._record())
        self.assertIn("限制声明（必须随结果一同引用）", text)
        self.assertIn("缩减成分体系", text)
        self.assertIn("受控元素排除", text)
        self.assertIn("`input_unknown`", text)
        self.assertIn("`measured_zero`", text)
        self.assertIn("`capacity_reduction`", text)
        self.assertIn("不能用于判断这些元素对偏聚、夹杂、晶界脆化、相稳定性或性能的影响", text)

    def test_csv_export_embeds_the_limitation_in_preamble_and_every_row(self):
        text = phase_fraction_csv(self._record())
        lines = text.splitlines()
        self.assertTrue(lines[0].startswith("#"))
        self.assertIn("# limitation_notice_zh:", text)
        self.assertIn("# reduced_component_system: true", text)
        data_rows = [line for line in lines if line and not line.startswith("#")]
        self.assertGreaterEqual(len(data_rows), 2)
        header, *rows = data_rows
        self.assertIn("limitation_notice_zh", header)
        self.assertIn("excluded_elements", header)
        self.assertIn("excluded_elements_and_reasons", header)
        self.assertIn("component_profile", header)
        self.assertIn("phase_profile", header)
        self.assertIn("review_status", header)
        for row in rows:
            self.assertIn("不能用于判断这些元素对偏聚", row)
            self.assertIn("As;", row)
            self.assertIn("steel_matrix_equilibrium_v1", row)
            self.assertIn("steel_matrix_major_carbides_v1", row)

    def test_blocked_record_still_carries_the_notice(self):
        blocked = self.preview_direct(
            COMPOSITION, sample_id="B-DQ", environment=READY_ENVIRONMENT,
            registry_path=self.temp / "absent.json",
        )
        record = run_phase_fraction_curve(blocked, runner=self.fake_runner(), scratch_root=self.temp / "s")
        self.assertEqual(record["status"], "blocked")
        self.assertIn("limitation_notice", record)
        self.assertFalse(record["writes_back_formal_experimental_data"])


class WorkerScriptContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = SCRATCH_ROOT / f"worker-{uuid.uuid4().hex}"
        self.temp.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, self.temp, ignore_errors=True)

    def test_worker_script_exists_and_keeps_pycalphad_import_out_of_the_top_level(self):
        path = ROOT / "scripts" / "calphad_phase_fraction_worker.py"
        text = path.read_text(encoding="utf-8")
        self.assertIn("summarize_phase_amounts", text)
        # The import must be lazy inside the helpers so a missing pycalphad is a bounded error.
        self.assertNotIn("\nfrom pycalphad", text)
        self.assertIn("from pycalphad import equilibrium, variables as v", text)
        self.assertIn("from pycalphad import Database", text)
        self.assertIn("CALPHAD-WORKER-TDB-004", text)

    def test_worker_loads_the_database_from_its_own_bytes(self):
        """A locale-dependent load would break the registered utf-8 candidate on a GBK host."""
        text = (ROOT / "scripts" / "calphad_phase_fraction_worker.py").read_text(encoding="utf-8")
        self.assertIn("def _load_database(", text)
        self.assertIn("from_string", text)
        self.assertNotIn("Database(str(database_path))", text)
        self.assertIn("CALPHAD-WORKER-MEMORY-001", text)

    def test_worker_rejects_a_request_without_declared_units(self):
        request = self.temp / "request.json"
        result = self.temp / "result.json"
        request.write_text(json.dumps({"request_schema_version": "1.1"}), encoding="utf-8")
        completed = subprocess.run(
            [sys.executable, "-B", str(ROOT / "scripts" / "calphad_phase_fraction_worker.py"), str(request), str(result)],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
            cwd=str(ROOT),
        )
        self.assertEqual(completed.returncode, 2)
        payload = json.loads(result.read_text(encoding="utf-8"))
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["error_code"], "CALPHAD-WORKER-UNIT-001")


class Phase3CommunityCandidateTests(_AdapterCase):
    """T86 phase 3: community derivative candidate registration, diff audit and evidence."""

    def _evidence(self) -> dict:
        return json.loads((ROOT / "config" / "calphad_gate_evidence_v1.1.json").read_text(encoding="utf-8"))

    def _registry(self) -> dict:
        return load_adapter_config()

    def test_committed_registry_selects_the_community_candidate(self):
        registry = self._registry()
        database = registry["database"]
        self.assertEqual(database["selected_database_id"], COMMITTED_POLICY_DATABASE_ID)
        self.assertEqual(database["selected_database_sha256"], COMMUNITY_CANDIDATE_SHA256)
        self.assertEqual(database["pycalphad_compatibility_gate"], "passed")
        self.assertEqual(database["pycalphad_compatibility_evidence"],
                         "config/calphad_gate_evidence_v1.1.json")
        # The scope of "passed" must be explicit: it is not a claim about the sample compositions.
        self.assertIn("does NOT mean", database["pycalphad_compatibility_gate_scope"])
        self.assertFalse(database["upstream_original"]["selectable"])
        self.assertIn("third-party community derivative",
                      database["selected_database_naming_rule"].lower())

    def test_committed_registry_records_the_solver_capability_limit(self):
        limit = self._registry()["solver_capability_limit"]
        self.assertEqual(limit["component_list_length_upper_bound_measured"], 13)
        self.assertEqual(limit["first_failing_component_list_length_measured"], 14)
        self.assertEqual(len(limit["measured_on_databases"]), 2)
        self.assertIn("identical", limit["control_database_component_limit"])
        # No silent downgrade may be permitted.
        self.assertIn("versioned update", limit["not_permitted_to_work_around_silently"])
        self.assertIn("CALPHAD-WORKER-MEMORY-001", limit["worker_error_codes"])

    def test_policy_v1_2_is_recorded_in_the_registry_and_on_disk(self):
        registry = self._registry()["controlled_element_exclusion"]
        self.assertEqual(registry["policy_file"], "config/calphad_exclusion_policy_v1.2.json")
        self.assertEqual(registry["policy_supersedes"], "config/calphad_exclusion_policy_v1.1.json")
        self.assertTrue((ROOT / registry["policy_file"]).is_file())
        self.assertTrue((ROOT / registry["policy_supersedes"]).is_file())
        self.assertFalse(registry["generic_element_ignore_switch"])

    def test_phase3_evidence_records_the_diff_audit(self):
        evidence = self._evidence()
        self.assertEqual(evidence["result"],
                         "community_candidate_gates_passed_blocked_by_solver_component_capacity")
        candidate = evidence["community_derivative_candidate"]
        self.assertEqual(candidate["sha256"], COMMUNITY_CANDIDATE_SHA256)
        self.assertEqual(candidate["source_commit"], "19b11640253543fe412145498438cb8355a32561")
        self.assertIn("ODbL", candidate["licence"])
        self.assertIn("no LICENSE file", candidate["licence"])
        self.assertIn("not edited", candidate["unmodified"])
        self.assertIn("no derived TDB", candidate["unmodified"])
        audit = evidence["diff_audit"]
        self.assertEqual(audit["verdict"], "passed_syntax_repairs_only")
        self.assertEqual(audit["unexplained_deviations"], 0)
        self.assertTrue(audit["no_gibbs_energy_or_breakpoint_change_found"])
        self.assertEqual(sorted(audit["deviation_classes"]),
                         sorted(["reference_key_normalisation", "invalid_delimiter_repair",
                                 "invalid_numeric_literal_repair", "duplicate_fragment_repair_verified",
                                 "duplicate_or_stray_fragment_removal", "missing_terminator_split",
                                 "structural_change_numbers_preserved", "matcalc_only_command_removed",
                                 "matcalc_only_parameter_removed"]))
        self.assertEqual(sum(audit["deviation_classes"].values()), 40)

    def test_phase3_evidence_records_the_reproduced_validations(self):
        evidence = self._evidence()
        community = evidence["independent_validation"]["community_binary_claims"]
        self.assertEqual(community["systems"], 5)
        self.assertEqual(community["checks_total"], 15)
        self.assertEqual(community["checks_passed"], 15)
        self.assertEqual(community["checks_failed"], 0)
        project = evidence["independent_validation"]["project_relevant_checks"]
        self.assertEqual(project["systems"], 9)
        self.assertEqual(project["checks_total"], 18)
        self.assertEqual(project["checks_passed"], 18)
        self.assertEqual(project["checks_failed"], 0)
        self.assertIn("NOT experimental validation", project["what_this_proves"])
        probe = evidence["independent_validation"]["model_loss_probe"]
        self.assertFalse(probe["mc_mx_composition_set_reachable"])
        self.assertTrue(probe["agrees_with_expectation"])

    def test_phase3_evidence_records_the_capacity_finding_and_the_control(self):
        evidence = self._evidence()
        limit = evidence["solver_capacity_limit"]
        self.assertEqual(limit["component_list_length_upper_bound_measured"], 13)
        self.assertEqual(limit["first_failing_component_list_length_measured"], 14)
        control = limit["control_experiment"]
        self.assertIn("COST507", control["database"])
        self.assertEqual(control["component_list_length_upper_bound_measured"], 13)
        self.assertEqual(control["first_failing_component_list_length_measured"], 14)
        for flag in ("phase_list_independent", "point_density_independent",
                     "component_identity_independent"):
            self.assertTrue(limit[flag], flag)
        outcomes = {(item["probe"], item["component_list_length"]): item["outcome"]
                    for item in limit["sweep_results"]}
        self.assertEqual(outcomes[("community_mc_fe", 13)], "solved")
        self.assertEqual(outcomes[("community_mc_fe", 14)], "process_aborted")
        self.assertEqual(outcomes[("control_cost507", 13)], "solved")
        self.assertEqual(outcomes[("control_cost507", 14)], "process_aborted")
        self.assertIn("CALPHAD-RUN-001", limit["product_behaviour"])
        self.assertIn("Blocked", evidence["status"]["t86"])
        self.assertEqual(evidence["status"]["database_candidate"], "compatibility_candidate")
        for never in ("validated", "production_ready", "pilot_ready_pending_scientific_review"):
            self.assertIn(never, evidence["status"]["not_claimed"])

    def test_phase3_evidence_records_the_model_losses_as_unknown_impact(self):
        evidence = self._evidence()
        structure = evidence["gate2_model_structure"]
        self.assertEqual(structure["order_disorder_links_found"], 0)
        self.assertFalse(structure["bcc_b2_order_disorder_coupled"])
        self.assertEqual(structure["composition_set_phases_found"], [])
        self.assertFalse(structure["mc_mx_carbo_nitride_reachable"])
        self.assertEqual(structure["impact_classification"], "unknown_model_impact")
        self.assertIn("'no effect' is explicitly NOT claimed", structure["impact_rationale"])
        commands = structure["matcalc_only_commands_commented_out"]
        self.assertEqual(commands["PARAMETER HMVA"], 21)

    def test_phase3_documentation_exists_and_keeps_the_naming_rule(self):
        text = (ROOT / "docs" / "T86_PHASE3_COMMUNITY_COMPATIBILITY.md").read_text(encoding="utf-8")
        self.assertIn("第三方社区派生数据库候选", text)
        self.assertIn("不得**称为 TU Wien 官方 pycalphad 兼容版", text)
        self.assertIn("15/15", text)
        self.assertIn("18/18", text)
        self.assertIn("0xC0000005", text)
        self.assertIn("COST507", text)
        self.assertIn("T86 保持 `Blocked`", text)
        self.assertIn("不构成任何钢种的实验验收", text)
        # The document must not embed a sample composition table row.
        self.assertNotRegex(text, r"(?m)^\|\s*[BR]-DQ\s*\|")

    def test_validation_script_isolates_and_bounds_every_equilibration(self):
        text = (ROOT / "scripts" / "calphad_candidate_validation.py").read_text(encoding="utf-8")
        self.assertIn("taskkill", text)
        self.assertIn("timed_out", text)
        self.assertIn("CREATE_NEW_PROCESS_GROUP", text)
        self.assertIn("load_control_database", text)
        # The candidate under review must never take the control-database fallback loader.
        self.assertIn("load_control_database(db_path) if probe[\"db\"] == \"cost507\" else load_database(db_path)", text)

    def test_diff_audit_and_gate_scripts_exist(self):
        for name in ("calphad_tdb_diff_audit.py", "calphad_compatibility_gate.py",
                     "calphad_candidate_validation.py", "calphad_malformed_statement_probe.py"):
            self.assertTrue((ROOT / "scripts" / name).is_file(), name)


class NativeAbortReportingTests(_AdapterCase):
    """A native pycalphad abort must surface as an explicit, actionable failure."""

    def _preview(self):
        preview = self.preview()
        self.assertEqual(preview.state, "ready", self.codes(preview))
        return preview

    @staticmethod
    def _native_runner(returncode: int):
        def runner(request, *, interpreter, workdir, timeout_seconds):
            return {"returncode": returncode, "payload": None, "stdout_tail": "", "stderr_tail": ""}

        return runner

    def test_access_violation_is_explained_not_reported_as_a_missing_file(self):
        record = run_phase_fraction_curve(
            self._preview(), runner=self._native_runner(0xC0000005 - (1 << 32)),
            scratch_root=self.temp / "scratch",
        )
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["state"], "blocked")
        self.assertEqual(record["error"]["code"], "CALPHAD-RUN-001")
        self.assertTrue(record["error"]["native_abort"])
        self.assertIn("ACCESS_VIOLATION", record["error"]["message"])
        self.assertIn("0xC0000005", record["error"]["message"])
        self.assertIn("人工批准", record["error"]["message"])
        self.assertEqual(record["error"]["worker_returncode"], 0xC0000005 - (1 << 32))

    def test_unsigned_windows_status_is_recognised(self):
        record = run_phase_fraction_curve(
            self._preview(), runner=self._native_runner(0xC0000005),
            scratch_root=self.temp / "scratch",
        )
        self.assertTrue(record["error"]["native_abort"])
        self.assertIn("0xC0000005", record["error"]["message"])

    def test_ordinary_nonzero_exit_is_not_labelled_a_native_abort(self):
        record = run_phase_fraction_curve(
            self._preview(), runner=self._native_runner(2),
            scratch_root=self.temp / "scratch",
        )
        self.assertFalse(record["error"]["native_abort"])
        self.assertIn("returncode=2", record["error"]["message"])

    def test_blocked_result_never_carries_a_curve(self):
        record = run_phase_fraction_curve(
            self._preview(), runner=self._native_runner(0xC0000005 - (1 << 32)),
            scratch_root=self.temp / "scratch",
        )
        self.assertEqual(record["points"], [])
        self.assertEqual(record["curve"], [])
        self.assertFalse(record["writes_back_formal_experimental_data"])
        self.assertFalse(record["is_complete_phase_diagram"])

    def test_worker_memory_message_states_the_measured_limit(self):
        import importlib.util

        path = ROOT / "scripts" / "calphad_phase_fraction_worker.py"
        spec = importlib.util.spec_from_file_location("_t86_worker_under_test", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        message = module._memory_message(
            MemoryError("Unable to allocate 10.9 GiB"), {"components": ["FE", "C", "VA"]}
        )
        self.assertIn("超出可用内存", message)
        self.assertIn("≤13", message)
        self.assertIn("COST507", message)
        self.assertIn("具名负责人批准", message)
        self.assertIn("不会自行降级成分体系", message)


class Phase4ReducedSystemTests(_AdapterCase):
    """T86 phase 4: fixed component profile, fixed phase range, named approval and naming."""

    def test_committed_reduced_system_policy_is_valid_and_fixed(self):
        report = validate_reduced_system_policy()
        self.assertEqual(report["status"], "passed", report["problems"])
        policy = load_reduced_system_policy()
        self.assertEqual(policy["policy_id"], "SteelAI-CALPHAD-Reduced-System-Policy-v1.0")
        component = policy["component_profile"]
        self.assertEqual(component["profile_id"], "steel_matrix_equilibrium_v1")
        self.assertEqual(sorted(component["included_elements"]),
                         sorted(REQUIRED_MATRIX_ELEMENTS))
        self.assertEqual(component["included_element_count"], 12)
        self.assertFalse(component["generic_element_selection_switch"])
        self.assertTrue(component["zero_fill_forbidden"])
        phase = policy["phase_profile"]
        self.assertEqual(phase["profile_id"], "steel_matrix_major_carbides_v1")
        self.assertEqual(tuple(phase["phases"]), REQUIRED_MATRIX_PHASES)
        self.assertFalse(phase["generic_phase_selection_switch"])
        self.assertEqual(policy["acknowledgement_text"], MATRIX_ACKNOWLEDGEMENT_TEXT)
        self.assertEqual(policy["result_naming"]["label"], RESULT_LABEL_MATRIX)
        for prohibited in PROHIBITED_RESULT_LABELS:
            self.assertIn(prohibited, policy["result_naming"]["prohibited_labels"])
        # The committed policy must not leak measured composition values.
        self.assertNotRegex(json.dumps(policy), r"0\.0[0-9]{3,}")

    def test_a_tampered_component_profile_fails_closed(self):
        def drop_manganese(policy):
            policy["component_profile"]["included_elements"] = [
                element for element in policy["component_profile"]["included_elements"]
                if element != "Mn"
            ]

        def widen_with_boron(policy):
            policy["component_profile"]["included_elements"].append("B")

        for mutate in (drop_manganese, widen_with_boron):
            report = validate_reduced_system_policy(self.write_reduced_policy(mutate))
            self.assertEqual(report["status"], "failed")
            self.assertIn("12 组元", " ".join(report["problems"]))

    def test_a_tampered_phase_profile_fails_closed(self):
        def drop_m6c(policy):
            policy["phase_profile"]["phases"] = [
                name for name in policy["phase_profile"]["phases"] if name != "M6C"
            ]

        def add_boride(policy):
            policy["phase_profile"]["phases"].append("M2B")

        for mutate in (drop_m6c, add_boride):
            report = validate_reduced_system_policy(self.write_reduced_policy(mutate))
            self.assertEqual(report["status"], "failed")
            self.assertIn("phase_profile.phases", " ".join(report["problems"]))

    def test_a_generic_selection_switch_fails_closed(self):
        report = validate_reduced_system_policy(self.write_reduced_policy(
            lambda policy: policy["component_profile"].update(
                {"generic_element_selection_switch": True})
        ))
        self.assertEqual(report["status"], "failed")
        self.assertIn("通用元素选择开关", " ".join(report["problems"]))

    def test_request_carries_the_profiles_phases_and_approval(self):
        preview = self.preview()
        self.assertEqual(preview.state, "ready", self.codes(preview))
        request = preview.request
        self.assertEqual(request["phases"], list(REQUIRED_MATRIX_PHASES))
        self.assertEqual(request["component_profile"]["profile_id"], "steel_matrix_equilibrium_v1")
        self.assertEqual(request["phase_profile"]["profile_id"], "steel_matrix_major_carbides_v1")
        self.assertTrue(request["component_profile"]["matches_profile"])
        self.assertEqual(request["component_profile"]["included_element_count"], 12)
        self.assertEqual(request["result_label"], RESULT_LABEL_MATRIX)
        approval = request["reduced_system_approval"]
        self.assertEqual(approval["reviewer_id"], "unit-test-reviewer")
        self.assertEqual(approval["approved_at"], "2026-09-25")
        self.assertTrue(approval["acknowledged"])
        self.assertTrue(approval["no_default_reviewer_in_code"])
        self.assertEqual(approval["database_sha256"], request["database"]["sha256"])
        self.assertEqual(sorted(approval["excluded_elements"]),
                         ["As", "B", "N", "O", "P", "S", "Sb", "Sn", "W"])
        self.assertIn("pycalphad", request["component_versions_and_hashes"])
        self.assertIn("database_sha256", request["component_versions_and_hashes"])

    def test_a_component_set_that_differs_from_the_profile_blocks(self):
        composition = {key: value for key, value in COMPOSITION.items() if key != "Cu"}
        preview = self.preview_direct(composition, sample_id="B-DQ",
                                      environment=READY_ENVIRONMENT,
                                      registry_path=self.write_registry(),
                                      exclusion_policy_path=self.write_policy(),
                                      fe_balance_confirmed_by="unit-test-reviewer",
                                      controlled_exclusions_confirmed_by="unit-test-reviewer")
        self.assertEqual(preview.state, "blocked")
        self.assertIn("CALPHAD-COMP-012", self.codes(preview))
        message = next(gate.message for gate in preview.gates if gate.code == "CALPHAD-COMP-012")
        self.assertIn("Cu", message)
        self.assertIn("没有通用选择开关", message)
        self.assertIsNone(preview.request)

    def test_a_profile_phase_missing_from_the_registration_blocks(self):
        registry_path = self.write_registry({
            "covered_phases": [name for name in COVERED_PHASES if name != "M6C"],
        })
        preview = self.preview_direct(COMPOSITION, sample_id="B-DQ",
                                      environment=READY_ENVIRONMENT, registry_path=registry_path,
                                      exclusion_policy_path=self.write_policy(),
                                      fe_balance_confirmed_by="unit-test-reviewer",
                                      controlled_exclusions_confirmed_by="unit-test-reviewer")
        self.assertEqual(preview.state, "blocked")
        self.assertIn("CALPHAD-PHASE-001", self.codes(preview))
        message = next(gate.message for gate in preview.gates if gate.code == "CALPHAD-PHASE-001")
        self.assertIn("M6C", message)
        self.assertIn("不得自动替换相名", message)

    def test_every_named_approval_field_is_required(self):
        cases = {
            "reviewer_id": {"reduced_system_reviewer_id": ""},
            "批准时间": {"reduced_system_approved_at": ""},
            "批准时间格式": {"reduced_system_approved_at": "25/09/2026"},
            "批准理由": {"reduced_system_approval_reason": ""},
            "确认文本": {"reduced_system_acknowledged": False},
        }
        for label, override in cases.items():
            with self.subTest(field=label):
                preview = self.preview(**override)
                self.assertEqual(preview.state, "blocked")
                self.assertIn("CALPHAD-COMP-011", self.codes(preview))
                self.assertIsNone(preview.request)

    def test_the_named_approval_is_never_defaulted_in_the_adapter(self):
        source = (ROOT / "steelai" / "calphad_adapter.py").read_text(encoding="utf-8")
        self.assertIn("reduced_system_reviewer_id: str = \"\"", source)
        self.assertNotIn("reduced_system_reviewer_id: str = \"SteelAI", source)

    def test_capacity_reduction_removes_the_element_from_the_request(self):
        preview = self.preview()
        self.assertEqual(preview.state, "ready", self.codes(preview))
        # The registered test database covers B/N/P/S; the profile still removes them.
        for element in ("B", "N", "P", "S"):
            self.assertNotIn(element, preview.request["components"])
            self.assertNotIn(element, preview.request["component_mole_fractions"])
        self.assertEqual(len(preview.request["components"]), 12)
        categories = {item["element"]: item["category"]
                      for item in preview.request["controlled_exclusions"]}
        self.assertEqual(categories["B"], "capacity_reduction")
        self.assertEqual(categories["S"], "capacity_reduction")
        self.assertEqual(
            sorted(preview.composition["capacity_reduction_elements"]), ["B", "N", "P", "S"])

    def test_capacity_reduction_requires_the_fixed_policy(self):
        policy_path = self.write_policy(approved_exclusions=[
            {"sample_id": "B-DQ", "elements": ["B", "N", "P", "S"],
             "category": "capacity_reduction", "reason": "unit-test capacity reduction"},
            {"sample_id": "B-DQ", "elements": ["O", "W"], "category": "input_unknown",
             "reason": "no measured value"},
            {"sample_id": "B-DQ", "elements": ["As", "Sn", "Sb"], "category": "measured_zero",
             "reason": "measured as zero"},
        ])
        preview = preview_phase_fraction_curve(
            COMPOSITION, sample_id="B-DQ", environment=READY_ENVIRONMENT,
            registry_path=self.write_registry(), exclusion_policy_path=policy_path,
            reduced_system_policy_path=self.temp / "absent.json",
            fe_balance_confirmed_by="unit-test-reviewer",
            controlled_exclusions_confirmed_by="unit-test-reviewer",
            **REDUCED_APPROVAL,
        )
        self.assertEqual(preview.state, "blocked")
        codes = self.codes(preview)
        self.assertIn("CALPHAD-POLICY-002", codes)
        self.assertIn("CALPHAD-COMP-013", codes)

    def test_committed_phase_profile_evidence_records_every_phase(self):
        evidence = json.loads(
            (ROOT / "config" / "calphad_phase_profile_evidence_v1.0.json").read_text(encoding="utf-8"))
        self.assertEqual(evidence["result"], "all_candidate_phases_verified")
        self.assertEqual(tuple(evidence["phase_profile"]["verified_phases"]), REQUIRED_MATRIX_PHASES)
        self.assertEqual(evidence["phase_profile"]["removed_phases"], [])
        for item in evidence["verification_criteria_results"]:
            self.assertTrue(item["in_database"], item["phase"])
            self.assertGreater(item["parameter_count"], 0, item["phase"])
            self.assertTrue(item["workspace_constructed"], item["phase"])
            self.assertTrue(item["single_phase_solved"], item["phase"])
            self.assertGreater(item["reachability_occurrences"], 0, item["phase"])
            self.assertEqual(item["verdict"], "verified")
        self.assertEqual(
            evidence["reduced_system_checks"]["step5_repeat_run_identical"], "ok")

    def test_committed_phase4_evidence_records_the_block(self):
        evidence = json.loads(
            (ROOT / "config" / "calphad_phase4_evidence_v1.0.json").read_text(encoding="utf-8"))
        self.assertEqual(evidence["result"], "blocked")
        self.assertEqual(evidence["status"]["t86"], "Blocked")
        for never in ("validated", "production_ready", "pilot_ready_pending_scientific_review"):
            self.assertIn(never, evidence["status"]["not_claimed"])
        steps = evidence["ten_step_validation"]["step_statuses"]
        self.assertEqual(steps["step6_b_dq_reduced_system"], "failed")
        self.assertEqual(steps["step7_r_dq_reduced_system"], "ok")
        self.assertEqual(steps["step9_excluded_elements_absent_from_worker"], "ok")
        self.assertEqual(steps["step0_no_named_approval_blocks"], "ok")
        step7 = evidence["ten_step_validation"]["step7_r_dq"]
        self.assertEqual(step7["status"], "ok")
        self.assertTrue(step7["repeat_identical"])
        self.assertLessEqual(step7["repeat_max_abs_difference"], step7["repeat_tolerance"])
        self.assertTrue(step7["plausibility"]["vacancy_included"])
        self.assertIn("LIQUID", step7["phase_union"])
        self.assertIn("BCC_A2", step7["phase_union"])
        defect = evidence["critical_defect_found_and_fixed"]
        self.assertIn("VA", defect["fix"])
        self.assertIn("sum", defect["summary"]) 

    def test_phase4_documentation_exists_and_states_the_block(self):
        text = (ROOT / "docs" / "T86_PHASE4_REDUCED_SYSTEM.md").read_text(encoding="utf-8")
        self.assertIn("steel_matrix_equilibrium_v1", text)
        self.assertIn("steel_matrix_major_carbides_v1", text)
        self.assertIn("12-component reduced-system matrix equilibrium prediction", text)
        self.assertIn("T86 保持 `Blocked`", text)
        self.assertIn("875 °C", text)
        self.assertIn("`VA`", text)
        self.assertNotRegex(text, r"(?m)^\|\s*[BR]-DQ\s*\|")

    def test_reduced_system_scripts_exist(self):
        for name in ("calphad_phase_profile_probe.py", "calphad_phase4_validation.py"):
            self.assertTrue((ROOT / "scripts" / name).is_file(), name)
        worker = (ROOT / "scripts" / "calphad_phase_fraction_worker.py").read_text(encoding="utf-8")
        self.assertIn("VA", worker)
        self.assertIn("pycalphad_components", worker)
        self.assertIn("CALPHAD-WORKER-PHASE-001", worker)
        self.assertIn("CALPHAD-WORKER-PHASE-002", worker)
        self.assertIn("CALPHAD-WORKER-APPROVAL-001", worker)
        self.assertIn("MAX_POINT_RETRIES", worker)


class Phase5IndependentPointTests(_AdapterCase):
    """T86 phase 5: one fresh process per temperature point, with the full point contract.

    These tests never start a heavy solver: they use the single-point worker double.
    """

    def _record(self, runner=None, **overrides):
        preview = self.preview(**overrides)
        self.assertEqual(preview.state, "ready", self.codes(preview))
        return preview, run_phase_fraction_curve(
            preview, runner=runner or self.fake_runner(), scratch_root=self.temp / "scratch"
        )

    @staticmethod
    def _observing_runner(behaviour=None, calls=None):
        """Records every request; ``behaviour(request, index)`` may return payload overrides."""
        log = calls if calls is not None else []

        def runner(request, *, interpreter, workdir, timeout_seconds):
            index = len(log)
            log.append(request)
            if behaviour is not None:
                result = behaviour(request, index)
                if result is not None:
                    return result
            temperatures = [float(value) for value in request["temperature"]["values_C"]]
            points = [{
                "temperature_C": temperature,
                "temperature_K": round(temperature + 273.15, 6),
                "total_moles": 1.0,
                "phase_fractions_mole": {"FCC_A1": 1.0},
                "raw_phase_amounts_mole": {"FCC_A1": 1.0},
                "phases_present": ["FCC_A1"],
            } for temperature in temperatures]
            return {"returncode": 0, "pid": 1000 + index, "payload": {
                "worker_schema_version": "1.1", "status": "ok",
                "pycalphad_version": request["pycalphad_version"],
                "python_version": "3.12.14",
                "phases": list(request.get("phases", [])),
                "components": list(request.get("components", [])),
                "pycalphad_components": list(request.get("components", [])) + ["VA"],
                "component_profile_id": (request.get("component_profile") or {}).get("profile_id"),
                "phase_profile_id": (request.get("phase_profile") or {}).get("profile_id"),
                "solver_mode": request.get("solver_mode"),
                "points": points, "warnings": [], "elapsed_s": 0.1,
            }, "stdout_tail": "", "stderr_tail": ""}

        return runner, log

    def test_default_mode_is_the_formal_independent_mode(self):
        preview, record = self._record()
        self.assertEqual(preview.request["request_schema_version"], "1.1")
        self.assertEqual(record["status"], "computed")
        self.assertEqual(record["solver_mode"], INDEPENDENT_SOLVER_MODE)
        self.assertTrue(record["formal_solver_mode"])
        self.assertTrue(record["single_point_process"])
        self.assertTrue(record["no_warm_start"])

    def test_one_fresh_process_per_point_with_one_temperature_each(self):
        runner, calls = self._observing_runner()
        _, record = self._record(runner=runner)
        expected_temperatures = record["temperature"]["values_C"]
        self.assertEqual(len(calls), len(expected_temperatures))
        hashes = set()
        for index, request in enumerate(calls):
            self.assertEqual(len(request["temperature"]["values_C"]), 1)
            self.assertEqual(request["temperature"]["values_C"][0], expected_temperatures[index])
            self.assertEqual(request["solver_mode"], INDEPENDENT_SOLVER_MODE)
            self.assertTrue(request["single_point_process"])
            self.assertTrue(request["no_warm_start"])
            self.assertEqual(request["point_index"], index + 1)
            self.assertEqual(request["point_count"], len(expected_temperatures))
            hashes.add(request["request_digest"])
        self.assertEqual(len(hashes), len(calls), "每个温度点必须有独立的请求哈希")

    def test_every_point_uses_identical_inputs_except_temperature(self):
        runner, calls = self._observing_runner()
        self._record(runner=runner)
        first = calls[0]
        for request in calls[1:]:
            for key in ("components", "component_mole_fractions", "phases", "pressure_Pa",
                        "database", "component_profile", "phase_profile", "units",
                        "pycalphad_version", "solver_mode"):
                self.assertEqual(request[key], first[key], f"{key} 必须逐点相同")
            self.assertEqual(request["temperature"]["min_C"], first["temperature"]["min_C"])
            self.assertEqual(request["temperature"]["step_C"], first["temperature"]["step_C"])
            self.assertNotEqual(request["temperature"]["values_C"],
                                first["temperature"]["values_C"])

    def test_points_run_serially_not_in_parallel(self):
        state = {"active": 0, "max_active": 0}
        runner, _ = self._observing_runner()

        def serial_runner(request, *, interpreter, workdir, timeout_seconds):
            state["active"] += 1
            state["max_active"] = max(state["max_active"], state["active"])
            try:
                return runner(request, interpreter=interpreter, workdir=workdir,
                              timeout_seconds=timeout_seconds)
            finally:
                state["active"] -= 1

        _, record = self._record(runner=serial_runner)
        self.assertEqual(record["status"], "computed")
        self.assertEqual(state["max_active"], 1, "温度点必须串行执行")

    def test_a_failed_point_produces_no_partial_curve(self):
        temperatures = ["600", "650", "700"]

        def behaviour(request, index):
            if index == 1:
                return {"returncode": 2, "pid": 4242, "payload": {
                    "worker_schema_version": "1.1", "status": "error",
                    "error_code": "CALPHAD-WORKER-SOLVE-001",
                    "error_message": "平衡求解可能未收敛。",
                }, "stdout_tail": "", "stderr_tail": "solve failed"}
            return None

        runner, _ = self._observing_runner(behaviour=behaviour)
        preview = self.preview()
        record = run_phase_fraction_curve(preview, runner=runner,
                                          scratch_root=self.temp / "scratch")
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["state"], "blocked")
        self.assertEqual(record["points"], [])
        self.assertEqual(record["curve"], [])
        self.assertFalse(record["partial_curve_returned"])
        self.assertEqual(record["point_count_expected"], len(temperatures))
        self.assertEqual(record["point_count_first_attempt_success"], 2)
        self.assertEqual(len(record["failed_points"]), 1)
        self.assertEqual(record["failed_points"][0]["temperature_C"], 650.0)
        self.assertEqual(len(record["point_manifest"]), 3)
        self.assertEqual(record["error"]["code"], "CALPHAD-RUN-001")

    def test_a_diagnostic_retry_never_changes_the_formal_result(self):
        state = {"calls": 0}

        def behaviour(request, index):
            # The 650 degC point fails on its first attempt and succeeds on the diagnostic retry.
            if str(request["temperature"]["values_C"][0]) == "650.0":
                state["calls"] += 1
                if state["calls"] == 1:
                    return {"returncode": 0xC0000005 - (1 << 32), "pid": 7, "payload": None,
                            "stdout_tail": "", "stderr_tail": "ACCESS_VIOLATION"}
            return None

        runner, calls = self._observing_runner(behaviour=behaviour)
        preview = self.preview()
        record = run_phase_fraction_curve(preview, runner=runner,
                                          scratch_root=self.temp / "scratch")
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["points"], [])
        self.assertEqual(record["point_count_first_attempt_success"], 2)
        failed = record["failed_points"][0]
        self.assertTrue(failed["diagnostic_retry_used"])
        self.assertTrue(failed["diagnostic_retry_succeeded"])
        self.assertTrue(record["error"]["native_abort"])
        manifest = {entry["temperature_C"]: entry for entry in record["point_manifest"]}
        self.assertFalse(manifest[650.0]["first_attempt_success"])
        self.assertTrue(manifest[650.0]["diagnostic_retry_succeeded"])
        self.assertEqual(manifest[650.0]["solve_status"], "failed")
        # 3 points plus exactly one diagnostic retry.
        self.assertEqual(len(calls), 4)

    def test_point_manifest_carries_the_full_contract(self):
        _, record = self._record()
        manifest = record["point_manifest"]
        self.assertEqual(len(manifest), 3)
        required = {"point_index", "request_hash", "temperature_C", "temperature_K", "components",
                    "phases", "va_present", "database_sha256", "worker_pid", "worker_returncode",
                    "solve_status", "active_phases", "phase_fractions_mole", "phase_fraction_sum",
                    "runtime_s", "stderr_summary", "first_attempt_success", "solver_mode"}
        for entry in manifest:
            self.assertLessEqual(required, set(entry), entry["temperature_C"])
            self.assertTrue(entry["first_attempt_success"])
            self.assertTrue(entry["va_present"])
            self.assertEqual(entry["solve_status"], "ok")
            self.assertEqual(entry["solver_mode"], INDEPENDENT_SOLVER_MODE)
            self.assertEqual(len(entry["request_hash"]), 64)
            self.assertEqual(entry["phase_fraction_sum"], 1.0)
            self.assertEqual(entry["database_sha256"],
                             record["database"]["sha256"])
        self.assertEqual(record["manifest_digest"], digest_value(manifest))
        self.assertEqual(len(record["manifest_digest"]), 64)

    def test_batch_mode_is_diagnostic_only_and_unknown_modes_block(self):
        preview = self.preview()
        batch = run_phase_fraction_curve(
            preview, runner=self.fake_runner(), scratch_root=self.temp / "scratch_batch",
            solver_mode=BATCH_SOLVER_MODE,
        )
        self.assertEqual(batch["status"], "computed")
        self.assertEqual(batch["solver_mode"], BATCH_SOLVER_MODE)
        self.assertFalse(batch["formal_solver_mode"])
        self.assertTrue(batch["batch_warm_start_diagnostic_only"])
        unknown = run_phase_fraction_curve(
            preview, runner=self.fake_runner(), scratch_root=self.temp / "scratch_unknown",
            solver_mode="some_other_mode",
        )
        self.assertEqual(unknown["status"], "failed")
        self.assertEqual(unknown["error"]["code"], "CALPHAD-CONFIG-003")
        self.assertEqual(unknown["points"], [])

    def test_committed_policy_declares_the_formal_mode_and_anti_splicing_rules(self):
        policy = load_reduced_system_policy()
        self.assertEqual(policy["formal_solver_mode"], INDEPENDENT_SOLVER_MODE)
        modes = policy["solver_modes"]
        independent = modes[INDEPENDENT_SOLVER_MODE]
        self.assertTrue(independent["formal_pilot"])
        self.assertEqual(independent["status"], "formal_pilot")
        for rule in ("one_temperature_per_process", "fresh_process_per_point",
                     "recreate_database_model_workspace_each_process", "serial_only_no_parallel",
                     "no_warm_start_from_previous_point"):
            self.assertTrue(independent["rules"][rule], rule)
        retry = independent["retry_policy"]
        self.assertTrue(retry["formal_acceptance_requires_first_attempt_success"])
        self.assertTrue(retry["diagnostic_retry_may_not_be_spliced_into_the_formal_curve"])
        self.assertTrue(retry["formal_curve_must_not_contain_selectively_retried_data"])
        self.assertFalse(modes[BATCH_SOLVER_MODE]["formal_pilot"])
        self.assertEqual(modes[BATCH_SOLVER_MODE]["status"], "diagnostic_only")
        self.assertIn("solver_mode", policy["required_result_fields"])
        report = validate_reduced_system_policy()
        self.assertEqual(report["status"], "passed", report["problems"])

    def test_a_policy_promoting_the_batch_mode_fails_closed(self):
        report = validate_reduced_system_policy(self.write_reduced_policy(
            lambda policy: policy.update({"formal_solver_mode": BATCH_SOLVER_MODE})
        ))
        self.assertEqual(report["status"], "failed")
        self.assertIn(INDEPENDENT_SOLVER_MODE, " ".join(report["problems"]))

    def test_worker_rejects_a_multi_temperature_independent_request(self):
        """The worker must refuse to reintroduce warm-starting inside the formal mode."""
        request = self.temp / "request.json"
        result = self.temp / "result.json"
        request.write_text(json.dumps({
            "request_schema_version": "1.1",
            "units": {"temperature_input": "degC", "composition_input": "wt_pct",
                      "output_phase_fraction": "mole_fraction_of_phase"},
            "claims": {"is_complete_phase_diagram": False},
            "components": ["FE", "C", "VA"],
            "component_mole_fractions": {"C": 0.01},
            "temperature": {"values_K": [1000.0, 1100.0]},
            "database": {"path": "x.tdb", "sha256": "0" * 64},
            "phases": ["BCC_A2"],
            "component_profile": {"profile_id": "steel_matrix_equilibrium_v1",
                                  "included_elements": ["Fe", "C"]},
            "phase_profile": {"profile_id": "steel_matrix_major_carbides_v1"},
            "reduced_system_approval": {"reviewer_id": "unit-test-reviewer",
                                        "approved_at": "2026-09-25",
                                        "approval_reason": "unit test",
                                        "acknowledged": True},
            "solver_mode": INDEPENDENT_SOLVER_MODE,
            "single_point_process": True,
            "no_warm_start": True,
        }), encoding="utf-8")
        completed = subprocess.run(
            [sys.executable, "-B", str(ROOT / "scripts" / "calphad_phase_fraction_worker.py"),
             str(request), str(result)],
            capture_output=True, encoding="utf-8", errors="replace", timeout=120, check=False,
            cwd=str(ROOT),
        )
        self.assertEqual(completed.returncode, 2)
        payload = json.loads(result.read_text(encoding="utf-8"))
        self.assertEqual(payload["error_code"], "CALPHAD-WORKER-MODE-001")

    def test_heavy_acceptance_script_requires_an_explicit_reviewer(self):
        script = (ROOT / "scripts" / "calphad_phase5_acceptance.py").read_text(encoding="utf-8")
        self.assertIn("independent_single_point_process_v1", script)
        self.assertIn("--reviewer-id", script)
        self.assertIn('parser.add_argument("--reviewer-id", default="")', script)
        self.assertIn("代码不代填姓名", script)
        document = (ROOT / "docs" / "T86_PHASE5_INDEPENDENT_POINTS.md")
        self.assertTrue(document.is_file())


class PortfolioDemoTests(_AdapterCase):
    """T86 portfolio scope: the public synthetic demo plus the split final status."""

    def test_committed_demo_policy_is_valid_and_public(self):
        report = validate_portfolio_demo_policy()
        self.assertEqual(report["status"], "passed", report["problems"])
        policy = load_portfolio_demo_policy()
        self.assertEqual(policy["policy_id"], "SteelAI-CALPHAD-Portfolio-Demo-Policy-v1.0")
        self.assertTrue(policy["public_synthetic_input"])
        self.assertEqual(policy["composition_wt_pct"]["C"], 0.45)
        self.assertEqual(tuple(policy["phase_profile"]["phases"]), PORTFOLIO_DEMO_REQUIRED_PHASES)
        self.assertEqual(policy["solver_mode"], INDEPENDENT_SOLVER_MODE)
        for key, value in PORTFOLIO_DEMO_FLAGS.items():
            self.assertEqual(policy["required_result_flags"][key], value, key)
        self.assertIn("data/processed", policy["no_write_back"])
        # The demo is bound to the public synthetic identity, never to a private sample record.
        self.assertNotIn("sample_id", policy)
        self.assertEqual(sorted(policy["composition_wt_pct"]), ["C", "Fe"])
        self.assertNotRegex(json.dumps(policy, ensure_ascii=False), r"0\.0[0-9]{3,}")

    def test_a_tampered_demo_policy_fails_closed(self):
        for mutate in (
            lambda policy: policy["phase_profile"].update({"phases": ["LIQUID", "BCC_A2"]}),
            lambda policy: policy["phase_profile"]["phases"].append("GRAPHITE"),
            lambda policy: policy.update({"public_synthetic_input": False}),
            lambda policy: policy["composition_wt_pct"].update({"C": 0.9}),
            lambda policy: policy.update({"solver_mode": BATCH_SOLVER_MODE}),
            lambda policy: policy["required_result_flags"].update({"not_for_scientific_conclusion": False}),
        ):
            with self.subTest(mutation=mutate):
                report = validate_portfolio_demo_policy(self.write_demo_policy(mutate=mutate))
                self.assertEqual(report["status"], "failed")

    def test_demo_preview_is_ready_and_uses_only_verified_phases(self):
        preview = self.demo_preview()
        self.assertEqual(preview.state, "ready", self.codes(preview))
        request = preview.request
        self.assertTrue(request["portfolio_demo"])
        self.assertTrue(request["public_synthetic_input"])
        self.assertTrue(request["not_for_scientific_conclusion"])
        self.assertEqual(request["components"], ["FE", "C"])
        self.assertEqual(tuple(request["phases"]), PORTFOLIO_DEMO_REQUIRED_PHASES)
        self.assertEqual(request["solver_mode"], INDEPENDENT_SOLVER_MODE)
        self.assertEqual(len(request["temperature"]["values_C"]), 25)
        self.assertEqual(request["temperature"]["min_C"], 400.0)
        self.assertEqual(request["temperature"]["max_C"], 1600.0)
        self.assertEqual(request["temperature"]["step_C"], 50.0)
        self.assertEqual(request["pressure_Pa"], 101325)
        self.assertEqual(request["database"]["sha256"], preview.database["sha256"])
        self.assertEqual(request["sample_id"], "fec_public_synthetic_v1")

    def test_demo_needs_no_scientific_approval_but_real_runs_still_do(self):
        demo = self.demo_preview()
        self.assertEqual(demo.state, "ready", self.codes(demo))
        self.assertNotIn("CALPHAD-COMP-011", self.codes(demo))
        self.assertTrue(demo.request["reduced_system_approval"]["no_scientific_approval_required"])

        real = self.preview(reduced_system_reviewer_id="")
        self.assertIn("CALPHAD-COMP-011", self.codes(real))
        self.assertIsNone(real.request)

    def test_demo_blocks_when_the_database_hash_or_phases_disagree(self):
        registry_path = self.demo_registry()
        mismatched = self.write_demo_policy(registry_path, mutate=lambda policy: policy["database"].update(
            {"sha256": "0" * 64}))
        preview = preview_portfolio_demo(registry_path=registry_path,
                                         demo_policy_path=mismatched,
                                         environment=READY_ENVIRONMENT)
        self.assertEqual(preview.state, "blocked")
        self.assertIn("CALPHAD-DEMO-002", self.codes(preview))

        narrow = self.write_registry({"declared_temperature_range_C": [400, 1727],
                                      "covered_phases": [name for name in COVERED_PHASES
                                                         if name != "CEMENTITE"]})
        blocked = preview_portfolio_demo(registry_path=narrow,
                                         demo_policy_path=self.write_demo_policy(narrow),
                                         environment=READY_ENVIRONMENT)
        self.assertEqual(blocked.state, "blocked")
        self.assertIn("CALPHAD-DEMO-003", self.codes(blocked))

        too_narrow_range = self.write_registry({"declared_temperature_range_C": [500, 1200]})
        out_of_range = preview_portfolio_demo(
            registry_path=too_narrow_range,
            demo_policy_path=self.write_demo_policy(too_narrow_range),
            environment=READY_ENVIRONMENT)
        self.assertEqual(out_of_range.state, "blocked")
        self.assertIn("CALPHAD-DEMO-004", self.codes(out_of_range))

    def test_demo_record_and_downloads_carry_every_required_flag(self):
        preview = self.demo_preview()
        record = run_phase_fraction_curve(
            preview, runner=self.fake_runner(), scratch_root=self.temp / "scratch"
        )
        self.assertEqual(record["status"], "computed")
        self.assertTrue(record["portfolio_demo"])
        self.assertTrue(record["public_synthetic_input"])
        self.assertTrue(record["not_for_scientific_conclusion"])
        self.assertEqual(record["result_type"], "model_prediction_not_experimental_measurement")
        self.assertFalse(record["is_complete_phase_diagram"])
        self.assertFalse(record["writes_back_formal_experimental_data"])
        self.assertEqual(record["solver_mode"], INDEPENDENT_SOLVER_MODE)
        self.assertEqual(record["pycalphad_version"], "0.11.2")
        self.assertIn("sha256", record["database"])
        self.assertEqual(record["components"], ["FE", "C"])
        self.assertEqual(record["pressure_Pa"], 101325)

        markdown = phase_fraction_curve_markdown(record)
        for token in ("portfolio_demo=true", "public_synthetic_input=true",
                      "not_for_scientific_conclusion=true",
                      "不得用于论文结论、真实钢种分析或生产决策"):
            self.assertIn(token, markdown)
        csv_text = phase_fraction_csv(record)
        for token in ("# portfolio_demo: true", "# public_synthetic_input: true",
                      "# not_for_scientific_conclusion: true",
                      "# solver_mode: independent_single_point_process_v1"):
            self.assertIn(token, csv_text)
        data_rows = [line for line in csv_text.splitlines() if line and not line.startswith("#")]
        self.assertTrue(data_rows[0].endswith("portfolio_demo") or "portfolio_demo" in data_rows[0])
        self.assertTrue(all("true" in row for row in data_rows[1:]))

    def test_a_real_sample_request_cannot_claim_to_be_a_demo(self):
        request = self.temp / "request.json"
        result = self.temp / "result.json"
        request.write_text(json.dumps({
            "request_schema_version": "1.1",
            "units": {"temperature_input": "degC", "composition_input": "wt_pct",
                      "output_phase_fraction": "mole_fraction_of_phase"},
            "claims": {"is_complete_phase_diagram": False},
            "components": ["FE", "C", "VA"],
            "component_mole_fractions": {"C": 0.02},
            "temperature": {"values_K": [1000.0]},
            "database": {"path": "x.tdb", "sha256": "0" * 64},
            "phases": ["BCC_A2"],
            "component_profile": {"profile_id": "steel_matrix_equilibrium_v1",
                                  "included_elements": ["Fe", "C"]},
            "phase_profile": {"profile_id": "steel_matrix_major_carbides_v1"},
            "reduced_system_approval": {"reviewer_id": "unit-test-reviewer",
                                        "approved_at": "2026-09-25",
                                        "approval_reason": "unit test",
                                        "acknowledged": True},
            "solver_mode": INDEPENDENT_SOLVER_MODE,
            "single_point_process": True,
            "no_warm_start": True,
            "portfolio_demo": True,
            "public_synthetic_input": False,
            "not_for_scientific_conclusion": False,
        }), encoding="utf-8")
        completed = subprocess.run(
            [sys.executable, "-B", str(ROOT / "scripts" / "calphad_phase_fraction_worker.py"),
             str(request), str(result)],
            capture_output=True, encoding="utf-8", errors="replace", timeout=120, check=False,
            cwd=str(ROOT),
        )
        self.assertEqual(completed.returncode, 2)
        payload = json.loads(result.read_text(encoding="utf-8"))
        self.assertEqual(payload["error_code"], "CALPHAD-WORKER-DEMO-001")

    def test_committed_configuration_records_the_split_status(self):
        registry = load_adapter_config()
        split = registry["status_split"]
        self.assertEqual(split["portfolio"]["status"], PORTFOLIO_STATUS_COMPLETE)
        self.assertEqual(split["portfolio"]["completed_value"], PORTFOLIO_STATUS_COMPLETE)
        self.assertEqual(split["scientific"]["status"], SCIENTIFIC_STATUS_BLOCKED)
        self.assertTrue(split["portfolio"]["owner_signature_required"])
        self.assertEqual(split["portfolio"]["owner_signature_status"], "signed")
        self.assertIn("已由项目负责人签署", split["portfolio"]["owner_signature_note"])
        self.assertEqual(split["scientific"]["published_curves"], [])
        self.assertIsNone(split["scientific"]["materials_conclusion"])
        self.assertTrue(split["scientific"]["evidence_preserved_unchanged"])
        self.assertEqual(len(split["scientific"]["reasons"]), 3)
        demo = split["portfolio"]["public_demo"]
        self.assertEqual(demo["result"], "portfolio_exploration_complete")
        self.assertEqual(demo["max_abs_difference_between_runs"], 0.0)
        self.assertFalse(demo["reads_private_data"])
        self.assertFalse(demo["writes_back_to_processed_data"])

    def test_phase_failure_evidence_is_preserved(self):
        for name in ("calphad_phase4_evidence_v1.0.json", "calphad_phase5_evidence_v1.0.json"):
            path = ROOT / "config" / name
            self.assertTrue(path.is_file(), name)
        phase5 = json.loads((ROOT / "config" / "calphad_phase5_evidence_v1.0.json").read_text(
            encoding="utf-8"))
        self.assertEqual(phase5["totals"]["independent_points_attempted"], 324)
        self.assertEqual(phase5["totals"]["first_attempt_success"], 320)
        self.assertEqual(phase5["status"]["t86"], "Blocked")
        mode = phase5["batch_vs_independent"]
        self.assertFalse(mode["status"] == "ok")
        self.assertGreater(mode["max_abs_difference"], mode["tolerance"])

    def test_portfolio_summary_exists_and_is_linked(self):
        summary = ROOT / "docs" / "T86_PORTFOLIO_SUMMARY.md"
        self.assertTrue(summary.is_file())
        text = summary.read_text(encoding="utf-8")
        for token in (PORTFOLIO_STATUS_COMPLETE, SCIENTIFIC_STATUS_BLOCKED,
                      "portfolio_demo", "public_synthetic_input", "not_for_scientific_conclusion",
                      "1.069", "0.0", "VA", "ODbL", "MIT"):
            self.assertIn(token, text)
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("T86_PORTFOLIO_SUMMARY.md", readme)
        release = (ROOT / "docs" / "T64_PORTFOLIO_RELEASE.md").read_text(encoding="utf-8")
        self.assertIn("T86_PORTFOLIO_SUMMARY.md", release)

    def test_demo_acceptance_script_is_fast_and_does_not_run_the_heavy_suite(self):
        script = (ROOT / "scripts" / "calphad_portfolio_demo_acceptance.py").read_text(encoding="utf-8")
        self.assertIn("preview_portfolio_demo", script)
        self.assertIn("DEMO_TOLERANCE = 1e-7", script)
        self.assertNotIn("calphad_phase5_acceptance", script)
        self.assertNotIn("--runs 3", script)
        self.assertIn("main_app_without_pycalphad", script)


class OwnerAcceptanceTests(_AdapterCase):
    """T86 owner sign-off: a portfolio-only signature that can never authorise scientific use."""

    def write_acceptance(self, mutate=None) -> Path:
        record = json.loads(OWNER_ACCEPTANCE_PATH.read_text(encoding="utf-8"))
        if mutate is not None:
            mutate(record)
        path = self.temp / f"owner_acceptance_{uuid.uuid4().hex[:8]}.json"
        path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        return path

    @staticmethod
    def entry_of(record: dict) -> dict:
        return record["entries"][0]

    def test_committed_acceptance_record_is_signed_and_complete(self):
        report = validate_owner_acceptance()
        self.assertEqual(report["status"], "passed", report["problems"])
        self.assertTrue(report["signed"])
        self.assertEqual(report["record_id"], "T86-PORTFOLIO-OWNER-SIGN-OFF-20260925")
        self.assertEqual(report["responsible_person_id"], "世道")
        self.assertEqual(report["signed_at"], "2026-09-25")
        self.assertEqual(report["timezone"], "Asia/Shanghai")
        self.assertEqual(report["decision_scope"], "portfolio_engineering_acceptance_only")
        self.assertEqual(report["portfolio_demo_evidence_version"],
                         "SteelAI-T86-Portfolio-Demo-Evidence-v1.0")
        self.assertEqual(report["acceptance_evidence"].get("checks_passed"), 7)
        self.assertEqual(report["acceptance_evidence"].get("max_abs_difference_between_runs"), 0.0)
        self.assertEqual(report["engineering_status"], PORTFOLIO_STATUS_COMPLETE)
        self.assertEqual(report["scientific_status"], SCIENTIFIC_STATUS_BLOCKED)

    def test_the_signature_authorises_no_scientific_use(self):
        report = validate_owner_acceptance()
        self.assertIs(report["scientific_use_approved"], False)
        self.assertIs(report["real_sample_curves_published"], False)
        self.assertIs(report["materials_conclusion_approved"], False)
        self.assertEqual(report["demo_configuration"]["demo_id"], "fec_public_synthetic_v1")
        self.assertEqual(tuple(report["demo_configuration"]["phases"]),
                         PORTFOLIO_DEMO_REQUIRED_PHASES)
        self.assertEqual(report["demo_configuration"]["solver_mode"], INDEPENDENT_SOLVER_MODE)
        self.assertEqual(
            report["database"]["sha256"],
            "7cf37dd423e14264ee67467011b6cb0ea90647fc365823899c29f7e827a12042",
        )
        for forbidden in ("真实钢种科研计算", "论文结论", "材料结论或生产决策"):
            self.assertTrue(any(forbidden in item
                                for item in report["explicitly_not_approved_for"]), forbidden)

    def test_a_tampered_signature_record_fails_closed(self):
        def approve_science(record):
            self.entry_of(record)["scientific_use_approved"] = True

        def publish_curves(record):
            self.entry_of(record)["real_sample_curves_published"] = True

        def approve_materials(record):
            self.entry_of(record)["materials_conclusion_approved"] = True

        def widen_scope(record):
            self.entry_of(record)["decision_scope"] = "scientific_use_approved"

        def wrong_timezone(record):
            self.entry_of(record)["timezone"] = "UTC"

        def no_signer(record):
            self.entry_of(record)["responsible_person_id"] = ""

        def mismatch_reviewer(record):
            self.entry_of(record)["reviewer_id"] = "someone_else"

        def wrong_demo(record):
            self.entry_of(record)["demo_configuration"]["phases"] = ["LIQUID", "BCC_A2"]

        def wrong_hash(record):
            self.entry_of(record)["database"]["sha256"] = "0" * 64

        def flip_status(record):
            self.entry_of(record)["scientific_status_after_signature"] = "pilot_ready"

        def drop_record(record):
            record["entries"] = []

        for mutate in (approve_science, publish_curves, approve_materials, widen_scope,
                       wrong_timezone, no_signer, mismatch_reviewer, wrong_demo, wrong_hash,
                       flip_status, drop_record):
            with self.subTest(mutation=getattr(mutate, "__name__", mutate)):
                report = validate_owner_acceptance(self.write_acceptance(mutate))
                self.assertEqual(report["status"], "failed", report["problems"])
                self.assertFalse(report["signed"])

    def test_status_pair_is_complete_and_blocked(self):
        status = owner_acceptance_status()
        self.assertEqual(status["portfolio"], PORTFOLIO_STATUS_COMPLETE)
        self.assertEqual(status["scientific"], SCIENTIFIC_STATUS_BLOCKED)
        self.assertTrue(status["portfolio_signed"])
        self.assertEqual(status["responsible_person_id"], "世道")
        self.assertEqual(status["timezone"], "Asia/Shanghai")
        self.assertEqual(status["decision_scope"], "portfolio_engineering_acceptance_only")
        self.assertIs(status["scientific_use_approved"], False)
        self.assertIs(status["real_sample_curves_published"], False)
        self.assertIs(status["materials_conclusion_approved"], False)
        self.assertEqual(status["problems"], [])

    def test_feature_status_and_registry_report_the_signed_dual_status(self):
        feature = calphad_feature_status()
        split = feature["status_split"]
        self.assertEqual(split["portfolio"], PORTFOLIO_STATUS_COMPLETE)
        self.assertEqual(split["scientific"], SCIENTIFIC_STATUS_BLOCKED)
        self.assertTrue(split["portfolio_signed"])
        self.assertEqual(split["responsible_person_id"], "世道")
        self.assertEqual(split["signed_at"], "2026-09-25")
        self.assertEqual(split["timezone"], "Asia/Shanghai")
        self.assertEqual(split["decision_scope"], "portfolio_engineering_acceptance_only")
        self.assertIs(split["scientific_use_approved"], False)

        registry = load_adapter_config()
        self.assertEqual(registry["status_split"]["portfolio"]["status"], PORTFOLIO_STATUS_COMPLETE)
        self.assertEqual(registry["status_split"]["portfolio"]["owner_signature_status"], "signed")
        self.assertEqual(registry["status_split"]["scientific"]["status"], SCIENTIFIC_STATUS_BLOCKED)
        record = registry["status_split"]["portfolio"]["owner_acceptance_record"]
        self.assertEqual(record["responsible_person_id"], "世道")
        self.assertEqual(record["signed_at"], "2026-09-25")
        self.assertEqual(record["timezone"], "Asia/Shanghai")
        self.assertEqual(record["decision_scope"], "portfolio_engineering_acceptance_only")
        self.assertEqual(record["file"], "config/calphad_owner_acceptance_v1.0.json")
        self.assertIs(record["scientific_use_approved"], False)
        self.assertIs(record["real_sample_curves_published"], False)
        self.assertIs(record["materials_conclusion_approved"], False)
        # A signed portfolio status never publishes real curves or a materials conclusion.
        self.assertEqual(registry["status_split"]["scientific"]["published_curves"], [])
        self.assertIsNone(registry["status_split"]["scientific"]["materials_conclusion"])

    def test_signature_is_registered_in_the_portfolio_acceptance_index(self):
        index = json.loads(PORTFOLIO_ACCEPTANCE_INDEX_PATH.read_text(encoding="utf-8"))
        self.assertEqual(index["registry_id"], "SteelAI-Portfolio-Acceptance-v1.0")
        matching = [row for row in index["entries"]
                    if row.get("record_id") == OWNER_ACCEPTANCE_RECORD_ID]
        self.assertEqual(len(matching), 1)
        row = matching[0]
        self.assertEqual(row["decision"], "approved")
        self.assertEqual(row["reviewer_id"], "世道")
        self.assertEqual(row["accepted_on"], "2026-09-25")
        self.assertEqual(row["result_level"], "portfolio_demo_only")
        # The project's own run-centre loader must accept the new entry.
        from steelai.run_center import load_portfolio_acceptances

        loaded = load_portfolio_acceptances(PORTFOLIO_ACCEPTANCE_INDEX_PATH)
        self.assertIn(OWNER_ACCEPTANCE_RECORD_ID, loaded)
        self.assertEqual(loaded[OWNER_ACCEPTANCE_RECORD_ID]["reviewer_id"], "世道")
        self.assertIn("T40-EBC752D15CFE43A605D1", loaded)

    def test_page_and_documents_report_the_signature(self):
        view = (ROOT / "steelai" / "views" / "physics_view.py").read_text(encoding="utf-8")
        self.assertIn("portfolio_signed", view)
        self.assertIn("owner_split.get('responsible_person_id')", view)
        self.assertIn("scientific_use_approved=false", view)

        summary = (ROOT / "docs" / "T86_PORTFOLIO_SUMMARY.md").read_text(encoding="utf-8")
        self.assertIn(PORTFOLIO_STATUS_COMPLETE, summary)
        self.assertIn("世道", summary)
        self.assertIn("2026-09-25", summary)
        self.assertIn("Asia/Shanghai", summary)
        self.assertIn("portfolio_engineering_acceptance_only", summary)
        self.assertIn("SteelAI-T86-Portfolio-Demo-Evidence-v1.0", summary)
        self.assertIn("scientific_use_approved", summary)
        self.assertIn("calphad_owner_acceptance_v1.0.json", summary)
        self.assertNotIn("portfolio_exploration_complete_pending_owner_signature", summary)

        for path in ("TASKS.md", "README.md", "docs/CURRENT_CAPABILITIES.md",
                     "docs/KNOWN_LIMITATIONS.md", "project_log/CHANGELOG.md",
                     "docs/T64_PORTFOLIO_RELEASE.md"):
            text = (ROOT / path).read_text(encoding="utf-8")
            self.assertIn("世道", text, path)

        tasks = (ROOT / "TASKS.md").read_text(encoding="utf-8")
        self.assertIn(PORTFOLIO_STATUS_COMPLETE, tasks)
        self.assertIn(SCIENTIFIC_STATUS_BLOCKED, tasks)

    def test_signature_does_not_upgrade_the_scientific_status_anywhere(self):
        for path in ("README.md", "TASKS.md", "docs/CURRENT_CAPABILITIES.md",
                     "docs/KNOWN_LIMITATIONS.md", "docs/T86_PORTFOLIO_SUMMARY.md"):
            text = (ROOT / path).read_text(encoding="utf-8")
            self.assertIn(SCIENTIFIC_STATUS_BLOCKED, text, path)
        # The scientific side must never be reported as approved or validated by this signature.
        registry = load_adapter_config()["status_split"]
        self.assertIs(registry["scientific"]["materials_conclusion"], None)
        self.assertEqual(registry["scientific"]["published_curves"], [])
        self.assertEqual(registry["portfolio"]["owner_acceptance_record"][
            "scientific_use_approved"], False)


if __name__ == "__main__":
    unittest.main()
