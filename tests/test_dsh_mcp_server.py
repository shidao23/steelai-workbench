import os
import sys
import unittest
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


ROOT = Path(__file__).resolve().parents[1]


class DSHMCPServerTests(unittest.IsolatedAsyncioTestCase):
    async def test_stdio_handshake_lists_and_calls_readonly_tools(self):
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "steelai.dsh_mcp_server"],
            cwd=str(ROOT),
            env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
        )
        async with stdio_client(parameters) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                listed = await session.list_tools()
                names = {tool.name for tool in listed.tools}
                self.assertEqual(
                    names,
                    {
                        "get_bridge_status",
                        "list_samples",
                        "get_sample_bundle",
                        "compare_samples",
                        "calculate_physics_card",
                        "get_ebsd_summary",
                        "get_autodimple_summary",
                        "get_evidence_validation_summary",
                    },
                )

                status = await session.call_tool("get_bridge_status", {})
                self.assertFalse(status.isError)
                serialized = status.model_dump_json().lower()
                self.assertIn("read_only_structured_data", serialized)
                self.assertIn('"writes_allowed":false', serialized)


if __name__ == "__main__":
    unittest.main()
