"""把真实 wheel 安装到隔离 uv tool 目录，测试不依赖源码导入路径。"""

from __future__ import annotations

import atexit
import functools
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@functools.cache
def hooks_command() -> list[str]:
    temporary = tempfile.TemporaryDirectory(prefix="installed hooks ' ")
    atexit.register(temporary.cleanup)
    root = Path(temporary.name).resolve()
    wheels = root / "wheels"
    subprocess.run(
        [sys.executable, "-m", "hatchling", "build", "-t", "wheel", "-d", str(wheels)],
        cwd=ROOT / "codex-hooks",
        check=True,
        capture_output=True,
    )
    environment = {
        **os.environ,
        "UV_TOOL_DIR": str(root / "tools"),
        "UV_TOOL_BIN_DIR": str(root / "bin"),
    }
    subprocess.run(
        [
            "uv",
            "tool",
            "install",
            "--no-config",
            "--no-index",
            "--python",
            sys.executable,
            str(next(wheels.glob("*.whl"))),
        ],
        env=environment,
        check=True,
        capture_output=True,
    )
    return [str(root / "bin/dev-workflow-standards-hooks"), "configure"]
