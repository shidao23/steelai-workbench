from __future__ import annotations

import json
import unittest

from steelai.intake_request import (
    folder_reference_selection,
    register_intake_request,
    uploaded_file_selection,
    validate_intake_request_contract,
    validate_intake_request_evidence,
)


class Upload:
    def __init__(self, name: str, payload: bytes):
        self.name = name
        self.size = len(payload)
        self._payload = payload

    def getvalue(self) -> bytes:
        return self._payload


class IntakeRequestTests(unittest.TestCase):
    def test_contract_is_valid(self):
        self.assertEqual(validate_intake_request_contract()["status"], "passed")

    def test_uploaded_selection_creates_metadata_only_unexecuted_event(self):
        session: dict = {}
        events: list[dict] = []

        def recorder(event_type, title, summary, evidence=None, tags=None):
            event = {
                "event_id": "event_test",
                "event_type": event_type,
                "title": title,
                "summary": summary,
                "evidence": evidence,
                "tags": tags,
            }
            events.append(event)
            return event

        source_name = "secret-specimen-B-DQ.csv"
        source_bytes = b"private-raw-measurement-1088"
        registration = register_intake_request(
            session,
            route="external_file",
            selection=uploaded_file_selection([Upload(source_name, source_bytes)]),
            event_recorder=recorder,
        )

        self.assertTrue(registration.created)
        self.assertIsNone(registration.identity.run_id)
        self.assertEqual(len(events), 1)
        evidence = events[0]["evidence"]
        self.assertEqual(events[0]["event_type"], "intake_request")
        self.assertFalse(evidence["execution_started"])
        self.assertFalse(evidence["research_data_written"])
        self.assertFalse(evidence["raw_content_persisted"])
        self.assertFalse(evidence["absolute_path_persisted"])
        serialized = json.dumps(events[0], ensure_ascii=False)
        self.assertNotIn(source_name, serialized)
        self.assertNotIn(source_bytes.decode(), serialized)

    def test_sensitive_or_oversized_extension_is_not_persisted(self):
        selection = uploaded_file_selection([
            Upload("sample.secret-specimen-identity", b"payload"),
        ])
        self.assertEqual(selection.extensions, ())

    def test_runtime_guard_rejects_extra_path_field(self):
        events: list[dict] = []

        def recorder(*args, **kwargs):
            events.append(kwargs["evidence"])
            return {"event_id": "event_guard", "evidence": kwargs["evidence"]}

        register_intake_request(
            {}, route="external_file",
            selection=uploaded_file_selection([Upload("safe.csv", b"payload")]),
            event_recorder=recorder,
        )
        unsafe = dict(events[0])
        unsafe["absolute_path"] = r"D:\private\safe.csv"
        with self.assertRaises(ValueError):
            validate_intake_request_evidence(unsafe)

    def test_same_selection_reuses_session_identity_and_deduplicates_event(self):
        session: dict = {}
        events: list[dict] = []

        def recorder(*args, **kwargs):
            event = {"event_id": f"event_{len(events) + 1}", "evidence": kwargs["evidence"]}
            events.append(event)
            return event

        selection = uploaded_file_selection([Upload("curve.A75", b"same bytes")])
        first = register_intake_request(
            session, route="thermal_simulation_files", selection=selection,
            event_recorder=recorder,
        )
        second = register_intake_request(
            session, route="thermal_simulation_files", selection=selection,
            event_recorder=recorder,
        )

        self.assertTrue(first.created)
        self.assertFalse(second.created)
        self.assertEqual(first.identity, second.identity)
        self.assertEqual(len(events), 1)

    def test_changed_content_creates_new_request_and_task(self):
        session: dict = {}
        events: list[dict] = []

        def recorder(*args, **kwargs):
            event = {"event_id": f"event_{len(events) + 1}", "evidence": kwargs["evidence"]}
            events.append(event)
            return event

        first = register_intake_request(
            session,
            route="steeldata_files",
            selection=uploaded_file_selection([Upload("result.csv", b"version one")]),
            event_recorder=recorder,
        )
        second = register_intake_request(
            session,
            route="steeldata_files",
            selection=uploaded_file_selection([Upload("result.csv", b"version two")]),
            event_recorder=recorder,
        )

        self.assertNotEqual(first.identity.request_id, second.identity.request_id)
        self.assertNotEqual(first.identity.task_id, second.identity.task_id)
        self.assertEqual(len(events), 2)

    def test_folder_reference_is_not_resolved_scanned_or_persisted(self):
        session: dict = {}
        events: list[dict] = []
        source_path = r"D:\private-lab\double-hit\batch-17"

        def recorder(*args, **kwargs):
            event = {"event_id": "event_folder", "evidence": kwargs["evidence"]}
            events.append(event)
            return event

        registration = register_intake_request(
            session,
            route="steeldata_folder",
            selection=folder_reference_selection(source_path),
            event_recorder=recorder,
        )

        selection = events[0]["evidence"]["selection"]
        self.assertTrue(registration.created)
        self.assertEqual(selection["reference_scope"], "reference_only_not_scanned")
        self.assertIsNone(selection["item_count"])
        self.assertIsNone(selection["total_size_bytes"])
        self.assertNotIn(source_path, json.dumps(events[0], ensure_ascii=False))

    def test_target_table_separates_standard_csv_tasks(self):
        session: dict = {}
        events: list[dict] = []

        def recorder(*args, **kwargs):
            event = {"event_id": f"event_{len(events) + 1}", "evidence": kwargs["evidence"]}
            events.append(event)
            return event

        selection = uploaded_file_selection([Upload("template.csv", b"same")])
        first = register_intake_request(
            session, route="standard_csv", selection=selection,
            target_table="process_steps", event_recorder=recorder,
        )
        second = register_intake_request(
            session, route="standard_csv", selection=selection,
            target_table="property_observations", event_recorder=recorder,
        )

        self.assertNotEqual(first.identity.task_id, second.identity.task_id)
        self.assertEqual([event["evidence"]["target_table"] for event in events], [
            "process_steps", "property_observations",
        ])


if __name__ == "__main__":
    unittest.main()
