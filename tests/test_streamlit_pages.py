import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[1]


class StreamlitPageTests(unittest.TestCase):
    def test_consolidated_pages_render_without_exception(self):
        files = [ROOT / "app.py", *sorted((ROOT / "pages").glob("*.py"))]
        self.assertEqual(len(files), 7)
        failures = []
        for path in files:
            app = AppTest.from_file(str(path), default_timeout=15).run()
            if app.exception:
                failures.append(f"{path.name}: {app.exception[0].message}")
        self.assertFalse(failures, "\n".join(failures))

    def test_all_embedded_feature_views_render_without_exception(self):
        files = sorted((ROOT / "steelai" / "views").glob("*_view.py"))
        self.assertEqual(len(files), 19)
        failures = []
        for path in files:
            app = AppTest.from_file(str(path), default_timeout=15).run()
            if app.exception:
                failures.append(f"{path.name}: {app.exception[0].message}")
        self.assertFalse(failures, "\n".join(failures))

    def test_data_quality_panel_renders_without_exception(self):
        path = ROOT / "steelai" / "views" / "data_quality_panel.py"
        app = AppTest.from_file(str(path), default_timeout=15).run()
        messages = [item.message for item in app.exception]
        self.assertFalse(messages, "\n".join(messages))

    def test_research_session_view_exposes_daily_workflow_creation(self):
        path = ROOT / "steelai" / "views" / "research_session_view.py"
        app = AppTest.from_file(str(path), default_timeout=15).run()
        self.assertFalse(app.exception)
        labels = {item.label for item in app.text_input}
        self.assertIn("会话标题", labels)
        self.assertTrue(any(item.label == "创建并设为当前会话" for item in app.button))

    def test_run_center_exposes_status_filters_and_next_step(self):
        path = ROOT / "steelai" / "views" / "run_center_view.py"
        app = AppTest.from_file(str(path), default_timeout=15).run()
        self.assertFalse(app.exception)
        labels = {item.label for item in app.selectbox}
        self.assertIn("查看范围", labels)
        metric_labels = {item.label for item in app.metric}
        self.assertIn("待人工确认", metric_labels)
        self.assertIn("完整性失效", metric_labels)
        self.assertIn("已验收成果", metric_labels)


if __name__ == "__main__":
    unittest.main()
