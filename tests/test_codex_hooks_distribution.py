"""验证独立 sdist 可重建 wheel，并由隔离 uv tool 离开源码运行。"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

from codex_hooks_test_support import build_hooks_distribution, install_hooks_wheel

ROOT = Path(__file__).resolve().parents[1]


def rebuild_sdist_wheel(source: Path, root: Path) -> tuple[Path, Path]:
    """从 sdist 自带文件重建 wheel，返回 wheel 与实际构建源码目录。"""
    artifacts = root / "artifacts"
    sdist = build_hooks_distribution(source, artifacts, "sdist")
    with tarfile.open(sdist) as archive:
        archive.extractall(root / "unpacked", filter="data")
    rebuilt = next((root / "unpacked").iterdir())
    wheel = build_hooks_distribution(rebuilt, artifacts, "wheel")
    return wheel, rebuilt


class HooksDistributionTests(unittest.TestCase):
    def test_sdist_rebuild_and_installed_event_registration_without_checkout(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="hooks distribution ") as directory:
            root = Path(directory).resolve()
            source = root / "source"
            shutil.copytree(
                ROOT / "codex-hooks",
                source,
                ignore=shutil.ignore_patterns(".venv", "__pycache__", "dist"),
            )
            wheel, rebuilt = rebuild_sdist_wheel(source, root)
            command = install_hooks_wheel(wheel, root)
            source.rename(root / "original-source-unavailable")
            rebuilt.rename(root / "build-source-unavailable")
            home = root / "codex-home"
            home.mkdir()
            environment = {**os.environ, "CODEX_HOME": str(home)}
            environment.pop("PYTHONPATH", None)
            subprocess.run(
                [str(command), "configure", "--global", "--install"],
                env=environment,
                cwd="/",
                capture_output=True,
                check=True,
                timeout=10,
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
                timeout=5,
            )
            self.assertIn(
                "additionalContext", json.loads(event.stdout)["hookSpecificOutput"]
            )
            self.assertEqual(
                [path.name for path in (home / "hooks").iterdir()],
                ["dev_agent_toolkit.manifest.json"],
            )
