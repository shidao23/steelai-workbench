from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from steelai.data_intake import validate_intake_csv
from steelai.data_intake_governance import commit_standard_intake_governed
from steelai.governance import digest_value, load_verified_manifest
from steelai.research_protocol import (
    A2ATaskEnvelope,
    GovernedResearchToolLayer,
    ProtocolEvidenceReference,
    make_tool_request,
)
from steelai.workflow_identity import WorkflowIdentity, validate_workflow_identity_contract


ROOT = Path(__file__).resolve().parents[1]
STAMP = "2026-09-15T02:00:00+00:00"


class WorkflowIdentityTests(unittest.TestCase):
    def _intake_fixture(self, root: Path) -> tuple[dict, Path, Path]:
        root.mkdir(parents=True, exist_ok=True)
        contract = json.loads(
            (ROOT / "config" / "research_data_contract_v1.0.json").read_text(encoding="utf-8")
        )
        policy = json.loads(
            (ROOT / "config" / "research_id_policy_v1.0.json").read_text(encoding="utf-8")
        )
        contract_path = root / "contract.json"
        policy_path = root / "policy.json"
        contract_path.write_text(json.dumps(contract), encoding="utf-8")
        policy_path.write_text(json.dumps(policy), encoding="utf-8")
        processed = root / "data" / "processed"
        processed.mkdir(parents=True)
        (processed / "samples.csv").write_text(
            "sample_id,steel,condition,batch,data_status\n"
            "B-DQ,B,DQ,DQ_6PASS_B,verified\n",
            encoding="utf-8",
        )
        report = validate_intake_csv(
            "process_steps",
            (
                "sample_id,step_id,step_type,sequence,source_status,start_temp_c,end_temp_c\n"
                "B-DQ,B-DQ-G01,rolling,1,verified_from_source,1060,1010\n"
            ).encode("utf-8"),
            contract_path=contract_path,
            project_root=root,
            id_policy_path=policy_path,
        )
        return report, contract_path, policy_path

    def test_contract_and_platform_aliases_are_frozen(self) -> None:
        self.assertEqual(validate_workflow_identity_contract()["status"], "passed")
        identity = WorkflowIdentity(
            "request_g01shared",
            "task_g01shared",
            "run_g01shared",
            2,
        )
        self.assertEqual(
            identity.to_platform_fields(),
            {
                "requestId": "request_g01shared",
                "taskId": "task_g01shared",
                "runId": "run_g01shared",
                "taskRevision": 2,
            },
        )

    def test_invalid_or_path_like_identifiers_fail_closed(self) -> None:
        for field_value in ("REQ-G01", "request_../escape", "request_AAAAAA"):
            with self.assertRaises(ValueError):
                WorkflowIdentity(field_value, "task_g01shared", None, 1)

    def test_one_request_and_task_correlate_mcp_receipt_and_intake_package(self) -> None:
        shared = WorkflowIdentity.create(
            request_id="request_g01shared",
            task_id="task_g01shared",
            seed={"fixture": "G01"},
        )
        evidence = ProtocolEvidenceReference(
            "SYNTH-G01-EVIDENCE",
            1,
            digest_value({"fixture": "G01"}),
            "synthetic_demo_data",
        )
        task = A2ATaskEnvelope.create(
            "planner",
            "data_steward",
            (evidence,),
            status="accepted",
            created_at=STAMP,
            request_id=shared.request_id,
            task_id=shared.task_id,
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            protocol_root = root / "protocol"
            layer = GovernedResearchToolLayer(
                output_root=protocol_root,
                backend=lambda _name, _arguments: {"samples": [], "count": 0},
            )
            response = layer.execute(
                "query_samples",
                make_tool_request(
                    shared.request_id,
                    "IDEM-G01-SHARED",
                    task,
                    "registry-g01",
                    {},
                ),
            )
            receipt = json.loads(
                (protocol_root / response["tool_call_id"] / "tool_receipt.json").read_text(
                    encoding="utf-8"
                )
            )

            report, contract_path, policy_path = self._intake_fixture(root / "intake-project")
            result = commit_standard_intake_governed(
                report,
                reviewer_id="g01-human-reviewer",
                rationale="Checked the G01 identity propagation fixture.",
                confirmed=True,
                project_root=root / "intake-project",
                contract_path=contract_path,
                id_policy_path=policy_path,
                output_root=root / "governed-intake",
                decided_at=STAMP,
                workflow_identity=shared,
            )
            package = Path(result["governance_package"])
            record = json.loads(
                (package / "governance_record.json").read_text(encoding="utf-8")
            )
            manifest = load_verified_manifest(package)

        for payload in (response, receipt, result):
            self.assertEqual(payload["request_id"], shared.request_id)
            self.assertEqual(payload["task_id"], shared.task_id)
            self.assertEqual(payload["task_revision"], 1)
            self.assertTrue(payload["run_id"].startswith("run_"))
        self.assertNotEqual(response["run_id"], result["run_id"])
        self.assertEqual(record["workflow_identity"]["run_id"], result["run_id"])
        self.assertEqual(manifest.metadata["workflow_identity"], record["workflow_identity"])


if __name__ == "__main__":
    unittest.main()
