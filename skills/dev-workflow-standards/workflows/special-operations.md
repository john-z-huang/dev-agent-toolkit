# 专项操作工作流

只在用户或项目明确要求时执行。操作优先使用 [`mcp-tools.md`](../references/mcp-tools.md) 点名的对应工具；未提供工具或功能未覆盖时，按 [`cli-fallback.md`](../references/cli-fallback.md) 使用相关 CLI 或已审阅脚本。只读细节见 [`read-only-queries.md`](../references/read-only-queries.md)。入口变化不授权额外的历史重写、配置修改或外部操作。

## Hook

按 [`hooks.md`](../references/hooks.md) 确认目标项目已有正确的 `.githooks/pre-commit` 和 `commit-msg`。满足条件且用户授权后，调用 `configure_project_hooks_path` 配置该仓库的 Hook 路径。MCP 不自动复制或安装 Hook 脚本；`--no-verify` 不能替代检查。配置前后均核对本地 Git 配置和文件范围。

## 自动化

使用可移植 Shell/Python、标准库、Git/公开 CLI，不使用专有 Hook 或内部状态；按 [`automation-index.md`](../references/automation-index.md) 记录用途、调用和退出码。项目专属脚本、测试和自定义检查仍由项目工作流执行；不把任意 shell 命令交给 MCP 工具。GitHub 写操作按 [`github-delivery.md`](github-delivery.md)。

## 历史标题维护

按 [`rewrite-weather-commit-subjects.md`](../references/rewrite-weather-commit-subjects.md) 核实历史提交标题维护的授权、范围及验证方案。当前 MCP 不提供对应工具；可按 CLI 补充规约使用相关命令或已审阅的兼容脚本，不因缺工具重复询问；历史重写及远端更新仍须各自的明确授权。
