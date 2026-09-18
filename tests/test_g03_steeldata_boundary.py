from __future__ import annotations

import unittest

from steelai.steeldata_bridge import _steeldata_subprocess_env


class SteelDataBoundaryTests(unittest.TestCase):
    def test_deterministic_child_receives_no_model_cloud_or_proxy_credentials(self):
        source = {
            "PATH": r"C:\Windows\System32",
            "SystemRoot": r"C:\Windows",
            "PROJECT_MODE": "local",
            "PYTHONPATH": r"D:\untrusted",
            "DEEPSEEK_API_KEY": "secret",
            "ANTHROPIC_API_KEY": "secret",
            "OPENROUTER_API_KEY": "secret",
            "GITHUB_TOKEN": "secret",
            "SERVICE_AUTH_TOKEN": "secret",
            "AWS_SECRET_ACCESS_KEY": "secret",
            "GOOGLE_APPLICATION_CREDENTIALS": r"D:\private\service.json",
            "HTTPS_PROXY": "http://credential@proxy.invalid",
        }

        env = _steeldata_subprocess_env(source)

        self.assertEqual(env["PATH"], source["PATH"])
        self.assertEqual(env["SystemRoot"], source["SystemRoot"])
        self.assertEqual(env["PROJECT_MODE"], "local")
        self.assertEqual(env["PYTHONUTF8"], "1")
        for key in source.keys() - {"PATH", "SystemRoot", "PROJECT_MODE"}:
            self.assertNotIn(key, env)


if __name__ == "__main__":
    unittest.main()
