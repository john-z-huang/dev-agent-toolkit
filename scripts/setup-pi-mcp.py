#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""将 uv tool 安装的 stdio MCP 服务注册到 pi（不启动服务）。"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_SERVER = "dev_agent_toolkit"
UV_TOOL_NAME = "dev-agent-toolkit-tools"
SOURCE = Path(__file__).resolve().parents[1] / "mcp-server"


class SetupError(RuntimeError):
    """Only safe, static diagnostics may reach the terminal."""


def run(argv: list[str], stage: str, timeout: int = 30) -> str:
    try:
        result = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        raise SetupError(
            f"{stage} could not complete; inspect state before retrying"
        ) from None
    if result.returncode:
        # uv/pi output may contain credentials or private package index addresses.
        raise SetupError(f"{stage} failed; inspect state before retrying")
    return result.stdout


def required_command(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise SetupError(f"{name} was not found on PATH")
    return str(Path(path).absolute())


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description=__doc__,
        epilog="pi mcp add replaces the same-name registration, including custom settings. "
        "No connection check is performed. Run pi mcp list separately and /reload in pi.",
    )
    result.add_argument("--server", default=DEFAULT_SERVER, help="pi server name")
    result.add_argument(
        "--command",
        default=UV_TOOL_NAME,
        help="executable basename inside uv tool dir --bin (not a PATH lookup)",
    )
    result.add_argument(
        "--install",
        action="store_true",
        help="install this repository's MCP package first",
    )
    result.add_argument(
        "--force",
        action="store_true",
        help="with --install, reinstall/update the uv tool",
    )
    result.add_argument(
        "--local",
        action="store_true",
        help="register in current directory's .pi/mcp.json",
    )
    result.add_argument(
        "--exposure",
        choices=("codemode", "deferred", "direct", "hidden"),
        default="codemode",
    )
    result.add_argument(
        "--dry-run",
        action="store_true",
        help="print plan without commands or configuration access",
    )
    return result


def main(argv: list[str] | None = None) -> int:
    cli = parser()
    args = cli.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.server):
        cli.error("--server must contain only letters, digits, '_' or '-'")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", args.command) or args.command in (
        ".",
        "..",
    ):
        cli.error("--command must be an executable basename")
    if args.force and not args.install:
        cli.error("--force requires --install")
    if args.install and args.command != UV_TOOL_NAME:
        cli.error("--install only installs this repository's default command")
    if args.dry_run:
        if args.install:
            print(
                f"Would {'reinstall' if args.force else 'install'} uv tool from {SOURCE}"
            )
        print(f"Would locate {args.command} in uv tool dir --bin")
        print(
            f"Would add/replace pi server {args.server} ({'project' if args.local else 'user'} scope, {args.exposure})"
        )
        print("No commands executed; no configuration read or written")
        return 0
    try:
        # Check both prerequisites before installing anything.
        uv = required_command("uv")
        pi = required_command("pi")
        if args.install:
            install = [uv, "tool", "install", "--managed-python"]
            if args.force:
                install.append("--force")
            run([*install, str(SOURCE)], "uv tool install", timeout=300)
        directory = Path(
            run([uv, "tool", "dir", "--bin"], "uv tool directory lookup").strip()
        )
        if not directory.is_absolute():
            raise SetupError("uv returned an invalid tool bin directory")
        executable = directory / args.command
        if not executable.is_file() or not os.access(executable, os.X_OK):
            raise SetupError("installed MCP executable not found or not executable")
        command = [pi, "mcp", "add", args.server, "--exposure", args.exposure]
        if args.local:
            command.append("--local")
        # stdio inherits pi's environment; do not persist credentials or optional
        # ${VAR} references that could fail expansion when a variable is unset.
        run([*command, "--", str(executable)], "pi MCP registration")
    except SetupError as exc:
        print(f"setup-pi-mcp: {exc}", file=sys.stderr)
        return 1
    print(f"Registered pi MCP server {args.server}; connection not tested")
    print("Run pi mcp list to check connections; use /reload in an existing pi session")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
