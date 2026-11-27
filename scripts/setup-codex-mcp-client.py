#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""从当前源码安装并验证供 Codex 调用的 MCP Client CLI。"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "mcp-client"
PACKAGE = "dev-agent-toolkit-mcp-client"
EXECUTABLE = "dev_agent_toolkit_mcp_client"


def _run(argv: list[str], *, timeout: int = 30) -> str:
    # uv 的诊断可能包含私有索引地址或凭据。
    return subprocess.run(
        argv, text=True, capture_output=True, check=True, timeout=timeout
    ).stdout


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="强制重新安装 uv tool")
    parser.add_argument("--dry-run", action="store_true", help="仅显示安装和验证计划")
    args = parser.parse_args(argv)
    if args.dry_run:
        action = "强制重新安装" if args.force else "安装"
        print(f"将从 {SOURCE} {action} {PACKAGE}")
        print(f"将通过 uv tool dir --bin 定位并执行 {EXECUTABLE} --help")
        return 0

    uv = shutil.which("uv")
    if uv is None:
        print("找不到 uv，请检查 PATH。", file=sys.stderr)
        return 1
    install = [uv, "tool", "install", "--managed-python"]
    if args.force:
        install.append("--force")
    try:
        _run([*install, "--reinstall-package", PACKAGE, str(SOURCE)], timeout=300)
    except (OSError, subprocess.SubprocessError):
        print("MCP Client 安装未完成，请检查 uv tool 安装状态后重试。", file=sys.stderr)
        return 1

    try:
        tool_bin = Path(_run([uv, "tool", "dir", "--bin"]).rstrip("\n"))
        executable = tool_bin / EXECUTABLE
        if (
            not tool_bin.is_absolute()
            or not executable.is_file()
            or not os.access(executable, os.X_OK)
        ):
            print(
                "MCP Client 已安装，但 uv tool 目录中找不到可执行入口。",
                file=sys.stderr,
            )
            return 1
        _run([str(executable), "--help"])
    except (OSError, subprocess.SubprocessError):
        print("MCP Client 已安装，但 CLI 验证失败。", file=sys.stderr)
        return 1

    print(f"MCP Client 已安装并通过 --help 验证：{executable}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
