from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import tomlkit
from codex_setup_fixtures import SCRIPT, config, setup


class EnvOnlyTests(unittest.TestCase):
    def test_default_server_merge_preserves_unrelated_settings_and_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = config(
                Path(directory) / "config.toml",
                '# keep comment\n[other]\nvalue = "untouched"\n\n'
                '[mcp_servers.dev-workflow-standards-tools]\ncommand = "/installed/server"\n'
                'args = []\napproval = "writes"\nenv = { EXISTING = "kept" }\n'
                'env_vars = ["KEEP"]\n',
            )
            path.chmod(0o640)
            out = StringIO()
            with redirect_stdout(out):
                self.assertEqual(setup.main(["--env-only", "--config", str(path)]), 0)
            text = path.read_text(encoding="utf-8")
            data = tomlkit.parse(text)
            server = data["mcp_servers"][setup.DEFAULT_SERVER]
            self.assertEqual(server["env_vars"], ["KEEP", *setup.DEFAULT_ENV_NAMES])
            self.assertEqual(server["approval"], "writes")
            self.assertEqual(server["env"], {"EXISTING": "kept"})
            self.assertIn("# keep comment", text)
            self.assertEqual(path.stat().st_mode & 0o777, 0o640)
            self.assertIn(setup.DEFAULT_SERVER, out.getvalue())

    def test_env_only_is_idempotent_and_runs_no_external_commands(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = config(
                Path(directory) / "custom.toml",
                '[mcp_servers.demo]\ncommand = "runner"\nargs = []\n'
                'env_vars = ["' + '", "'.join(setup.DEFAULT_ENV_NAMES) + '"]\n',
            )
            before, mtime = path.read_bytes(), path.stat().st_mtime_ns
            with (
                patch.object(setup.subprocess, "run", side_effect=AssertionError),
                patch.object(setup.shutil, "which", side_effect=AssertionError),
            ):
                self.assertEqual(
                    setup.main(
                        ["--env-only", "--server", "demo", "--config", str(path)]
                    ),
                    0,
                )
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(path.stat().st_mtime_ns, mtime)

    def test_env_only_dry_run_reads_but_does_not_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = config(
                Path(directory) / "config.toml",
                '[mcp_servers.demo]\ncommand = "runner"\n',
            )
            before, mtime = path.read_bytes(), path.stat().st_mtime_ns
            self.assertEqual(
                setup.main(
                    [
                        "--env-only",
                        "--server",
                        "demo",
                        "--config",
                        str(path),
                        "--dry-run",
                    ]
                ),
                0,
            )
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(path.stat().st_mtime_ns, mtime)

    def test_missing_registration_is_not_created_in_env_only_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = config(
                Path(directory) / "config.toml", "[mcp_servers.other]\ncommand='x'\n"
            )
            before = path.read_bytes()
            err = StringIO()
            with redirect_stderr(err):
                self.assertEqual(
                    setup.main(
                        ["--env-only", "--server", "missing", "--config", str(path)]
                    ),
                    2,
                )
            self.assertIn("section is missing", err.getvalue())
            self.assertEqual(path.read_bytes(), before)

    def test_remote_source_conflict_does_not_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = config(
                Path(directory) / "config.toml",
                '[mcp_servers.demo]\ncommand="runner"\n'
                'env_vars=[{name="OPENAI_API_KEY",source="remote"}]\n',
            )
            before = path.read_bytes()
            with self.assertRaisesRegex(setup.SetupError, "remote"):
                setup._merge_config(path, "demo")
            self.assertEqual(path.read_bytes(), before)

    def test_symlink_and_fifo_targets_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = config(
                root / "target.toml", '[mcp_servers.demo]\ncommand="runner"\n'
            )
            link = root / "link.toml"
            link.symlink_to(target)
            with self.assertRaisesRegex(setup.SetupError, "non-symlink"):
                setup._merge_config(link, "demo")
            if hasattr(os, "mkfifo"):
                fifo = root / "fifo.toml"
                os.mkfifo(fifo)
                with self.assertRaisesRegex(setup.SetupError, "regular"):
                    setup._merge_config(fifo, "demo")

    def test_unsupported_roundtrip_layout_fails_for_change_but_noop_stays_exact(
        self,
    ) -> None:
        prefix = (
            '[[fruit]]\nname="apple"\n\n[unrelated]\nflag=true\n\n'
            '[fruit.texture]\nsmooth=true\n\n[mcp_servers.demo]\ncommand="echo"\n'
        )
        with tempfile.TemporaryDirectory() as directory:
            path = config(Path(directory) / "config.toml", prefix)
            before, mtime = path.read_bytes(), path.stat().st_mtime_ns
            self.assertNotEqual(tomlkit.dumps(tomlkit.parse(prefix)), prefix)
            with self.assertRaisesRegex(setup.SetupError, "cannot be safely rewritten"):
                setup._merge_config(path, "demo")
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(path.stat().st_mtime_ns, mtime)
            complete = (
                prefix
                + "env_vars=["
                + ",".join(f'"{name}"' for name in setup.DEFAULT_ENV_NAMES)
                + "]\n"
            )
            path.write_text(complete, encoding="utf-8")
            before, mtime = path.read_bytes(), path.stat().st_mtime_ns
            self.assertFalse(setup._merge_config(path, "demo"))
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(path.stat().st_mtime_ns, mtime)

    def test_atomic_replace_failure_cleans_temp(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = config(
                Path(directory) / "config.toml",
                '[mcp_servers.demo]\ncommand="runner"\n',
            )
            before = path.read_bytes()
            with (
                patch.object(setup.os, "replace", side_effect=OSError("synthetic")),
                self.assertRaisesRegex(setup.SetupError, "could not be updated"),
            ):
                setup._merge_config(path, "demo")
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(list(Path(directory).glob(".config.toml.*")), [])

    def test_detected_concurrent_change_aborts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = config(
                Path(directory) / "config.toml",
                '[mcp_servers.demo]\ncommand="runner"\n',
            )
            original = setup._read_target
            calls = 0

            def changing_read(candidate: Path, *, allow_missing: bool):
                nonlocal calls
                if candidate == path:
                    calls += 1
                    if calls == 3:
                        path.write_text('[mcp_servers.demo]\ncommand="changed"\n')
                return original(candidate, allow_missing=allow_missing)

            with (
                patch.object(setup, "_read_target", side_effect=changing_read),
                self.assertRaisesRegex(setup.SetupError, "changed during update"),
            ):
                setup._merge_config(path, "demo")
            self.assertIn("changed", path.read_text(encoding="utf-8"))
            self.assertEqual(list(Path(directory).glob(".config.toml.*")), [])


class StandaloneTests(unittest.TestCase):
    def test_pep723_script_runs_from_external_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cwd = Path(directory)
            path = config(
                cwd / "external.toml",
                '[mcp_servers.demo]\ncommand="runner"\nargs=[]\n',
            )
            result = subprocess.run(
                [
                    "uv",
                    "--offline",
                    "run",
                    "--script",
                    str(SCRIPT),
                    "--env-only",
                    "--server",
                    "demo",
                    "--config",
                    str(path),
                    "--dry-run",
                ],
                cwd=cwd,
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("OPENAI_API_KEY", result.stdout)
            self.assertNotIn("command=", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
