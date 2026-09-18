"""T76 regressions for the Windows launcher's loopback instance detection.

The launcher must recognise an already running SteelAI instance even when the
user has ``HTTP_PROXY``/``HTTPS_PROXY`` configured without a localhost
exception.  Two things are checked here:

* the real ``Start_SteelAI.bat`` no longer starts Streamlit while the health
  endpoint answers, and
* the real ``scripts/check_local_streamlit_health.ps1`` probe used by that
  launcher still reports "not running" when nothing answers.

Both run against temporary loopback servers, so no test can occupy the default
8501 port or leave a process behind.
"""

import http.server
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "Start_SteelAI.bat"
HEALTH_PROBE = ROOT / "scripts" / "check_local_streamlit_health.ps1"

# A syntactically valid but unreachable local proxy.  Any request sent to it
# fails, so a health probe that honours the proxy cannot report HTTP 200.
DEAD_PROXY = "http://127.0.0.1:9"

# The exact command line a launcher must not reach while an instance is running.
STREAMLIT_COMMAND = (
    '".venv\\Scripts\\python.exe" -m streamlit run app.py '
    "--server.address=127.0.0.1 --server.port=%STEELAI_PORT% --server.headless=false"
)
START_MARKER = "STEELAI_START_ATTEMPTED"

POWERSHELL = shutil.which("powershell.exe")


@unittest.skipUnless(sys.platform == "win32", "Windows launcher regression")
@unittest.skipUnless(POWERSHELL, "powershell.exe not available")
class WindowsLauncherProxyTests(unittest.TestCase):
    """Run the real launcher batches with proxy variables set."""

    def setUp(self):
        text = LAUNCHER.read_text(encoding="utf-8-sig")
        self.assertIn(
            STREAMLIT_COMMAND,
            text,
            "Start_SteelAI.bat no longer contains the expected Streamlit command line; "
            "update this regression together with the launcher.",
        )
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.workdir = Path(self.tmpdir.name)
        # Keep the real launcher name so the behaviour under test stays the
        # production entry point.  The only edit replaces the Streamlit start
        # command with a marker echo, so the branch can be observed without ever
        # occupying a port or leaving a process behind.
        self.launcher = self.workdir / "Start_SteelAI.bat"
        self.launcher.write_bytes(
            text.replace(STREAMLIT_COMMAND, f"echo {START_MARKER}").encode("utf-8")
        )
        # The launcher requires a local ".venv\Scripts\python.exe" before it
        # enters the start branch, so link the repository environment.  The stub
        # start command never touches it.
        try:
            os.symlink(ROOT / ".venv", self.workdir / ".venv", target_is_directory=True)
        except (OSError, NotImplementedError):
            shutil.copytree(
                ROOT / ".venv" / "Scripts",
                self.workdir / ".venv" / "Scripts",
                symlinks=True,
            )
        # The probe script lives in scripts\ next to the launcher's own copy, so
        # keep the directory layout of the repository.
        target_scripts = self.workdir / "scripts"
        try:
            os.symlink(ROOT / "scripts", target_scripts, target_is_directory=True)
        except (OSError, NotImplementedError):
            (target_scripts / "check_local_streamlit_health.ps1").parent.mkdir(
                parents=True, exist_ok=True
            )
            shutil.copy2(HEALTH_PROBE, target_scripts / HEALTH_PROBE.name)

    def _free_port(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]

    def _start_health_server(self):
        """Start a loopback-only health server that answers HTTP 200."""

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 - http.server API
                body = b"ok"
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):  # keep pytest output clean
                return

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def cleanup():
            server.shutdown()
            server.server_close()
            thread.join(timeout=10)

        self.addCleanup(cleanup)
        return port

    def _proxy_env(self, port=None):
        env = dict(os.environ)
        # Simulate the reported environment: proxy set, no localhost exception.
        env["HTTP_PROXY"] = DEAD_PROXY
        env["HTTPS_PROXY"] = DEAD_PROXY
        env["ALL_PROXY"] = DEAD_PROXY
        env["NO_PROXY"] = ""
        if port is not None:
            env["STEELAI_PORT"] = str(port)
        env["STEELAI_NO_BROWSER"] = "1"
        return env

    def _run(self, args, env):
        return subprocess.run(
            args,
            cwd=self.workdir,
            env=env,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=60,
        )

    def test_existing_instance_is_detected_behind_a_broken_proxy(self):
        port = self._start_health_server()
        env = self._proxy_env(port)
        before = {name: env[name] for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")}

        completed = self._run(["cmd.exe", "/c", str(self.launcher)], env)
        output = completed.stdout + completed.stderr

        # The health endpoint is served on loopback, so the probe must succeed
        # even though the configured proxy cannot be reached.
        self.assertEqual(
            completed.returncode,
            0,
            f"launcher did not report the running instance:\n{output}",
        )
        self.assertIn("already running", output.lower())
        self.assertNotIn(
            START_MARKER,
            output,
            "launcher tried to start a second Streamlit process while the first "
            f"instance was answering on 127.0.0.1:{port}",
        )
        # The launcher must not read, set or persist proxy configuration.
        self.assertEqual(
            {name: env[name] for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")},
            before,
        )

    def test_launcher_falls_through_when_the_health_endpoint_is_unavailable(self):
        port = self._free_port()
        env = self._proxy_env(port)

        completed = self._run(["cmd.exe", "/c", str(self.launcher)], env)
        output = completed.stdout + completed.stderr

        self.assertNotIn("already running", output.lower())
        self.assertIn(
            START_MARKER,
            output,
            f"launcher did not fall through to the start branch:\n{output}",
        )

    def test_health_probe_rejects_an_unreachable_proxy_for_loopback(self):
        port = self._start_health_server()
        env = self._proxy_env()

        completed = self._run(
            [
                POWERSHELL,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(HEALTH_PROBE),
                "-Port",
                str(port),
            ],
            env,
        )

        self.assertEqual(
            completed.returncode,
            0,
            "loopback health probe returned "
            f"{completed.returncode} with HTTP_PROXY={DEAD_PROXY} and no localhost "
            f"exception:\n{completed.stdout}{completed.stderr}",
        )

    def test_health_probe_reports_not_running_when_nothing_answers(self):
        port = self._free_port()
        env = self._proxy_env()

        completed = self._run(
            [
                POWERSHELL,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(HEALTH_PROBE),
                "-Port",
                str(port),
            ],
            env,
        )

        self.assertEqual(
            completed.returncode,
            1,
            "probe must not report a running instance when nothing answers:\n"
            f"{completed.stdout}{completed.stderr}",
        )

    def test_health_probe_disables_the_proxy_only_for_its_own_request(self):
        text = HEALTH_PROBE.read_text(encoding="utf-8-sig")
        self.assertIn("$request.Proxy = $null", text)
        self.assertIn("$response.Close()", text)
        self.assertIn("$response.Dispose()", text)
        # No global proxy bypass and no proxy-variable mutation may be added.
        for forbidden in ("DefaultWebProxy", "SetEnvironmentVariable", "NO_PROXY="):
            self.assertNotIn(forbidden, text)
        launcher_text = LAUNCHER.read_text(encoding="utf-8-sig")
        self.assertIn("check_local_streamlit_health.ps1", launcher_text)
        self.assertIn('set "STEELAI_PORT=8501"', launcher_text)
        self.assertIn('set "STEELAI_URL=http://127.0.0.1:%STEELAI_PORT%"', launcher_text)
        self.assertIn("--server.address=127.0.0.1", launcher_text)


if __name__ == "__main__":
    unittest.main()
