#!/bin/bash

# 与 Python 实现放在同一目录，使入口不依赖调用者的工作目录。
script_dir="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)" || exit 1

case "${1:-}" in
    --skills-install|--skills-update|--agents-install|--agents-update)
        operation="$1"
        shift
        # 管理资源必须使用完整发行包入口，不能从可编辑源码环境导入。
        tool_bin="$(uv tool dir --bin)" || exit $?
        case "$operation" in
            --skills-install) set -- skills install "$@" ;;
            --skills-update) set -- skills update "$@" ;;
            # agents update 已支持首次创建，并保留已有文件的接管与备份校验。
            --agents-install|--agents-update) set -- agents update "$@" ;;
        esac
        exec "$tool_bin/dev-workflow-standards" "$@"
        ;;
    --mcp-install)
        shift
        set -- --install "$@"
        ;;
    --mcp-update)
        shift
        set -- --install --force "$@"
        ;;
    --help|-h|"")
        cat <<'HELP'
用法：setup-codex-mcp.sh 操作参数 [对应操作的选项]
  --mcp-install     安装 MCP Server，并注册和配置 Codex
  --mcp-update      更新 MCP Server，并注册和配置 Codex
  --skills-install  从已安装的完整发行包安装 Skill
  --skills-update   从已安装的完整发行包更新 Skill
  --agents-install  创建全局 AGENTS.md；已有文件须显式接管
  --agents-update   更新全局 AGENTS.md，保留接管、备份与冲突校验
Skill 和 AGENTS.md 操作不安装或更新 MCP Server，也不修改 MCP 注册。
在操作参数后加 --help 查看对应选项，加 --dry-run 预览。
兼容原 MCP 参数，例如 --install --force 或 --env-only。
HELP
        exit 0
        ;;
esac

# exec 保留退出状态与信号语义；参数逐项转发，避免空格或通配符被重新解释。
exec uv run --managed-python -- "$script_dir/setup-codex-mcp.py" "$@"
