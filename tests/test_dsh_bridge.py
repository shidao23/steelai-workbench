import json
import unittest
from unittest.mock import patch

from steelai.dsh_bridge import (
    ALLOWED_TOOLS,
    DSHBridgeError,
    bridge_status,
    execute_dsh_tool,
    tool_catalog,
)


class DSHBridgeTests(unittest.TestCase):
    def test_catalog_matches_audited_research_tools(self):
        self.assertEqual({item["name"] for item in tool_catalog()}, ALLOWED_TOOLS)
        self.assertEqual(bridge_status()["tool_count"], 7)
        self.assertFalse(bridge_status()["writes_allowed"])

    def test_unknown_tool_is_blocked(self):
        with self.assertRaises(DSHBridgeError):
            execute_dsh_tool("read_file", {"path": "anything"})

    def test_extra_and_missing_arguments_are_blocked(self):
        with self.assertRaises(DSHBridgeError):
            execute_dsh_tool("list_samples", {"path": "anything"})
        with self.assertRaises(DSHBridgeError):
            execute_dsh_tool("get_sample_bundle", {})

    def test_invalid_enum_is_blocked(self):
        with self.assertRaises(DSHBridgeError):
            execute_dsh_tool("get_ebsd_summary", {"scale": "mixed"})

    def test_structured_sample_result_has_no_raw_locator(self):
        result = execute_dsh_tool("get_sample_bundle", {"sample_id": "B-DQ"})
        serialized = json.dumps(result, ensure_ascii=False).lower()
        self.assertNotRegex(serialized, r"[a-z]:[\\/]")
        self.assertNotIn(".ctf", serialized)
        self.assertNotIn(".tif", serialized)
        self.assertNotIn("source_locator", serialized)

    def test_egress_guard_blocks_path_even_if_upstream_regresses(self):
        with patch(
            "steelai.dsh_bridge.execute_readonly_tool",
            return_value={"leak": r"D:\private\raw_image.tif"},
        ):
            with self.assertRaises(DSHBridgeError):
                execute_dsh_tool("list_samples")

    def test_comparison_remains_evidence_bounded(self):
        result = execute_dsh_tool(
            "compare_samples",
            {"control_id": "B-DQ", "comparison_id": "R-DQ"},
        )
        self.assertEqual(result["evidence"]["method"], "offline_rules")
        self.assertNotIn("narrative", result)


if __name__ == "__main__":
    unittest.main()
