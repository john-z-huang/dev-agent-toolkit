# 自动化与兼容资产

交互式 Skill 操作优先使用 [`mcp-tools.md`](mcp-tools.md) 中覆盖需求的工具；未提供工具或功能未覆盖时按 [`cli-fallback.md`](cli-fallback.md) 补足。下面的脚本仍保留在源码仓库，供现有 Hook 或兼容集成使用；核实其用途、实现和副作用后，也可在已授权 CLI 路径中使用，不替代可用工具或绕过实际失败。表内路径均相对源码仓库根目录，不是安装后 Skill 内的文件，安装入口见 [安装与更新索引](../hooks/index.md#安装与更新)。

| 兼容资产 | 用途 / 对应 MCP 工具 |
|---|---|
| `scripts/check-branch-name.py` | Hook 分支名检查；交互式使用 `check_branch_names` |
| `scripts/check-commit-message.py` | Hook 提交标题检查；交互式使用 `check_commit_message` |
| `scripts/check-staged-changes.py` | Hook 暂存区空白检查；交互式使用 `check_staged_changes`（不运行测试） |
| `scripts/check-pr-policy.py` | 历史兼容脚本；交互式使用 `audit_issue_pr_policy` |
| `scripts/pr-merge-cleanup.py` | 旧清理入口；交互式使用 `cleanup_merged_pr_local_branch` |
| `scripts/rewrite_commit_subjects.py` | 通用提交标题映射兼容脚本；当前 MCP 服务不提供对应的交互式工具 |

Hook 接入规则见 [`hooks.md`](git-hooks.md)。历史标题维护边界见 [`rewrite-weather-commit-subjects.md`](rewrite-weather-commit-subjects.md)。
