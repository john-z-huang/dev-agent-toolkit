from __future__ import annotations

import json
import os
import subprocess
import tempfile
import tomllib
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from typing import Any
from unittest.mock import patch

from codex_setup_fixtures import config, setup


class RegistrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = self.root / "codex-home" / "config.toml"
        self.exe = self.root / "bin" / "dev-workflow-standards-tools"
        self.exe.parent.mkdir(parents=True)
        self.exe.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        self.exe.chmod(0o755)
        self.calls: list[tuple[list[str], dict[str, str] | None]] = []

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _codex_mocks(
        self, *, listed: bool, existing: dict[str, Any] | None = None, add=None
    ):
        def run(argv, **kwargs):
            env = kwargs.get("env")
            self.calls.append((argv, env))
            if argv[1:3] == ["mcp", "list"]:
                return subprocess.CompletedProcess(
                    argv,
                    0,
                    json.dumps([{"name": setup.DEFAULT_SERVER}] if listed else []),
                    "",
                )
            if argv[1:3] == ["mcp", "get"]:
                return subprocess.CompletedProcess(argv, 0, json.dumps(existing), "")
            if "mcp" in argv and "add" in argv:
                if add:
                    add(argv, env)
                return subprocess.CompletedProcess(argv, 0, "", "")
            if argv[-1:] == ["--version"]:
                return subprocess.CompletedProcess(argv, 0, "codex test", "")
            return subprocess.CompletedProcess(argv, 0, str(self.root / "tool-bin"), "")

        return run

    def test_default_registration_adds_required_names_and_uses_selected_codex_home(
        self,
    ) -> None:
        def destructive_add(argv, env):
            self.assertEqual(env["CODEX_HOME"], str(self.config.parent))
            self.config.parent.mkdir(parents=True, exist_ok=True)
            self.config.write_text(
                f'[mcp_servers.{setup.DEFAULT_SERVER}]\ncommand = "{argv[-1]}"\nargs = []\n',
                encoding="utf-8",
            )

        with (
            patch.object(
                setup.shutil,
                "which",
                side_effect=lambda name: "/codex" if name == "codex" else "/uv",
            ),
            patch.object(
                setup.subprocess,
                "run",
                side_effect=self._codex_mocks(listed=False, add=destructive_add),
            ),
        ):
            self.assertEqual(
                setup.main(
                    ["--config", str(self.config), "--executable", str(self.exe)]
                ),
                0,
            )
        parsed = tomllib.loads(self.config.read_text(encoding="utf-8"))
        self.assertEqual(
            parsed["mcp_servers"][setup.DEFAULT_SERVER]["env_vars"],
            list(setup.DEFAULT_ENV_NAMES),
        )
        add_call = next(call for call, _env in self.calls if "add" in call)
        self.assertEqual(add_call[-2:], ["--", str(self.exe.resolve())])

    def test_matching_registration_repairs_env_without_upsert(self) -> None:
        config(
            self.config,
            f'[mcp_servers.{setup.DEFAULT_SERVER}]\ncommand="{self.exe}"\nargs=[]\n'
            'approval = "writes"\n',
        )
        existing = {
            "name": setup.DEFAULT_SERVER,
            "enabled": True,
            "transport": {"type": "stdio", "command": str(self.exe), "args": []},
        }
        with (
            patch.object(setup.shutil, "which", return_value="/codex"),
            patch.object(
                setup.subprocess,
                "run",
                side_effect=self._codex_mocks(listed=True, existing=existing),
            ),
        ):
            self.assertEqual(
                setup.main(
                    ["--config", str(self.config), "--executable", str(self.exe)]
                ),
                0,
            )
        self.assertFalse(any("add" in call for call, _env in self.calls))
        parsed = tomllib.loads(self.config.read_text(encoding="utf-8"))
        server = parsed["mcp_servers"][setup.DEFAULT_SERVER]
        self.assertEqual(server["approval"], "writes")
        self.assertEqual(server["env_vars"], list(setup.DEFAULT_ENV_NAMES))

    def test_replace_restores_stdio_settings_after_destructive_upsert(self) -> None:
        config(
            self.config,
            f'[mcp_servers.{setup.DEFAULT_SERVER}]\ncommand="/old/launcher"\nargs=[]\n'
            'enabled=false\nenv_vars=["KEEP"]\nenv={EXISTING="safe"}\n'
            'default_tools_approval_mode="writes"\ntool_timeout_sec=17\n',
        )
        existing = {
            "name": setup.DEFAULT_SERVER,
            "enabled": True,
            "transport": {"type": "stdio", "command": "/old/launcher", "args": []},
        }

        def add(argv, _env):
            self.config.write_text(
                f'[mcp_servers.{setup.DEFAULT_SERVER}]\ncommand="{argv[-1]}"\nargs=[]\nenabled=true\n',
                encoding="utf-8",
            )

        with (
            patch.object(setup.shutil, "which", return_value="/codex"),
            patch.object(
                setup.subprocess,
                "run",
                side_effect=self._codex_mocks(listed=True, existing=existing, add=add),
            ),
        ):
            self.assertEqual(
                setup.main(
                    [
                        "--config",
                        str(self.config),
                        "--executable",
                        str(self.exe),
                        "--replace",
                    ]
                ),
                0,
            )
        server = tomllib.loads(self.config.read_text(encoding="utf-8"))["mcp_servers"][
            setup.DEFAULT_SERVER
        ]
        self.assertTrue(server["enabled"])
        self.assertEqual(server["env_vars"], ["KEEP", *setup.DEFAULT_ENV_NAMES])
        self.assertEqual(server["env"], {"EXISTING": "safe"})
        self.assertEqual(server["default_tools_approval_mode"], "writes")
        self.assertEqual(server["tool_timeout_sec"], 17)

    def test_http_replace_keeps_only_common_policy(self) -> None:
        config(
            self.config,
            f'[mcp_servers.{setup.DEFAULT_SERVER}]\nurl="https://example.invalid"\n'
            'bearer_token_env_var="OLD"\ndefault_tools_approval_mode="writes"\n'
            'disabled_tools=["x"]\n',
        )
        existing = {
            "name": setup.DEFAULT_SERVER,
            "enabled": True,
            "transport": {"type": "http", "url": "https://example.invalid"},
        }

        def add(argv, _env):
            config(
                self.config,
                f'[mcp_servers.{setup.DEFAULT_SERVER}]\ncommand="{argv[-1]}"\nargs=[]\nenabled=true\n',
            )

        with (
            patch.object(setup.shutil, "which", return_value="/codex"),
            patch.object(
                setup.subprocess,
                "run",
                side_effect=self._codex_mocks(listed=True, existing=existing, add=add),
            ),
        ):
            self.assertEqual(
                setup.main(
                    [
                        "--config",
                        str(self.config),
                        "--executable",
                        str(self.exe),
                        "--replace",
                    ]
                ),
                0,
            )
        server = tomllib.loads(self.config.read_text(encoding="utf-8"))["mcp_servers"][
            setup.DEFAULT_SERVER
        ]
        self.assertEqual(server["default_tools_approval_mode"], "writes")
        self.assertEqual(server["disabled_tools"], ["x"])
        self.assertNotIn("url", server)
        self.assertNotIn("bearer_token_env_var", server)

    def test_conflict_and_invalid_config_fail_before_install(self) -> None:
        config(
            self.config,
            f'[mcp_servers.{setup.DEFAULT_SERVER}]\ncommand="/old"\nargs=[]\n',
        )
        existing = {
            "name": setup.DEFAULT_SERVER,
            "enabled": True,
            "transport": {"type": "stdio", "command": "/old", "args": []},
        }
        with (
            patch.object(
                setup.shutil,
                "which",
                side_effect=lambda name: "/codex" if name == "codex" else "/uv",
            ),
            patch.object(
                setup.subprocess,
                "run",
                side_effect=self._codex_mocks(listed=True, existing=existing),
            ),
        ):
            err = StringIO()
            with redirect_stderr(err):
                self.assertEqual(
                    setup.main(["--install", "--config", str(self.config)]), 2
                )
        self.assertIn("use --replace", err.getvalue())
        self.assertFalse(any("install" in call for call, _env in self.calls))
        self.assertFalse(any("add" in call for call, _env in self.calls))

    def test_symlink_config_fails_before_install_or_registration(self) -> None:
        target = config(self.root / "target.toml", "[other]\nvalue=1\n")
        self.config.parent.mkdir(parents=True)
        self.config.symlink_to(target)
        with (
            patch.object(
                setup.shutil,
                "which",
                side_effect=lambda name: "/codex" if name == "codex" else "/uv",
            ),
            patch.object(
                setup.subprocess, "run", side_effect=self._codex_mocks(listed=False)
            ),
        ):
            err = StringIO()
            with redirect_stderr(err):
                self.assertEqual(
                    setup.main(["--install", "--config", str(self.config)]), 2
                )
        self.assertIn("non-symlink", err.getvalue())
        self.assertFalse(any("install" in call for call, _env in self.calls))
        self.assertFalse(any("add" in call for call, _env in self.calls))

    def test_malformed_toml_fails_before_install_or_registration(self) -> None:
        config(self.config, "not = [valid\n")
        with (
            patch.object(
                setup.shutil,
                "which",
                side_effect=lambda name: "/codex" if name == "codex" else "/uv",
            ),
            patch.object(
                setup.subprocess, "run", side_effect=self._codex_mocks(listed=False)
            ),
        ):
            err = StringIO()
            with redirect_stderr(err):
                self.assertEqual(
                    setup.main(["--install", "--config", str(self.config)]), 2
                )
        self.assertIn("not valid UTF-8 TOML", err.getvalue())
        self.assertFalse(any("install" in call for call, _env in self.calls))
        self.assertFalse(any("add" in call for call, _env in self.calls))

    def test_failed_add_reports_uncertain_partial_state_without_echoing_output(
        self,
    ) -> None:
        marker = "SYNTHETIC_SUBPROCESS_OUTPUT"

        def run(argv, **kwargs):
            self.calls.append((argv, kwargs.get("env")))
            if argv[-1:] == ["--version"]:
                return subprocess.CompletedProcess(argv, 0, "", "")
            if argv[1:3] == ["mcp", "list"]:
                return subprocess.CompletedProcess(argv, 0, "[]", "")
            if "add" in argv:
                self.config.parent.mkdir(parents=True, exist_ok=True)
                self.config.write_text(
                    f'[mcp_servers.{setup.DEFAULT_SERVER}]\ncommand="{argv[-1]}"\nargs=[]\n',
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess(argv, 7, marker, marker)
            return subprocess.CompletedProcess(argv, 0, "", "")

        with (
            patch.object(setup.shutil, "which", return_value="/codex"),
            patch.object(setup.subprocess, "run", side_effect=run),
        ):
            err = StringIO()
            with redirect_stderr(err):
                self.assertEqual(
                    setup.main(
                        ["--config", str(self.config), "--executable", str(self.exe)]
                    ),
                    2,
                )
        self.assertIn("registration did not complete", err.getvalue())
        self.assertIn("inspect the selected Codex config", err.getvalue())
        self.assertNotIn(marker, err.getvalue())
        self.assertNotIn(
            "env_vars",
            tomllib.loads(self.config.read_text(encoding="utf-8"))["mcp_servers"][
                setup.DEFAULT_SERVER
            ],
        )

    def test_install_precedes_registration_and_force_is_forwarded(self) -> None:
        install_exe = self.root / "tool-bin" / "dev-workflow-standards-tools"

        def run(argv, **kwargs):
            self.calls.append((argv, kwargs.get("env")))
            if argv[1:3] == ["mcp", "list"]:
                return subprocess.CompletedProcess(argv, 0, "[]", "")
            if argv[-1:] == ["--version"]:
                return subprocess.CompletedProcess(argv, 0, "", "")
            if argv[1:4] == ["tool", "install", "--managed-python"]:
                install_exe.parent.mkdir(parents=True, exist_ok=True)
                install_exe.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
                install_exe.chmod(0o755)
                return subprocess.CompletedProcess(argv, 0, "", "")
            if "add" in argv:
                self.config.parent.mkdir(parents=True, exist_ok=True)
                self.config.write_text(
                    f'[mcp_servers.{setup.DEFAULT_SERVER}]\ncommand="{argv[-1]}"\nargs=[]\n',
                    encoding="utf-8",
                )
            return subprocess.CompletedProcess(argv, 0, str(self.root / "tool-bin"), "")

        with (
            patch.object(
                setup.shutil,
                "which",
                side_effect=lambda name: "/codex" if name == "codex" else "/uv",
            ),
            patch.object(setup.subprocess, "run", side_effect=run),
        ):
            self.assertEqual(
                setup.main(["--install", "--force", "--config", str(self.config)]), 0
            )
        install_index = next(
            i
            for i, (call, _) in enumerate(self.calls)
            if call[1:3] == ["tool", "install"]
        )
        add_index = next(i for i, (call, _) in enumerate(self.calls) if "add" in call)
        self.assertLess(install_index, add_index)
        self.assertIn("--force", self.calls[install_index][0])
        self.assertEqual(
            self.calls[install_index][0][-3:],
            [
                "--reinstall-package",
                setup.DEFAULT_SERVER,
                str(Path(setup.__file__).resolve().parents[1] / "mcp-server"),
            ],
        )

    def test_registration_dry_run_has_no_config_reads_or_subprocesses(self) -> None:
        with (
            patch.object(setup, "_read_target", side_effect=AssertionError),
            patch.object(setup.subprocess, "run", side_effect=AssertionError),
            patch.object(setup.shutil, "which", side_effect=AssertionError),
        ):
            self.assertEqual(
                setup.main(["--dry-run", "--config", str(self.config), "--install"]), 0
            )

    def test_config_home_is_forwarded_and_arbitrary_registration_filename_rejected(
        self,
    ) -> None:
        with patch.dict(os.environ, {"CODEX_HOME": str(self.root / "home")}):
            self.assertEqual(setup.target_config(), self.root / "home" / "config.toml")
        err = StringIO()
        with redirect_stderr(err), self.assertRaises(SystemExit) as raised:
            setup.main(["--config", str(self.root / "custom.toml"), "--dry-run"])
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("must name config.toml", err.getvalue())

    def test_subprocess_error_does_not_echo_captured_contents(self) -> None:
        sentinel = "SYNTHETIC_SENTINEL_VALUE"
        argv = ["fake-codex"]
        with (
            patch.object(
                setup.subprocess,
                "run",
                return_value=subprocess.CompletedProcess(argv, 5, sentinel, sentinel),
            ),
            self.assertRaises(setup.SetupError) as caught,
        ):
            setup._run(argv, stage="Codex probe")
        self.assertNotIn(sentinel, str(caught.exception))


if __name__ == "__main__":
    unittest.main()
