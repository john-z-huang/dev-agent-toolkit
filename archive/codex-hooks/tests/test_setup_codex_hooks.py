"""核验软件包安装和 Hooks 注册之间的真实阶段边界。"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SETUP = Path(__file__).resolve().parents[1] / "scripts/setup-codex-hooks.py"
spec = importlib.util.spec_from_file_location("hooks_setup", SETUP)
assert spec is not None and spec.loader is not None
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class HooksSetupTests(unittest.TestCase):
    def test_dry_run_does_not_install_or_register(self) -> None:
        with (
            patch.object(
                sys,
                "argv",
                [str(SETUP), "--global", "--install", "--merge", "--dry-run"],
            ),
            patch.object(setup.subprocess, "run") as run,
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(setup.main(), 0)
            run.assert_not_called()
            self.assertIn("uv tool install", output.getvalue())
            self.assertIn("configure --global --install --merge", output.getvalue())

    def test_project_preview_does_not_require_an_existing_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "not-created"
            argv = [str(SETUP), "--project-root", str(target), "--update"]
            with (
                patch.object(sys, "argv", [*argv, "--dry-run"]),
                patch.object(setup.subprocess, "run") as run,
                contextlib.redirect_stdout(io.StringIO()) as output,
            ):
                self.assertEqual(setup.main(), 0)
                self.assertIn(str(target), output.getvalue())
                with (
                    patch.object(sys, "argv", argv),
                    contextlib.redirect_stderr(io.StringIO()),
                    self.assertRaises(SystemExit),
                ):
                    setup.main()
                run.assert_not_called()
            self.assertFalse(target.exists())

    def test_update_installs_package_then_verifies_and_registers_exact_entry(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="hooks bin ") as directory:
            root = Path(directory)
            executable = root / setup.TOOL
            executable.touch()
            results = [
                subprocess.CompletedProcess([], 0),
                subprocess.CompletedProcess([], 0, stdout=str(root) + "\n"),
                subprocess.CompletedProcess([], 0, stdout="0.2.0\n"),
                subprocess.CompletedProcess([], 17),
            ]
            with (
                patch.object(
                    sys, "argv", [str(SETUP), "--global", "--update", "--reconcile"]
                ),
                patch.object(setup.subprocess, "run", side_effect=results) as run,
                contextlib.redirect_stderr(io.StringIO()) as output,
            ):
                self.assertEqual(setup.main(), 17)
            commands = [call.args[0] for call in run.call_args_list]
            self.assertEqual(commands[0][:3], ["uv", "tool", "install"])
            self.assertIn("--force", commands[0])
            self.assertEqual(
                commands[0][-3:],
                [
                    "--reinstall-package",
                    setup.TOOL,
                    str(SETUP.parent.parent),
                ],
            )
            self.assertEqual(commands[2], [str(executable), "--version"])
            self.assertEqual(
                commands[3],
                [str(executable), "configure", "--global", "--update", "--reconcile"],
            )
            self.assertIn("软件包已安装", output.getvalue())

    def test_package_install_failure_never_registers_or_echoes_exception(self) -> None:
        failure = subprocess.CalledProcessError(1, ["uv"], output="SENSITIVE_ERROR")
        with (
            patch.object(sys, "argv", [str(SETUP), "--global", "--install"]),
            patch.object(setup.subprocess, "run", side_effect=failure) as run,
            contextlib.redirect_stderr(io.StringIO()) as output,
        ):
            self.assertEqual(setup.main(), 1)
            self.assertEqual(run.call_count, 1)
            self.assertIn("--reinstall-package", run.call_args.args[0])
            self.assertNotIn("SENSITIVE", output.getvalue())

    def test_registration_timeout_reports_installed_package_and_uncertain_config(
        self,
    ) -> None:
        with (
            patch.object(sys, "argv", [str(SETUP), "--global", "--install"]),
            patch.object(
                setup,
                "install_tool",
                return_value=Path("/synthetic/bin/dev-agent-toolkit-hooks"),
            ),
            patch.object(
                setup.subprocess,
                "run",
                side_effect=subprocess.TimeoutExpired("configure", 30),
            ),
            contextlib.redirect_stderr(io.StringIO()) as output,
        ):
            self.assertEqual(setup.main(), 1)
            self.assertIn("注册中断", output.getvalue())
