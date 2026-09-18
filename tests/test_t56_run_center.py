from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from steelai.governance import (
    ApprovalSnapshot,
    EvidenceClass,
    ResearchObjectIdentity,
    ResultLevel,
    SourceReference,
    build_manifest,
    create_staging_directory,
    digest_value,
    publish_append_only,
    seal_package,
)
from steelai.portfolio import portfolio_markdown, verified_portfolio_results
from steelai.run_center import (
    accepted_portfolio_results,
    collect_run_records,
    filter_run_records,
    load_portfolio_acceptances,
    run_center_snapshot,
)


STAMP = "2026-09-10T00:00:00+00:00"


class RunCenterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.repository = Path(self.temporary.name)
        self.outputs = self.repository / "outputs"
        self.sessions = self.repository / "project_log" / "research_sessions"
        self.registry = self.repository / "config" / "portfolio_acceptance_v1.0.json"
        self.registry.parent.mkdir(parents=True)
        self.registry.write_text(json.dumps({
            "schema_version": "1.0",
            "registry_id": "SteelAI-Portfolio-Acceptance-v1.0",
            "entries": [],
        }), encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def publish_governed(
        self,
        root_name: str,
        publication_id: str,
        *,
        state: str,
        result_level: ResultLevel,
        evidence_class: EvidenceClass,
        approved: bool = False,
        mismatched_approval: bool = False,
    ) -> Path:
        output_root = self.outputs / root_name
        stage = create_staging_directory(output_root, publication_id)
        payload = {"publication_id": publication_id, "synthetic_fixture": True}
        (stage / "result.json").write_text(json.dumps(payload), encoding="utf-8")
        identity = ResearchObjectIdentity(
            object_type="fixture_result",
            object_id=publication_id,
            revision=1,
            content_digest=digest_value(payload),
            created_at=STAMP,
            created_by="test-fixture",
        )
        approvals = ()
        if approved:
            approval_identity = identity
            if mismatched_approval:
                approval_identity = ResearchObjectIdentity(
                    object_type=identity.object_type,
                    object_id=publication_id + "-OTHER",
                    revision=identity.revision,
                    content_digest=digest_value({"different": publication_id}),
                    created_at=STAMP,
                    created_by="test-fixture",
                )
            approvals = (ApprovalSnapshot.create(
                approval_identity,
                "approved",
                "researcher-test",
                "Synthetic T56 run-center test fixture.",
                "Fixture identity and result were reviewed.",
                decided_at=STAMP,
            ),)
        source = SourceReference(
            source_id="SOURCE-" + publication_id,
            source_revision=1,
            source_digest=digest_value({"source": publication_id}),
            evidence_class=evidence_class.value,
            source_status="synthetic_fixture",
        )
        manifest = build_manifest(
            stage,
            publication_id=publication_id,
            identity=identity,
            state=state,
            result_level=result_level,
            evidence_class=evidence_class,
            sources=(source,),
            approvals=approvals,
            generated_by="test-fixture",
            generated_at=STAMP,
        )
        seal_package(stage, manifest)
        return Path(publish_append_only(stage, output_root / publication_id).destination)

    def collect(self):
        return collect_run_records(
            repository_root=self.repository,
            outputs_root=self.outputs,
            session_root=self.sessions,
            acceptance_registry=self.registry,
        )

    def test_governed_packages_are_normalized_and_locations_are_relative(self) -> None:
        self.publish_governed(
            "governed_data_intake", "INTAKE-COMPLETE",
            state="complete", result_level=ResultLevel.ACCEPTED_EVIDENCE,
            evidence_class=EvidenceClass.REAL_RESEARCH_DATA, approved=True,
        )
        self.publish_governed(
            "physics_runs", "PHYSICS-REVIEW",
            state="needs_human", result_level=ResultLevel.WORKING_CANDIDATE,
            evidence_class=EvidenceClass.MODEL_OUTPUT,
        )
        records = self.collect()
        self.assertEqual({item.task_id for item in records}, {"INTAKE-COMPLETE", "PHYSICS-REVIEW"})
        complete = next(item for item in records if item.task_id == "INTAKE-COMPLETE")
        self.assertTrue(complete.portfolio_eligible)
        self.assertEqual(complete.reviewer_id, "researcher-test")
        self.assertEqual(complete.result_location, "outputs/governed_data_intake/INTAKE-COMPLETE")
        self.assertFalse(Path(complete.result_location).is_absolute())
        review = next(item for item in records if item.task_id == "PHYSICS-REVIEW")
        self.assertEqual(review.state_group, "needs_human")
        self.assertFalse(review.portfolio_eligible)

    def test_approval_must_match_the_current_research_object_identity(self) -> None:
        self.publish_governed(
            "governed_data_intake", "INTAKE-STALE-APPROVAL",
            state="complete", result_level=ResultLevel.ACCEPTED_EVIDENCE,
            evidence_class=EvidenceClass.REAL_RESEARCH_DATA,
            approved=True, mismatched_approval=True,
        )
        record = self.collect()[0]
        self.assertEqual(record.integrity_status, "passed")
        self.assertEqual(record.reviewer_id, "")
        self.assertFalse(record.portfolio_eligible)
        self.assertIn("具名人工验收", record.portfolio_reason)

    def test_tampered_package_is_visibly_invalidated_and_never_portfolio_eligible(self) -> None:
        package = self.publish_governed(
            "governed_statistics", "STATS-TAMPERED",
            state="complete", result_level=ResultLevel.ACCEPTED_EVIDENCE,
            evidence_class=EvidenceClass.REAL_RESEARCH_DATA, approved=True,
        )
        (package / "result.json").write_text("{}", encoding="utf-8")
        record = self.collect()[0]
        self.assertEqual(record.state, "invalidated")
        self.assertEqual(record.state_group, "invalidated")
        self.assertFalse(record.portfolio_eligible)
        self.assertEqual(filter_run_records([record], "完整性失效"), [record])

    def test_complete_agent_working_candidate_is_not_a_portfolio_result(self) -> None:
        self.publish_governed(
            "agent_gateway", "AGENTGW-FIXTURE",
            state="complete", result_level=ResultLevel.WORKING_CANDIDATE,
            evidence_class=EvidenceClass.MODEL_OUTPUT,
        )
        records = self.collect()
        self.assertEqual(records[0].state_group, "completed")
        self.assertFalse(records[0].portfolio_eligible)
        self.assertEqual(accepted_portfolio_results(records), [])

    def test_sessions_and_automation_are_visible_but_not_portfolio_results(self) -> None:
        self.sessions.mkdir(parents=True)
        (self.sessions / "RS-FIXTURE.json").write_text(json.dumps({
            "session_id": "RS-FIXTURE",
            "title": "Synthetic blocked session",
            "status": "blocked",
            "updated_at": STAMP,
        }), encoding="utf-8")
        automation = self.outputs / "automation"
        automation.mkdir(parents=True)
        (automation / "autodimple_br10_status.json").write_text(json.dumps({
            "job_id": "AUTO-FIXTURE",
            "status": "running",
            "started_at": STAMP,
        }), encoding="utf-8")
        records = self.collect()
        by_id = {item.task_id: item for item in records}
        self.assertEqual(by_id["RS-FIXTURE"].state_group, "blocked")
        self.assertEqual(by_id["AUTO-FIXTURE"].state_group, "running")
        self.assertFalse(any(item.portfolio_eligible for item in records))

    def test_frozen_flagship_needs_both_integrity_and_explicit_acceptance(self) -> None:
        package = self.outputs / "flagship_demo" / "T40-FIXTURE"
        package.mkdir(parents=True)
        self.registry.write_text(json.dumps({
            "schema_version": "1.0",
            "registry_id": "SteelAI-Portfolio-Acceptance-v1.0",
            "entries": [{
                "record_id": "T40-FIXTURE",
                "decision": "approved",
                "reviewer_id": "project_owner",
                "scope": "Synthetic engineering demonstration only.",
            }],
        }), encoding="utf-8")
        with patch("steelai.run_center.verify_flagship_demo", return_value={"status": "passed"}):
            record = self.collect()[0]
        self.assertTrue(record.portfolio_eligible)
        self.assertEqual(record.evidence_class, "synthetic_demo_data")
        self.assertIn("工程能力", record.portfolio_reason)

    def test_filters_and_snapshot_have_stable_counts(self) -> None:
        self.publish_governed(
            "governed_data_intake", "INTAKE-OK",
            state="complete", result_level=ResultLevel.ACCEPTED_EVIDENCE,
            evidence_class=EvidenceClass.REAL_RESEARCH_DATA, approved=True,
        )
        self.publish_governed(
            "physics_runs", "PHYSICS-BLOCKED",
            state="blocked", result_level=ResultLevel.WORKING_CANDIDATE,
            evidence_class=EvidenceClass.MODEL_OUTPUT,
        )
        snapshot = run_center_snapshot(
            repository_root=self.repository,
            outputs_root=self.outputs,
            session_root=self.sessions,
            acceptance_registry=self.registry,
        )
        self.assertEqual(snapshot["record_count"], 2)
        self.assertEqual(snapshot["counts"]["blocked"], 1)
        self.assertEqual(snapshot["counts"]["portfolio_eligible"], 1)
        records = self.collect()
        self.assertEqual(
            [item.task_id for item in filter_run_records(records, "需要我处理")],
            ["PHYSICS-BLOCKED"],
        )
        self.assertEqual([item.task_id for item in filter_run_records(records, "已验收成果")], ["INTAKE-OK"])

    def test_portfolio_defense_in_depth_ignores_drafts_and_invalidated_rows(self) -> None:
        accepted = {
            "task_id": "RESULT-1", "title": "Accepted result", "module": "可追溯统计",
            "state": "complete", "integrity_status": "passed", "reviewer_id": "researcher",
            "portfolio_eligible": True, "portfolio_reason": "reviewed",
        }
        draft = {**accepted, "task_id": "DRAFT-1", "title": "Private draft", "state": "needs_human"}
        invalid = {**accepted, "task_id": "BAD-1", "title": "Tampered result", "integrity_status": "invalidated"}
        filtered = verified_portfolio_results([accepted, draft, invalid])
        self.assertEqual([item["task_id"] for item in filtered], ["RESULT-1"])
        report = portfolio_markdown([accepted, draft, invalid])
        self.assertIn("Accepted result", report)
        self.assertNotIn("Private draft", report)
        self.assertNotIn("Tampered result", report)

    def test_acceptance_registry_rejects_path_like_or_unreviewed_entries(self) -> None:
        self.registry.write_text(json.dumps({
            "schema_version": "1.0",
            "registry_id": "SteelAI-Portfolio-Acceptance-v1.0",
            "entries": [
                {"record_id": "../private", "decision": "approved", "reviewer_id": "human", "scope": "x"},
                {"record_id": "NO-REVIEW", "decision": "approved", "reviewer_id": "", "scope": "x"},
            ],
        }), encoding="utf-8")
        self.assertEqual(load_portfolio_acceptances(self.registry), {})


if __name__ == "__main__":
    unittest.main()
