import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from steelai.research_agent import (
    AgentStatus,
    TOOL_DEFINITIONS,
    agent_status,
    execute_readonly_tool,
    run_research_agent,
)


class FakeResponses:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


class FakeChatCompletions:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


class ResearchAgentTests(unittest.TestCase):
    def test_status_is_offline_without_key(self):
        settings = {
            "ai": {
                "enabled": True,
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "api_key_env": "DEEPSEEK_API_KEY",
                "base_url": "https://api.deepseek.com/beta",
            }
        }
        with patch("steelai.research_agent.load_settings", return_value=settings), patch.dict(
            os.environ, {"DEEPSEEK_API_KEY": ""}
        ):
            status = agent_status()
        self.assertFalse(status.ready)
        self.assertEqual(status.state, "offline_missing_key")
        self.assertEqual(status.provider, "deepseek")
        self.assertEqual(status.model, "deepseek-v4-flash")

    def test_tool_schemas_are_strict_and_closed(self):
        names = {item["name"] for item in TOOL_DEFINITIONS}
        self.assertEqual(
            names,
            {
                "list_samples",
                "get_sample_bundle",
                "compare_samples",
                "calculate_physics_card",
                "get_ebsd_summary",
                "get_autodimple_summary",
                "get_evidence_validation_summary",
            },
        )
        for item in TOOL_DEFINITIONS:
            self.assertTrue(item["strict"])
            self.assertFalse(item["parameters"]["additionalProperties"])

    def test_readonly_sample_tool_uses_processed_tables(self):
        result = execute_readonly_tool("list_samples", {})
        self.assertEqual(result["count"], 2)
        self.assertEqual({row["sample_id"] for row in result["samples"]}, {"B-DQ", "R-DQ"})

    def test_unknown_sample_is_rejected(self):
        with self.assertRaises(ValueError):
            execute_readonly_tool("get_sample_bundle", {"sample_id": "UNKNOWN"})

    def test_physics_tool_reports_engine_and_model_count(self):
        result = execute_readonly_tool("calculate_physics_card", {"sample_id": "B-DQ"})
        self.assertEqual(result["engine"], "SteelAI Physics Model Registry v1.0")
        self.assertEqual(result["model_count"], len(result["results"]))
        self.assertGreaterEqual(result["model_count"], 6)
        self.assertEqual(result["result_type"], "empirical_model_estimates_not_experimental_truth")

    def test_validation_tool_never_exposes_source_locators(self):
        result = execute_readonly_tool("get_evidence_validation_summary", {})
        serialized = json.dumps(result, ensure_ascii=False).lower()
        self.assertNotIn("source_locator", serialized)
        self.assertNotIn(".ctf", serialized)
        self.assertNotIn(".tif", serialized)
        self.assertFalse(result["causal_inference_ready"])

    def test_agent_executes_tool_and_returns_trace(self):
        function_call = SimpleNamespace(
            type="function_call",
            name="list_samples",
            arguments="{}",
            call_id="call-1",
        )
        first = SimpleNamespace(id="resp-1", output=[function_call], output_text="")
        second = SimpleNamespace(
            id="resp-2",
            output=[],
            output_text="## 已确认事实\n- list_samples显示当前有2个样品。",
        )
        responses = FakeResponses([first, second])
        client = SimpleNamespace(responses=responses)
        status = AgentStatus(
            "online_ready", True, True, True, "gpt-5.6-luna", "low", 6, 4, "ok", "2.53.0"
        )

        result = run_research_agent("当前有多少样品？", client=client, status=status)

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.response_id, "resp-2")
        self.assertEqual(result.tool_trace[0]["tool"], "list_samples")
        self.assertEqual(len(responses.calls), 2)
        second_input = responses.calls[1]["input"]
        tool_outputs = [item for item in second_input if isinstance(item, dict) and item.get("type") == "function_call_output"]
        self.assertEqual(len(tool_outputs), 1)
        self.assertEqual(json.loads(tool_outputs[0]["output"])["count"], 2)

    def test_deepseek_adapter_executes_strict_chat_tool_loop(self):
        tool_call = SimpleNamespace(
            id="call-ds-1",
            function=SimpleNamespace(name="list_samples", arguments="{}"),
        )
        first_message = SimpleNamespace(content=None, tool_calls=[tool_call])
        second_message = SimpleNamespace(
            content="## 已确认事实\n- list_samples显示当前有2个样品。",
            tool_calls=None,
        )
        first = SimpleNamespace(
            id="ds-resp-1",
            choices=[SimpleNamespace(message=first_message)],
            usage=SimpleNamespace(prompt_tokens=20, completion_tokens=5, total_tokens=25),
        )
        second = SimpleNamespace(
            id="ds-resp-2",
            choices=[SimpleNamespace(message=second_message)],
            usage=SimpleNamespace(prompt_tokens=30, completion_tokens=10, total_tokens=40),
        )
        completions = FakeChatCompletions([first, second])
        client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        status = AgentStatus(
            state="online_ready",
            enabled=True,
            api_key_present=True,
            package_present=True,
            model="deepseek-v4-flash",
            reasoning_effort="low",
            max_tool_calls=6,
            max_rounds=4,
            message="ok",
            package_version="2.53.0",
            provider="deepseek",
            api_key_env="DEEPSEEK_API_KEY",
            base_url="https://api.deepseek.com/beta",
        )

        result = run_research_agent("当前有多少样品？", client=client, status=status)

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.response_id, "ds-resp-2")
        self.assertEqual(result.usage["total_tokens"], 65)
        self.assertEqual(result.tool_trace[0]["tool"], "list_samples")
        self.assertEqual(len(completions.calls), 2)
        self.assertEqual(completions.calls[0]["extra_body"], {"thinking": {"type": "disabled"}})
        strict_functions = [item["function"] for item in completions.calls[0]["tools"]]
        self.assertTrue(all(item["strict"] for item in strict_functions))
        tool_messages = [item for item in completions.calls[1]["messages"] if isinstance(item, dict) and item.get("role") == "tool"]
        self.assertEqual(len(tool_messages), 1)
        self.assertEqual(json.loads(tool_messages[0]["content"])["count"], 2)


if __name__ == "__main__":
    unittest.main()
