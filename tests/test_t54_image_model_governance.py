from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from steelai.governance import GovernanceError, load_verified_manifest, verify_package
from steelai.image_model_governance import (
    inspect_image_model_package,
    list_image_model_result_index,
    preview_image_model_task,
    record_image_model_run,
    register_image_model_task,
    review_image_model_run,
)


STAMP = "2026-09-09T12:00:00+00:00"


class ImageModelGovernanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "private raw SEM image 001.tif"
        self.source.write_bytes(b"synthetic-image-fixture-v1")
        self.output = self.root / "isolated-runtime" / "mask.bin"
        self.output.parent.mkdir()
        self.output.write_bytes(b"synthetic-model-output-v1")
        self.tasks = self.root / "tasks"
        self.runs = self.root / "runs"
        self.reviews = self.root / "reviews"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def source_record(self, modality: str = "SEM") -> dict:
        return {
            "source_id": f"SRC-{modality}-01",
            "source_path": str(self.source),
            "source_status": "read_only_verified",
            "source_revision": 1,
            "modality": modality,
            "sample_id": "SYN-B-DQ",
            "specimen_id": "SYN-B-DQ-01",
            "image_field_id": f"FIELD-{modality}-01",
        }

    def register_task(self, modality: str = "SEM") -> dict:
        return register_image_model_task(
            f"SYN-{modality}-TASK",
            modality=modality,
            task_type="fracture_segmentation" if modality == "SEM" else "orientation_map_analysis",
            sources=[self.source_record(modality)],
            software_id="micro-sam" if modality == "SEM" else "mtex",
            software_version="1.0-test",
            model_id="sam-vit-b" if modality == "SEM" else "basic-ebsd-pipeline",
            model_version="fixture-v1",
            parameters={"threshold": 0.5, "raw_files_read_only": True},
            environment={
                "environment_id": f"isolated-{modality.lower()}-fixture",
                "runtime": "python" if modality == "SEM" else "matlab",
                "runtime_version": "fixture-1",
                "isolated_from_workbench": True,
                "hardware_profile": "test-cpu",
            },
            reviewer_id="researcher-test",
            rationale="Synthetic fixture parameters reviewed for governance contract testing.",
            decided_at=STAMP,
            output_root=self.tasks,
        )

    def record_run(self, task: dict, *, outcome: str = "completed", attempt: int = 1, rerun_of=None) -> dict:
        outputs = [] if outcome in {"failed", "canceled"} else [
            {"output_id": "MASK-01", "path": str(self.output), "media_type": "application/octet-stream"}
        ]
        return record_image_model_run(
            task["package"],
            outcome=outcome,
            outputs=outputs,
            attempt=attempt,
            rerun_of=rerun_of,
            error_code="RUNTIME-TEST" if outcome == "failed" else None,
            error_summary="Synthetic runtime failure." if outcome == "failed" else None,
            started_at=STAMP,
            finished_at=STAMP,
            output_root=self.runs,
        )

    def test_ebsd_and_sem_task_manifest_registers_identity_without_copying_raw_file(self) -> None:
        original = self.source.read_bytes()
        for modality in ("SEM", "EBSD"):
            task = self.register_task(modality)
            package = Path(task["package"])
            self.assertEqual(verify_package(package).status, "passed")
            payload = json.loads((package / "image_task_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["modality"], modality)
            self.assertEqual(payload["governance_state"], "needs_human")
            self.assertTrue(payload["environment"]["isolated_from_workbench"])
            self.assertFalse(payload["sources"][0]["raw_file_copied"])
            serialized = json.dumps(payload, ensure_ascii=False)
            self.assertNotIn(str(self.source), serialized)
            self.assertNotIn(self.source.name, serialized)
            self.assertFalse(any(path.suffix.lower() in {".tif", ".ctf"} for path in package.rglob("*")))
        self.assertEqual(self.source.read_bytes(), original)

    def test_completed_run_is_traceable_but_defaults_to_needs_human(self) -> None:
        task = self.register_task()
        run = self.record_run(task)
        package = Path(run["package"])
        manifest = load_verified_manifest(package)
        record = json.loads((package / "model_run_record.json").read_text(encoding="utf-8"))
        trace = json.loads((package / "result_traceability.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest.state, "needs_human")
        self.assertEqual(manifest.result_level, "working_candidate")
        self.assertEqual(record["technical_outcome"], "completed")
        self.assertFalse(record["boundaries"]["formal_evidence_allowed"])
        self.assertEqual(trace["task_id"], task["task_id"])
        self.assertEqual(trace["source_ids"], ["SRC-SEM-01"])
        self.assertEqual(trace["output_ids"], ["MASK-01"])
        self.assertEqual(record["model"]["model_version"], "fixture-v1")
        self.assertEqual(record["environment"]["environment_id"], "isolated-sem-fixture")

    def test_human_review_creates_model_result_and_result_index(self) -> None:
        run = self.record_run(self.register_task())
        review = review_image_model_run(
            run["package"],
            reviewer_id="researcher-test",
            decision="approved",
            rationale="Mask boundary and failure cases were reviewed.",
            scope="Synthetic contract fixture only.",
            accepted_output_ids=["MASK-01"],
            decided_at=STAMP,
            output_root=self.reviews,
        )
        package = Path(review["package"])
        manifest = load_verified_manifest(package)
        index = json.loads((package / "result_index_record.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest.state, "complete")
        self.assertEqual(manifest.result_level, "model_result")
        self.assertEqual(manifest.evidence_class, "model_output")
        self.assertTrue(index["evidence_eligible"])
        self.assertFalse(json.loads((package / "human_review.json").read_text(encoding="utf-8"))["is_experimental_measurement"])
        rows = list_image_model_result_index(self.reviews)
        self.assertEqual([row["review_id"] for row in rows], [review["review_id"]])

    def test_partial_requires_explicit_warning_acceptance(self) -> None:
        run = self.record_run(self.register_task(), outcome="partial")
        with self.assertRaises(GovernanceError) as context:
            review_image_model_run(
                run["package"],
                reviewer_id="researcher-test",
                decision="approved",
                rationale="Review attempted.",
                scope="Fixture scope.",
                decided_at=STAMP,
                output_root=self.reviews,
            )
        self.assertEqual(context.exception.code, "GOV-WARNING-001")
        accepted = review_image_model_run(
            run["package"],
            reviewer_id="researcher-test",
            decision="warning_accepted",
            rationale="The missing portion is retained as an explicit limitation.",
            scope="Partial fixture output only.",
            decided_at=STAMP,
            output_root=self.reviews,
        )
        self.assertEqual(accepted["status"], "complete")

    def test_failed_canceled_and_rerun_states_are_stable(self) -> None:
        task = self.register_task()
        failed = self.record_run(task, outcome="failed")
        canceled = self.record_run(task, outcome="canceled", attempt=2, rerun_of=failed["run_id"])
        rerun = self.record_run(task, outcome="completed", attempt=3, rerun_of=failed["run_id"])
        self.assertEqual(failed["status"], "blocked")
        self.assertEqual(canceled["status"], "blocked")
        self.assertEqual(rerun["status"], "needs_human")
        rerun_record = json.loads((Path(rerun["package"]) / "model_run_record.json").read_text(encoding="utf-8"))
        self.assertEqual(rerun_record["attempt"], 3)
        self.assertEqual(rerun_record["rerun_of"], failed["run_id"])

    def test_tampered_run_is_invalidated_and_cannot_be_reviewed(self) -> None:
        run = self.record_run(self.register_task())
        package = Path(run["package"])
        (package / "model_run_record.json").write_text("{}", encoding="utf-8")
        self.assertEqual(inspect_image_model_package(package)["status"], "invalidated")
        with self.assertRaises(GovernanceError) as context:
            review_image_model_run(
                package,
                reviewer_id="researcher-test",
                decision="approved",
                rationale="Should fail.",
                scope="Fixture scope.",
                decided_at=STAMP,
                output_root=self.reviews,
            )
        self.assertEqual(context.exception.code, "GOV-INTEGRITY-001")

    def test_unisolated_runtime_and_missing_source_fail_closed(self) -> None:
        source = self.source_record()
        bad_environment = {
            "environment_id": "embedded-runtime",
            "runtime": "python",
            "runtime_version": "fixture-1",
            "isolated_from_workbench": False,
        }
        with self.assertRaises(GovernanceError) as context:
            preview_image_model_task(
                "BAD-TASK",
                modality="SEM",
                task_type="segmentation",
                sources=[source],
                software_id="micro-sam",
                software_version="1",
                model_id="sam",
                model_version="1",
                parameters={"threshold": 1},
                environment=bad_environment,
            )
        self.assertEqual(context.exception.code, "GOV-RUNTIME-001")
        source["source_path"] = str(self.root / "missing.ctf")
        with self.assertRaises(GovernanceError) as context:
            preview_image_model_task(
                "MISSING-TASK",
                modality="EBSD",
                task_type="orientation_map_analysis",
                sources=[source],
                software_id="mtex",
                software_version="1",
                model_id="basic-ebsd",
                model_version="1",
                parameters={"angle": 3},
                environment={**bad_environment, "isolated_from_workbench": True},
            )
        self.assertEqual(context.exception.code, "GOV-SOURCE-001")


if __name__ == "__main__":
    unittest.main()
