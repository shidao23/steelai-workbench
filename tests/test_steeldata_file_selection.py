"""Browser selection validation, temporary staging, and UI gating; synthetic only."""
import json
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from steelai.steeldata_bridge import SteelDataClient, _digest, validate_selected_files


ROOT = Path(__file__).resolve().parents[1]


def approval_bytes(kind="human"):
    profile = {"profile_id": "synthetic-test", "domain": "tensile"}
    return json.dumps({"kind": kind, "profile": profile, "profile_sha256": _digest(profile)}).encode()


class FileSelectionTests(unittest.TestCase):
    def setUp(self):
        self.data = [("合成 拉伸.csv", b"synthetic,test\n1,2\n"), ("SYN-second.tsv", b"a\tb\n1\t2\n")]
        self.approvals = [("test-approved.json", approval_bytes())]

    def test_selection_is_readonly_before_run(self):
        with patch("steelai.steeldata_bridge.tempfile.TemporaryDirectory") as temporary:
            validate_selected_files(self.data, self.approvals)
        temporary.assert_not_called()

    def test_selected_bytes_and_names_are_preserved_and_temp_is_cleaned(self):
        roots = []
        def fake_run(input_dir, approval_paths):
            root = Path(input_dir)
            roots.append(root.parent)
            self.assertEqual({p.name for p in root.iterdir()}, {n for n, _ in self.data})
            for name, content in self.data:
                self.assertEqual((root / name).read_bytes(), content)
            self.assertEqual(Path(approval_paths[0]).read_bytes(), self.approvals[0][1])
            self.assertNotEqual(Path(approval_paths[0]).parent, root)
            return {"run_dir": "result-outside-temporary"}
        client = SteelDataClient()
        with patch.object(client, "run", side_effect=fake_run):
            result = client.run_selected(self.data, self.approvals)
        self.assertEqual(result["run_dir"], "result-outside-temporary")
        self.assertFalse(roots[0].exists())

    def test_failure_also_cleans_temporary_copies(self):
        roots = []
        def fail(input_dir, approvals):
            roots.append(Path(input_dir).parent)
            raise ValueError("simulated processing error")
        client = SteelDataClient()
        with patch.object(client, "run", side_effect=fail):
            with self.assertRaises(ValueError):
                client.run_selected(self.data, self.approvals)
        self.assertFalse(roots[0].exists())

    def test_unsafe_names_unsupported_extensions_and_empty_data_are_rejected(self):
        for name in ["../x.csv", "D:\\x.csv", "dir/x.csv", "CON.csv", "LPT1.tsv", "x.csv.",
                     "x.csv ", "x.xls", "bad\x00.csv", "x.csv:stream", "x.exe"]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate_selected_files([(name, b"test")], self.approvals)
        with self.assertRaises(ValueError):
            validate_selected_files([("empty.csv", b"")], self.approvals)

    def test_duplicate_case_insensitive_names_and_count_limits_reject_before_writes(self):
        with self.assertRaises(ValueError):
            validate_selected_files([("one.csv", b"a"), ("ONE.CSV", b"b")], self.approvals)
        with self.assertRaises(ValueError):
            validate_selected_files(self.data, [("a.json", approval_bytes()), ("A.JSON", approval_bytes())])
        with self.assertRaises(ValueError):
            validate_selected_files([("a.csv", b"a")] * 1001, self.approvals)
        with self.assertRaises(ValueError):
            validate_selected_files(self.data, self.approvals * 41)

    def test_size_limits(self):
        with self.assertRaises(ValueError):
            validate_selected_files([("large.csv", b"x" * (20 * 1024 * 1024 + 1))], self.approvals)
        block = b"x" * (20 * 1024 * 1024)
        with self.assertRaisesRegex(ValueError, "100 MiB"):
            validate_selected_files([(f"{i}.csv", block) for i in range(6)], self.approvals)
        with self.assertRaises(ValueError):
            validate_selected_files(self.data, [("large.json", b"x" * (2 * 1024 * 1024 + 1))])

    def test_missing_unapproved_or_tampered_approval_is_rejected(self):
        for data, approvals in [([], self.approvals), (self.data, []),
            (self.data, [("demo.json", approval_bytes("bundled_demo"))]),
            (self.data, [("plain.json", b'{"profile_id":"not-approved"}')]),
            (self.data, [("broken.json", b"not-json")])]:
            with self.subTest(approvals=approvals), self.assertRaises(ValueError):
                validate_selected_files(data, approvals)
        tampered = json.loads(approval_bytes())
        tampered["profile"]["domain"] = "composition"
        with self.assertRaises(ValueError):
            validate_selected_files(self.data, [("tampered.json", json.dumps(tampered).encode())])


class Upload:
    def __init__(self, name, data):
        self.name, self.data, self.size = name, data, len(data)

    def getvalue(self):
        return self.data


class SelectionPanelTests(unittest.TestCase):
    def test_picker_and_manual_path_are_both_available_and_no_auto_execution(self):
        from streamlit.testing.v1 import AppTest
        with patch.object(SteelDataClient, "_call", side_effect=AssertionError("No automatic execution")):
            app = AppTest.from_file(str(ROOT / "steelai/views/data_quality_panel.py"), default_timeout=20).run()
            app.radio(key="sd_mode").set_value("运行原始数据批次").run()
            self.assertFalse(app.exception, str(app.exception))
            labels = {item.label for item in app.get("file_uploader")}
            self.assertIn("选取实验数据文件", labels)
            self.assertIn("选取已人工批准的映射 JSON", labels)
            self.assertTrue(app.button(key="sd_run").disabled)
            app.checkbox(key="sd_snapshot_agree").check().run()
            app.radio(key="sd_selection_mode").set_value("填写文件夹路径").run()
            self.assertFalse(app.exception, str(app.exception))
            self.assertFalse(app.checkbox(key="sd_snapshot_agree").value)
            self.assertTrue(any(item.key == "sd_input" for item in app.text_input))

    def test_selected_files_need_confirmation_and_result_uses_existing_qc_gate(self):
        from streamlit.testing.v1 import AppTest
        from test_steeldata_bridge import result_fixture
        data = Upload("SYN-test.csv", b"synthetic,only\n")
        approval = Upload("test.json", approval_bytes())
        def picker(label, **kwargs):
            return {"选取实验数据文件": [data], "选取已人工批准的映射 JSON": [approval]}.get(label)
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp) / "run"
            result_fixture(run, synthetic=True)
            with patch("streamlit.file_uploader", side_effect=picker), patch.object(
                SteelDataClient, "availability", return_value={"ready": True, "project": "test"}), patch.object(
                SteelDataClient, "run_selected", return_value={"run_dir": str(run)}) as execute:
                app = AppTest.from_file(str(ROOT / "steelai/views/data_quality_panel.py"), default_timeout=20).run()
                app.radio(key="sd_mode").set_value("运行原始数据批次").run()
                self.assertFalse(app.exception, str(app.exception))
                self.assertTrue(app.button(key="sd_run").disabled)
                execute.assert_not_called()
                app.checkbox(key="sd_snapshot_agree").check().run()
                self.assertFalse(app.button(key="sd_run").disabled)
                app.button(key="sd_run").click().run()
                self.assertFalse(app.exception, str(app.exception))
                execute.assert_called_once_with([(data.name, data.data)], [(approval.name, approval.data)])
                self.assertTrue(app.button(key="sd_blocked_commit").disabled)


if __name__ == "__main__":
    unittest.main()
