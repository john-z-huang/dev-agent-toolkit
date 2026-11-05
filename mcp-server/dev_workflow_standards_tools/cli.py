"""独立 Skill 管理入口；不导入或启动 MCP/OpenAI，不读取凭据。"""

import argparse
import json
import sys

from .services.skill_installation import DEFAULT_DIRECTORY, SkillError, manage_skill
from .services.global_agents import GlobalAgentsError, manage_global_agents


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="离线安装或显式更新开发规范 Skill；不注册 MCP 或安装 Hook")
    groups = parser.add_subparsers(dest="group", required=True)
    skills = groups.add_parser("skills", help="安装、查看及更新独立 Skill 快照")
    commands = skills.add_subparsers(dest="action", required=True)
    for action, help_text in (
        ("install", "安装到不存在的目录；拒绝覆盖任何已有目标"),
        ("update", "仅更新完整且未修改的受管安装"),
        ("show", "只读查看包版本、目标状态和已安装版本"),
    ):
        command = commands.add_parser(action, help=help_text)
        command.add_argument("--target", help=f"完整目标目录；默认 ~/.agents/skills/{DEFAULT_DIRECTORY}")
        if action != "show":
            command.add_argument("--dry-run", action="store_true", help="完整预检但不创建目录、锁或文件")
    agents = groups.add_parser("agents", help="查看或显式更新 Codex 全局 AGENTS.md（更新现有文件前强制备份）")
    agent_commands = agents.add_subparsers(dest="action", required=True)
    show = agent_commands.add_parser("show", help="只读查看候选内容哈希、目标状态和本地依赖")
    show.add_argument("--source", help="显式 Markdown 模板路径；默认使用 wheel 中独立打包的模板")
    update = agent_commands.add_parser("update", help="显式更新 ~/.codex/AGENTS.md；现有目标先备份")
    update.add_argument("--source", help="显式 Markdown 模板路径；默认使用 wheel 中独立打包的模板")
    update.add_argument("--dry-run", action="store_true", help="显示状态、冲突、差异和备份名，不创建任何目录、锁或文件")
    update.add_argument("--adopt", action="store_true",
                        help="接管未知目标；目标字节相同仅记录元数据，不同则先完整备份")
    update.add_argument("--replace-local", action="store_true", help="允许替换哈希与元数据不符的受管本地修改；仍会先完整备份")
    args = parser.parse_args(argv)
    try:
        if args.group == "skills":
            result = manage_skill(args.action, args.target, dry_run=getattr(args, "dry_run", False))
        else:
            result = manage_global_agents(
                args.action,
                args.source,
                dry_run=getattr(args, "dry_run", False),
                adopt=getattr(args, "adopt", False),
                replace_local=getattr(args, "replace_local", False),
            )
    except SkillError as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    except GlobalAgentsError as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
