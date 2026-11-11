"""Offline tests: no global configuration, installation or MCP connections."""

import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/setup-pi-mcp.py"
spec = importlib.util.spec_from_file_location("setup_pi_mcp", SCRIPT)
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class SetupPiMcpTests(unittest.TestCase):
    def invoke(self, args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            code = setup.main(args)
        return code, output.getvalue()

    def test_dry_run_has_no_external_calls(self):
        with (
            patch.object(setup, "required_command", side_effect=AssertionError),
            patch.object(setup, "run", side_effect=AssertionError),
        ):
            code, text = self.invoke(["--install", "--force", "--local", "--dry-run"])
        self.assertEqual(code, 0)
        self.assertIn("reinstall", text)
        self.assertIn("project", text)

    def test_registration_and_install_order(self):
        with tempfile.TemporaryDirectory(prefix="pi tool ") as tmp:
            executable = Path(tmp) / setup.DEFAULT_SERVER
            executable.write_text("#!/bin/sh\nexit 0\n")
            executable.chmod(0o755)
            with (
                patch.object(
                    setup, "required_command", side_effect=lambda n: f"/bin/{n}"
                ),
                patch.object(setup, "run", side_effect=["", tmp + "\n", ""]) as run,
            ):
                code, text = self.invoke(
                    ["--install", "--force", "--local", "--exposure", "deferred"]
                )
            self.assertEqual(code, 0)
            calls = run.call_args_list
            self.assertEqual(
                calls[0].args[0],
                [
                    "/bin/uv",
                    "tool",
                    "install",
                    "--managed-python",
                    "--force",
                    str(setup.SOURCE),
                ],
            )
            self.assertEqual(calls[1].args[0], ["/bin/uv", "tool", "dir", "--bin"])
            self.assertEqual(
                calls[2].args[0],
                [
                    "/bin/pi",
                    "mcp",
                    "add",
                    setup.DEFAULT_SERVER,
                    "--exposure",
                    "deferred",
                    "--local",
                    "--",
                    str(executable),
                ],
            )
            self.assertIn("connection not tested", text)

    def test_missing_executable_does_not_register(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(setup, "required_command", side_effect=lambda n: f"/bin/{n}"),
            patch.object(setup, "run", return_value=tmp) as run,
        ):
            self.assertEqual(self.invoke([])[0], 1)
            self.assertEqual(run.call_count, 1)

    def test_missing_pi_does_not_install(self):
        with (
            patch.object(
                setup,
                "required_command",
                side_effect=["/bin/uv", setup.SetupError("pi was not found on PATH")],
            ),
            patch.object(setup, "run") as run,
        ):
            self.assertEqual(self.invoke(["--install"])[0], 1)
            run.assert_not_called()

    def test_install_failure_stops_registration(self):
        with (
            patch.object(setup, "required_command", return_value="/bin/mock"),
            patch.object(
                setup, "run", side_effect=setup.SetupError("uv tool install failed")
            ) as run,
        ):
            self.assertEqual(self.invoke(["--install"])[0], 1)
            self.assertEqual(run.call_count, 1)

    def test_relative_tool_directory_rejected(self):
        with (
            patch.object(setup, "required_command", return_value="/bin/mock"),
            patch.object(setup, "run", return_value="relative") as run,
        ):
            self.assertEqual(self.invoke([])[0], 1)
            self.assertEqual(run.call_count, 1)

    def test_argument_validation(self):
        for args in (
            ["--force"],
            ["--server", "bad/name"],
            ["--command", "../bad"],
            ["--install", "--command", "other"],
        ):
            with (
                self.subTest(args=args),
                contextlib.redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit),
            ):
                setup.main(args)

    def test_generic_installed_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "other-mcp"
            exe.write_text("test")
            exe.chmod(0o755)
            with (
                patch.object(setup, "required_command", return_value="/bin/mock"),
                patch.object(setup, "run", side_effect=[tmp, ""]) as run,
            ):
                self.assertEqual(
                    self.invoke(["--command", "other-mcp", "--server", "other"])[0], 0
                )
                self.assertEqual(run.call_args.args[0][-1], str(exe))

    @unittest.skipUnless(shutil.which("pi"), "pi CLI not installed")
    def test_real_pi_registration_in_isolated_config(self):
        # add does not connect: this checks pi's actual persisted configuration,
        # without launching an MCP server or touching the user's configuration.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agent = root / "agent"
            agent.mkdir()
            config = agent / "mcp.json"
            config.write_text(
                json.dumps({"mcpServers": {"untouched": {"enabled": False}}})
            )
            executable = root / setup.DEFAULT_SERVER
            executable.write_text("#!/bin/sh\nexit 0\n")
            executable.chmod(0o755)
            original_run = setup.run

            def isolated_run(argv, stage, timeout=30):
                if stage == "uv tool directory lookup":
                    return str(root)
                return original_run(argv, stage, timeout)

            with (
                patch.dict(os.environ, {"PI_CODING_AGENT_DIR": str(agent)}),
                patch.object(setup, "run", side_effect=isolated_run),
            ):
                code, _ = self.invoke([])
            self.assertEqual(code, 0)
            document = json.loads(config.read_text())
            self.assertEqual(document["mcpServers"]["untouched"], {"enabled": False})
            server = document["mcpServers"][setup.DEFAULT_SERVER]
            self.assertEqual(server["command"], str(executable))
            self.assertEqual(server["exposure"], "codemode")
            self.assertFalse(server.get("env"))

    def test_subprocess_failures_are_redacted(self):
        for response in (
            subprocess.CompletedProcess([], 1, "secret", "private endpoint"),
            subprocess.TimeoutExpired("private endpoint", 1, output="secret"),
            OSError("secret"),
        ):
            with (
                self.subTest(response=type(response)),
                patch.object(subprocess, "run") as run,
            ):
                if isinstance(response, Exception):
                    run.side_effect = response
                else:
                    run.return_value = response
                with self.assertRaises(setup.SetupError) as caught:
                    setup.run(["mock"], "test")
                self.assertNotIn("secret", str(caught.exception))
                self.assertNotIn("private endpoint", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
