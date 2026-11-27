"""把真实 wheel 安装到隔离 uv tool 目录，测试不依赖源码导入路径。"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

ROOT = Path(__file__).resolve().parents[1]


def build_hooks_distribution(
    source: Path, destination: Path, kind: Literal["sdist", "wheel"]
) -> Path:
    """使用现有测试解释器构建标准发行包，不安装依赖或修改用户工具。"""
    subprocess.run(
        [
            sys.executable,
            "-m",
            "hatchling",
            "build",
            "-t",
            kind,
            "-d",
            str(destination),
        ],
        cwd=source,
        check=True,
        capture_output=True,
        timeout=60,
    )
    suffix = "*.whl" if kind == "wheel" else "*.tar.gz"
    return next(destination.glob(suffix))


def install_hooks_wheel(wheel: Path, root: Path) -> Path:
    """仅向调用者提供的隔离 uv tool 目录安装 wheel，禁止访问包索引。"""
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
            str(wheel),
        ],
        env=environment,
        check=True,
        capture_output=True,
        timeout=60,
    )
    return root / "bin/dev-agent-toolkit-hooks"


@contextmanager
def installed_hooks_tool() -> Generator[tuple[str, str], None, None]:
    """显式管理测试工具目录，构建失败或测试结束时均清理临时资源。"""
    with tempfile.TemporaryDirectory(prefix="installed hooks ' ") as temporary:
        root = Path(temporary).resolve()
        wheel = build_hooks_distribution(ROOT / "codex-hooks", root / "wheels", "wheel")
        executable = install_hooks_wheel(wheel, root)
        yield str(executable), "configure"


class InstalledHooksTestCase(unittest.TestCase):
    """注册测试共用的类级工具环境；各用例的目标配置目录仍独立。"""

    configure_command: tuple[str, str]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.configure_command = cls.enterClassContext(installed_hooks_tool())
