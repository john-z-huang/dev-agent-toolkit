# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""用 uv tool 安装/更新独立 Hooks 包，再通过已安装命令注册到 Codex。"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = "dev-workflow-standards-hooks"


def build_parser() -> argparse.ArgumentParser:
    """声明安装阶段选项；软件包安装和配置注册仍是两个独立阶段。"""
    parser = argparse.ArgumentParser(description=__doc__)
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--project-root", type=Path, help="目标项目的绝对目录")
    scope.add_argument("--global", dest="global_scope", action="store_true")
    operation = parser.add_mutually_exclusive_group()
    operation.add_argument("--install", action="store_true")
    operation.add_argument("--update", action="store_true")
    parser.add_argument(
        "--dry-run", action="store_true", help="只打印安装与注册计划，不写文件"
    )
    parser.add_argument(
        "--merge", action="store_true", help="首次注册时显式备份并合并已有 Hooks"
    )
    return parser


def registration_arguments(args: argparse.Namespace) -> list[str]:
    scope = (
        ["--global"]
        if args.global_scope
        else ["--project-root", str(args.project_root)]
    )
    result = ["configure", *scope]
    if args.install:
        result.append("--install")
    elif args.update:
        result.append("--update")
    if args.merge:
        result.append("--merge")
    return result


def install_tool(command: list[str]) -> Path:
    """执行 uv 安装并验证实际入口；失败时尚未开始配置注册。"""
    subprocess.run(command, check=True, capture_output=True, timeout=120)
    result = subprocess.run(
        ["uv", "tool", "dir", "--bin"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    executable = Path(result.stdout.strip()) / TOOL
    if not executable.is_absolute() or not executable.is_file():
        raise OSError("安装入口缺失")
    subprocess.run(
        [str(executable), "--version"],
        check=True,
        capture_output=True,
        timeout=10,
    )
    return executable


def register_tool(executable: Path, arguments: list[str]) -> int:
    """执行已安装注册器，保留退出码并区分失败与写入状态未知。"""
    try:
        result = subprocess.run([str(executable), *arguments], check=False, timeout=30)
    except (OSError, subprocess.SubprocessError):
        print(
            "软件包已安装；Hooks 注册中断，请检查实际配置与备份后再处理。",
            file=sys.stderr,
        )
        return 1
    if result.returncode:
        print("软件包已安装；Hooks 注册未完成，未回滚软件包。", file=sys.stderr)
    return result.returncode


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.merge and not args.install:
        parser.error("--merge 只能与 --install 一起使用")
    if args.project_root is not None and (
        not args.project_root.is_absolute() or not args.project_root.is_dir()
    ):
        parser.error("--project-root 必须是已存在的绝对目录")
    install_command = ["uv", "tool", "install", "--python", sys.executable]
    if args.update:
        install_command.extend(["--force", "--reinstall"])
    install_command.append(str(ROOT / "codex-hooks"))
    configure = registration_arguments(args)
    if args.dry_run or not (args.install or args.update):
        print("预览：不安装软件包、不注册配置；以下为执行计划，未验证目标冲突。")
        print(shlex.join(install_command))
        print(f'"$(uv tool dir --bin)/{TOOL}" ' + shlex.join(configure))
        return 0
    try:
        executable = install_tool(install_command)
    except (OSError, subprocess.SubprocessError):
        print(
            "Hooks 软件包安装或入口核验失败；未执行配置注册，请核对 uv tool 状态。",
            file=sys.stderr,
        )
        return 1
    return register_tool(executable, configure)


if __name__ == "__main__":
    raise SystemExit(main())
