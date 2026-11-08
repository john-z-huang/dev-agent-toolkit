"""验证独立 sdist 可重建 wheel，并由隔离 uv tool 离开源码运行。"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class HooksDistributionTests(unittest.TestCase):
    def test_sdist_rebuild_and_installed_event_registration_without_checkout(self):
        with tempfile.TemporaryDirectory(prefix="hooks distribution ") as directory:
            root = Path(directory).resolve()
            source = root / "source"
            shutil.copytree(
                ROOT / "codex-hooks",
                source,
                ignore=shutil.ignore_patterns(".venv", "__pycache__", "dist"),
            )
            artifacts = root / "artifacts"
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "hatchling",
                    "build",
                    "-t",
                    "sdist",
                    "-d",
                    str(artifacts),
                ],
                cwd=source,
                capture_output=True,
                check=True,
            )
            with tarfile.open(next(artifacts.glob("*.tar.gz"))) as archive:
                archive.extractall(root / "unpacked", filter="data")
            rebuilt = next((root / "unpacked").iterdir())
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "hatchling",
                    "build",
                    "-t",
                    "wheel",
                    "-d",
                    str(artifacts),
                ],
                cwd=rebuilt,
                capture_output=True,
                check=True,
            )
            environment = {
                **os.environ,
                "UV_TOOL_DIR": str(root / "tools"),
                "UV_TOOL_BIN_DIR": str(root / "bin"),
            }
            environment.pop("PYTHONPATH", None)
            subprocess.run(
                [
                    "uv",
                    "tool",
                    "install",
                    "--no-config",
                    "--no-index",
                    "--python",
                    sys.executable,
                    str(next(artifacts.glob("*.whl"))),
                ],
                env=environment,
                capture_output=True,
                check=True,
            )
            source.rename(root / "original-source-unavailable")
            rebuilt.rename(root / "build-source-unavailable")
            command = root / "bin/dev-workflow-standards-hooks"
            home = root / "codex-home"
            home.mkdir()
            environment["CODEX_HOME"] = str(home)
            subprocess.run(
                [str(command), "configure", "--global", "--install"],
                env=environment,
                cwd="/",
                capture_output=True,
                check=True,
            )
            config = json.loads((home / "hooks.json").read_bytes())
            hook = config["hooks"]["SessionStart"][0]["hooks"][0]["command"]
            self.assertEqual(shlex.split(hook), [str(command)])
            event = subprocess.run(
                shlex.split(hook),
                input='{"hook_event_name":"SessionStart"}',
                text=True,
                cwd="/",
                env=environment,
                capture_output=True,
                check=True,
            )
            self.assertIn(
                "additionalContext", json.loads(event.stdout)["hookSpecificOutput"]
            )
            self.assertFalse((home / "hooks/dev_workflow.py").exists())
