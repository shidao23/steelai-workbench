import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[1]


class StreamlitPageTests(unittest.TestCase):
    def test_consolidated_pages_render_without_exception(self):
        files = [ROOT / "app.py", *sorted((ROOT / "pages").glob("*.py"))]
        self.assertEqual(len(files), 6)
        failures = []
        for path in files:
            app = AppTest.from_file(str(path), default_timeout=15).run()
            if app.exception:
                failures.append(f"{path.name}: {app.exception[0].message}")
        self.assertFalse(failures, "\n".join(failures))

    def test_all_embedded_feature_views_render_without_exception(self):
        files = sorted((ROOT / "steelai" / "views").glob("*_view.py"))
        self.assertEqual(len(files), 11)
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


if __name__ == "__main__":
    unittest.main()
