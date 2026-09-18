"""T51 acceptance tests for the reusable SteelAI governance core."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from steelai.governance import (
    ApprovalDecision,
    ApprovalSnapshot,
    EvidenceClass,
    GovernanceError,
    GovernanceManifest,
    GovernanceState,
    ResearchObjectIdentity,
    ResultLevel,
    SourceReference,
    authorize_execution,
    build_manifest,
    create_staging_directory,
    digest_value,
    evaluate_formal_write,
    publish_append_only,
    seal_package,
    transition_state,
    validate_governance_contract,
    verify_package,
)


STAMP = "2026-09-09T08:00:00+00:00"


class GovernanceCoreTests(unittest.TestCase):
    def _identity(self, content: str = "stable result") -> ResearchObjectIdentity:
        return ResearchObjectIdentity.from_content(
            "result",
            "SYN-T51-RESULT-001",
            1,
            {"content": content},
            "t51-test-runner",
            created_at=STAMP,
        )

    def _source(self, content: str = "source") -> SourceReference:
        return SourceReference(
            source_id="SYN-T51-SOURCE-001",
            source_revision=1,
            source_digest=digest_value({"content": content}),
            evidence_class=EvidenceClass.REAL_RESEARCH_DATA.value,
            source_status="synthetic_test_fixture",
            relative_locator="fixtures/source.json",
        )

    def _approval(
        self,
        identity: ResearchObjectIdentity,
        decision: str | ApprovalDecision = ApprovalDecision.APPROVED,
    ) -> ApprovalSnapshot:
        return ApprovalSnapshot.create(
            identity,
            decision,
            "human-reviewer-t51",
            "T51 isolated contract test",
            "Reviewed identity, source and declared scope.",
            decided_at=STAMP,
        )

    def _sealed_stage(
        self,
        root: Path,
        publication_id: str,
        *,
        content: str = "governed output",
    ) -> tuple[Path, ResearchObjectIdentity, ApprovalSnapshot]:
        identity = self._identity(content)
        approval = self._approval(identity)
        stage = create_staging_directory(root, publication_id)
        (stage / "result.txt").write_text(content, encoding="utf-8")
        manifest = build_manifest(
            stage,
            publication_id=publication_id,
            identity=identity,
            state=GovernanceState.COMPLETE,
            result_level=ResultLevel.ACCEPTED_EVIDENCE,
            evidence_class=EvidenceClass.REAL_RESEARCH_DATA,
            sources=(self._source(),),
            approvals=(approval,),
            generated_by="t51-test-runner",
            generated_at=STAMP,
            metadata={"test_fixture": True},
        )
        seal_package(stage, manifest)
        return stage, identity, approval

    def test_frozen_contract_is_loaded_by_the_runtime(self) -> None:
        report = validate_governance_contract()
        self.assertEqual(report["status"], "passed", report["problems"])
        self.assertEqual(report["workspace_count"], 9)
        self.assertEqual(report["state_count"], 10)
        self.assertEqual(report["contract_id"], "SteelAI-Global-Research-Governance-v1.0")

    def test_identity_source_approval_and_manifest_have_stable_round_trip(self) -> None:
        identity = self._identity()
        source = self._source()
        approval = self._approval(identity)
        self.assertEqual(ResearchObjectIdentity.from_dict(identity.to_dict()), identity)
        self.assertEqual(SourceReference.from_dict(source.to_dict()), source)
        self.assertEqual(ApprovalSnapshot.from_dict(approval.to_dict()), approval)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "artifact.json").write_text("{}\n", encoding="utf-8")
            manifest = build_manifest(
                root,
                publication_id="SYN-T51-PACKAGE-001",
                identity=identity,
                state="complete",
                result_level="accepted_evidence",
                evidence_class="real_research_data",
                sources=(source,),
                approvals=(approval,),
                generated_by="t51-test-runner",
                generated_at=STAMP,
            )
        round_trip = GovernanceManifest.from_dict(
            json.loads(json.dumps(manifest.to_dict(), ensure_ascii=False))
        )
        self.assertEqual(round_trip.to_dict(), manifest.to_dict())
        self.assertEqual(round_trip.publication_fingerprint, round_trip.expected_fingerprint())
        extra = round_trip.to_dict()
        extra["unregistered_field"] = "must fail closed"
        with self.assertRaises(ValueError):
            GovernanceManifest.from_dict(extra)

    def test_ai_identity_cannot_create_human_approval(self) -> None:
        with self.assertRaises(GovernanceError) as caught:
            ApprovalSnapshot.create(
                self._identity(),
                "approved",
                "agent-deepseek",
                "test",
                "AI cannot approve this object.",
                decided_at=STAMP,
            )
        self.assertEqual(caught.exception.code, "GOV-AI-AUTH-001")
        self.assertEqual(caught.exception.state, "blocked")

    def test_source_reference_rejects_local_absolute_or_parent_locator(self) -> None:
        common = {
            "source_id": "SYN-T51-SOURCE-001",
            "source_revision": 1,
            "source_digest": digest_value({"source": True}),
            "evidence_class": "real_research_data",
            "source_status": "synthetic_test_fixture",
        }
        windows_absolute = "C" + ":/" + "Users/person/secret.csv"
        for locator in (windows_absolute, "../secret.csv", "folder\\secret.csv", ""):
            with self.subTest(locator=locator):
                with self.assertRaises(ValueError):
                    SourceReference(**common, relative_locator=locator)

    def test_controlled_execution_requires_current_hash_bound_approval(self) -> None:
        identity = self._identity()
        with self.assertRaises(GovernanceError) as missing:
            authorize_execution(identity, "approved", None, occurred_at=STAMP)
        self.assertEqual(missing.exception.code, "GOV-APPROVAL-001")

        stale_identity = self._identity("changed after approval")
        with self.assertRaises(GovernanceError) as stale:
            authorize_execution(stale_identity, "approved", self._approval(identity), occurred_at=STAMP)
        self.assertEqual(stale.exception.code, "GOV-APPROVAL-001")

        record = authorize_execution(identity, "approved", self._approval(identity), occurred_at=STAMP)
        self.assertEqual(record.from_state, "approved")
        self.assertEqual(record.to_state, "running")
        self.assertTrue(record.transition_id.startswith("TRN-"))

    def test_invalid_state_shortcuts_fail_closed(self) -> None:
        identity = self._identity()
        for source, target in (("draft", "running"), ("needs_human", "running"), ("blocked", "complete")):
            with self.subTest(source=source, target=target):
                with self.assertRaises(GovernanceError) as caught:
                    transition_state(identity, source, target, actor="system", approval=self._approval(identity))
                self.assertEqual(caught.exception.code, "GOV-STATE-001")
                self.assertEqual(caught.exception.state, "blocked")

    def test_warning_completion_requires_explicit_warning_acceptance(self) -> None:
        identity = self._identity()
        with self.assertRaises(GovernanceError) as caught:
            transition_state(identity, "warning", "complete", actor="human", approval=self._approval(identity))
        self.assertEqual(caught.exception.code, "GOV-APPROVAL-001")
        record = transition_state(
            identity,
            "warning",
            "complete",
            actor="human",
            approval=self._approval(identity, ApprovalDecision.WARNING_ACCEPTED),
            occurred_at=STAMP,
        )
        self.assertEqual(record.to_state, "complete")

    def test_formal_write_gate_reports_all_ten_checks(self) -> None:
        identity = self._identity()
        decision = evaluate_formal_write(
            identity,
            state="complete",
            result_level="accepted_evidence",
            evidence_class="real_research_data",
            sources=(self._source(),),
            approvals=(self._approval(identity),),
            qc_status="passed",
            provenance_complete=True,
            manifest_valid=True,
            destination_allowed=True,
            append_only=True,
        )
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.state, "complete")
        self.assertEqual(len(decision.checks), 10)

    def test_formal_write_rejects_synthetic_data_and_non_append_write(self) -> None:
        identity = self._identity()
        common = {
            "identity": identity,
            "state": "complete",
            "sources": (self._source(),),
            "approvals": (self._approval(identity),),
            "qc_status": "passed",
            "provenance_complete": True,
            "manifest_valid": True,
            "destination_allowed": True,
            "append_only": True,
        }
        with self.assertRaises(GovernanceError) as synthetic:
            evaluate_formal_write(
                **common,
                result_level="synthetic_demo_only",
                evidence_class="synthetic_demo_data",
            )
        self.assertEqual(synthetic.exception.code, "GOV-RESULT-001")
        with self.assertRaises(GovernanceError) as overwrite:
            evaluate_formal_write(
                **{**common, "append_only": False},
                result_level="accepted_evidence",
                evidence_class="real_research_data",
            )
        self.assertEqual(overwrite.exception.code, "GOV-WRITE-001")

    def test_append_only_publication_succeeds_and_reuses_same_content(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stage, _, _ = self._sealed_stage(root, "SYN-T51-PACKAGE-001")
            destination = root / "SYN-T51-PACKAGE-001"
            first = publish_append_only(stage, destination)
            self.assertFalse(first.reused)
            self.assertEqual(verify_package(destination).status, "passed")

            replay, _, _ = self._sealed_stage(root, "SYN-T51-PACKAGE-001")
            second = publish_append_only(replay, destination)
            self.assertTrue(second.reused)
            self.assertFalse(replay.exists())
            self.assertEqual(first.manifest_digest, second.manifest_digest)

    def test_same_publication_identity_with_different_content_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stage, _, _ = self._sealed_stage(root, "SYN-T51-PACKAGE-001")
            destination = root / "SYN-T51-PACKAGE-001"
            publish_append_only(stage, destination)
            conflict, _, _ = self._sealed_stage(
                root,
                "SYN-T51-PACKAGE-001",
                content="different governed output",
            )
            with self.assertRaises(GovernanceError) as caught:
                publish_append_only(conflict, destination)
            self.assertEqual(caught.exception.code, "GOV-DUPLICATE-001")
            self.assertEqual((destination / "result.txt").read_text(encoding="utf-8"), "governed output")

    def test_tampered_artifact_becomes_invalidated_and_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stage, _, _ = self._sealed_stage(root, "SYN-T51-PACKAGE-001")
            destination = root / "SYN-T51-PACKAGE-001"
            publish_append_only(stage, destination)
            (destination / "result.txt").write_text("tampered", encoding="utf-8")
            verification = verify_package(destination)
            self.assertEqual(verification.status, "invalidated")
            self.assertTrue(any("mismatch" in problem for problem in verification.problems))

            replay, _, _ = self._sealed_stage(root, "SYN-T51-PACKAGE-001")
            with self.assertRaises(GovernanceError) as caught:
                publish_append_only(replay, destination)
            self.assertEqual(caught.exception.code, "GOV-INTEGRITY-001")
            self.assertEqual((destination / "result.txt").read_text(encoding="utf-8"), "tampered")

    def test_missing_marker_or_manifest_edit_becomes_invalidated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stage, _, _ = self._sealed_stage(root, "SYN-T51-PACKAGE-001")
            (stage / "COMPLETE").unlink()
            self.assertEqual(verify_package(stage).status, "invalidated")

            seal_manifest = json.loads((stage / "governance_manifest.json").read_text(encoding="utf-8"))
            seal_manifest["state"] = "draft"
            (stage / "governance_manifest.json").write_text(
                json.dumps(seal_manifest, ensure_ascii=False),
                encoding="utf-8",
            )
            result = verify_package(stage)
            self.assertEqual(result.status, "invalidated")
            self.assertTrue(any("fingerprint" in problem or "incompatible" in problem for problem in result.problems))


if __name__ == "__main__":
    unittest.main()
