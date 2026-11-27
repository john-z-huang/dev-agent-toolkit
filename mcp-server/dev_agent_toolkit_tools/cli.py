"""管理 Skill、全局指令及 Toolkit 工作流。"""

import argparse
import json
import sys
from pathlib import Path

from .services.global_agents import GlobalAgentsError, manage_global_agents
from .services.skill_installation import SKILL, SkillError, manage_skill


def _parser() -> argparse.ArgumentParser:
    """集中声明 CLI 命令与参数，执行入口只负责分派和错误输出。"""
    parser = argparse.ArgumentParser(
        description="管理 Dev Agent Toolkit Skill、全局指令及提交草稿"
    )
    parser.add_argument(
        "--source-root",
        type=Path,
        help="从指定 checkout 读取 Skill 和全局 AGENTS.md 模板",
    )
    groups = parser.add_subparsers(dest="group", required=True)
    groups.add_parser(
        "mcp",
        help="从 stdin 读取单个 JSON 对象，发现或调用已安装 uv tool 的离线只读工具",
    )
    commit = groups.add_parser("commit", help="通过本地 MCP Client 生成和提交草稿")
    commit.add_argument("--registry", type=Path, help="使用指定的 MCP Client 注册表")
    commit_commands = commit.add_subparsers(dest="action", required=True)
    draft = commit_commands.add_parser("draft", help="生成并保存可采用的候选")
    draft.add_argument("draft_file", type=Path)
    draft.add_argument("--repo-path", type=Path, help="仓库根路径，默认当前目录")
    draft.add_argument("--server", help="Toolkit 服务注册 ID")
    apply = commit_commands.add_parser("apply", help="校验并提交已审阅的草稿")
    apply.add_argument("draft_file", type=Path)
    skills = groups.add_parser("skills", help="安装、查看及更新独立 Skill 快照")
    commands = skills.add_subparsers(dest="action", required=True)
    for action, help_text in (
        ("install", "安装到不存在的目录；拒绝覆盖任何已有目标"),
        ("update", "仅更新完整且未修改的受管安装"),
        ("show", "只读查看来源版本、目标状态和已安装版本"),
    ):
        command = commands.add_parser(action, help=help_text)
        command.add_argument(
            "--target", help=f"完整目标目录；默认 ~/.agents/skills/{SKILL}"
        )
        if action != "show":
            command.add_argument(
                "--dry-run", action="store_true", help="完整预检但不创建目录、锁或文件"
            )
    agents = groups.add_parser(
        "agents", help="查看或显式更新 Codex 全局 AGENTS.md（更新现有文件前强制备份）"
    )
    agent_commands = agents.add_subparsers(dest="action", required=True)
    show = agent_commands.add_parser(
        "show", help="只读校验模板并查看候选内容哈希和目标状态"
    )
    source_help = "显式指定 Markdown 模板路径。默认使用当前 checkout 或发行包随附的模板"
    show.add_argument("--source", help=source_help)
    update = agent_commands.add_parser(
        "update", help="显式更新 ~/.codex/AGENTS.md；现有目标先备份"
    )
    update.add_argument("--source", help=source_help)
    update.add_argument(
        "--dry-run",
        action="store_true",
        help="显示状态、冲突、差异和备份名，不创建任何目录、锁或文件",
    )
    update.add_argument(
        "--adopt",
        action="store_true",
        help="接管未知目标；目标字节相同仅记录元数据，不同则先完整备份",
    )
    update.add_argument(
        "--replace-local",
        action="store_true",
        help="允许替换哈希与元数据不符的受管本地修改；仍会先完整备份",
    )
    return parser


def _run_local_mcp() -> int:
    import asyncio

    from .services.local_mcp import call_updated_local_mcp

    try:
        request = json.load(sys.stdin)
        if not isinstance(request, dict) or request.keys() - {"tool_name", "arguments"}:
            raise ValueError
    except (ValueError, RecursionError):
        result = {"ok": False, "status": "invalid_request"}
    else:
        result = asyncio.run(call_updated_local_mcp(**request))
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1


def _run_commit(args: argparse.Namespace) -> int:
    from .commit_draft import (
        DEFAULT_TOOLKIT_SERVER,
        DraftError,
        apply_draft,
        create_draft,
    )

    try:
        if args.action == "draft":
            result = create_draft(
                args.registry,
                args.server or DEFAULT_TOOLKIT_SERVER,
                args.repo_path or Path.cwd(),
                args.draft_file,
            )
        else:
            result = apply_draft(args.registry, args.draft_file)
    except DraftError as error:
        result = {"ok": False, "error": error.as_dict()}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.group == "mcp":
        return _run_local_mcp()
    if args.group == "commit":
        return _run_commit(args)
    try:
        if args.group == "skills":
            result = manage_skill(
                args.action,
                args.target,
                dry_run=getattr(args, "dry_run", False),
                source_root=args.source_root,
            )
        else:
            source = args.source
            if source is None and args.source_root is not None:
                source = str(args.source_root / "instructions" / "codex-global.md")
            result = manage_global_agents(
                args.action,
                source,
                dry_run=getattr(args, "dry_run", False),
                adopt=getattr(args, "adopt", False),
                replace_local=getattr(args, "replace_local", False),
            )
    except SkillError as error:
        print(
            json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 1
    except GlobalAgentsError as error:
        print(
            json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
