"""为明确指定的项目生成原生 Codex hooks；默认只预览，不覆盖已有配置。"""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build_config(interpreter: Path, runtime: Path) -> dict:
    command = shlex.join([str(interpreter), str(runtime)])
    handler = {
        "type": "command",
        "command": command,
        "timeout": 5,
        "statusMessage": "核对开发操作约束",
    }
    tools = (
        r"^(Bash|exec_command|shell|shell_command|apply_patch|"
        r"mcp__(dev-workflow-standards-tools|dev_workflow_standards_tools)__.*)$"
    )
    return {
        "hooks": {
            "SessionStart": [{"hooks": [handler]}],
            "UserPromptSubmit": [{"hooks": [handler]}],
            "PreToolUse": [{"matcher": tools, "hooks": [handler]}],
            "PostToolUse": [{"matcher": tools, "hooks": [handler]}],
        }
    }


def install(project: Path, configuration: dict) -> None:
    directory = project / ".codex"
    runtime = directory / "hooks" / "dev_workflow.py"
    config = directory / "hooks.json"
    # 配置和脚本均采用独占创建；不合并未知策略，不替用户信任 hooks。
    if directory.is_symlink() or runtime.parent.is_symlink():
        raise ValueError("目标 .codex 或 hooks 目录不能是符号链接")
    if (
        config.exists()
        or config.is_symlink()
        or runtime.exists()
        or runtime.is_symlink()
    ):
        raise ValueError("目标已有 hooks 配置或脚本；请审阅后手工合并")
    runtime.parent.mkdir(parents=True, exist_ok=True)
    with runtime.open("x", encoding="utf-8") as stream:
        stream.write((ROOT / "codex-hooks" / "runtime.py").read_text(encoding="utf-8"))
    with config.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(configuration, ensure_ascii=False, indent=2) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--install", action="store_true", help="写入目标项目 .codex")
    args = parser.parse_args()
    if not args.project_root.is_absolute() or not args.project_root.is_dir():
        parser.error("--project-root 必须是已存在的绝对目录")
    if not args.python.is_absolute() or not args.python.is_file():
        parser.error("--python 必须是已存在的 Python 解释器绝对路径")
    project = args.project_root.resolve()
    configuration = build_config(args.python, project / ".codex/hooks/dev_workflow.py")
    if args.install:
        try:
            install(project, configuration)
        except (OSError, ValueError):
            print(
                "安装未完成：目标不可写或已有资源。请检查实际文件，勿盲目重试或覆盖。",
                file=sys.stderr,
            )
            return 1
    print(json.dumps(configuration, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
