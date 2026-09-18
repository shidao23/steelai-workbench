"""G07 Streamlit state projection tests; fixtures are synthetic and temporary."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from steelai.steeldata_bridge import SteelDataClient
from steelai.views.steeldata_panel import steeldata_state_presentation
from tests.test_steeldata_bridge import result_fixture


ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "steelai/views/data_quality_panel.py"


class StateProjectionTests(unittest.TestCase):
    def test_five_states_have_distinct_titles_and_safe_next_actions(self) -> None:
        states = ["completed", "needs_human", "blocked", "invalidated", "offline"]
        rendered = [steeldata_state_presentation(state) for state in states]
        self.assertEqual({item["state"] for item in rendered}, set(states))
        self.assertEqual(len({item["title"] for item in rendered}), 5)
        self.assertTrue(all(item["next_action"] for item in rendered))
        self.assertEqual(steeldata_state_presentation("completed")["severity"], "success")
        self.assertEqual(steeldata_state_presentation("needs_human")["severity"], "warning")
        self.assertEqual(steeldata_state_presentation("blocked")["severity"], "error")
        self.assertEqual(steeldata_state_presentation("invalidated")["severity"], "error")
        self.assertEqual(steeldata_state_presentation("offline")["severity"], "warning")

    def test_unknown_state_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported SteelData UI state"):
            steeldata_state_presentation("finished")


class StreamlitStateTests(unittest.TestCase):
    @staticmethod
    def _messages(elements) -> list[str]:
        return [str(item.value) for item in elements]

    def test_offline_is_visible_without_fallback_execution(self) -> None:
        from streamlit.testing.v1 import AppTest

        with patch.object(
            SteelDataClient,
            "availability",
            return_value={"ready": False, "project": "test", "reason": "runtime_probe_failed"},
        ), patch.object(SteelDataClient, "_call", side_effect=AssertionError("must stay offline")):
            app = AppTest.from_file(str(PANEL), default_timeout=20).run()
        self.assertFalse(app.exception, str(app.exception))
        self.assertTrue(any("本地服务离线" in value for value in self._messages(app.warning)))
        self.assertFalse(any("已完成" in value for value in self._messages(app.success)))

    def test_remembered_completed_state_is_rendered_as_success(self) -> None:
        from streamlit.testing.v1 import AppTest

        with patch.object(
            SteelDataClient,
            "availability",
            return_value={"ready": True, "project": "test", "reason": "ready"},
        ):
            app = AppTest.from_file(str(PANEL), default_timeout=20).run()
            app.session_state["sd_import_ui_state"] = steeldata_state_presentation(
                "completed", "治理审计编号 test-audit。"
            )
            app.run()
        self.assertFalse(app.exception, str(app.exception))
        self.assertTrue(any("已完成" in value for value in self._messages(app.success)))

    def test_valid_package_is_needs_human_not_completed(self) -> None:
        from streamlit.testing.v1 import AppTest

        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp) / "run"
            result_fixture(run)
            app = AppTest.from_file(str(PANEL), default_timeout=20).run()
            app.text_input(key="sd_run_path").set_value(str(run)).run()
            app.button(key="sd_load").click().run()
        self.assertFalse(app.exception, str(app.exception))
        self.assertTrue(any("待人工确认" in value for value in self._messages(app.warning)))
        self.assertFalse(any("已完成" in value for value in self._messages(app.success)))

    def test_blocked_package_never_renders_completed(self) -> None:
        from streamlit.testing.v1 import AppTest

        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp) / "run"
            result_fixture(run, synthetic=True)
            app = AppTest.from_file(str(PANEL), default_timeout=20).run()
            app.text_input(key="sd_run_path").set_value(str(run)).run()
            app.button(key="sd_load").click().run()
        self.assertFalse(app.exception, str(app.exception))
        self.assertTrue(any("已阻断" in value for value in self._messages(app.error)))
        self.assertFalse(any("已完成" in value for value in self._messages(app.success)))

    def test_tampered_package_is_visibly_invalidated(self) -> None:
        from streamlit.testing.v1 import AppTest

        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp) / "run"
            result_fixture(run)
            (run / "report.html").write_text("tampered", encoding="utf-8")
            app = AppTest.from_file(str(PANEL), default_timeout=20).run()
            app.text_input(key="sd_run_path").set_value(str(run)).run()
            app.button(key="sd_load").click().run()
        self.assertFalse(app.exception, str(app.exception))
        self.assertTrue(any("完整性失效" in value for value in self._messages(app.error)))
        self.assertFalse(any("已完成" in value for value in self._messages(app.success)))


if __name__ == "__main__":
    unittest.main()
