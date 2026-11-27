# Hook 条件索引

按准备执行的动作或当前状态选读合同。共用规则见 [Skill 入口](../SKILL.md)。

| 动作或状态 | 合同 |
|---|---|
| 修改项目内容 | [项目修改](project-change.md) |
| 代码语义、JSON/YAML/Markdown/TOML/HTML 结构化读取、已安装依赖源码阅读或 Serena 项目配置 | [代码理解与 Serena](code-understanding.md) |
| 选择运行环境，执行 Python、JavaScript 或 TypeScript 命令，编写 Shell 脚本，或进行格式化与静态检查 | [执行环境](environment.md) |
| 创建、同步、恢复或移除 worktree | [Worktree](worktree.md) |
| 暂存或提交 | [暂存与提交](git-commit.md) |
| 使用 `gh` 或访问 GitHub 的 MCP/Connector，或在 GitHub 上操作 Issue、推送分支、创建、修改或合并 PR | [托管资源](github-delivery.md) |
| 引用历史会话事实或保存摘要 | [会话事实](session-facts.md) |
| 发送外部 API 请求 | [外部 API](external-api.md) |
| Codex 当前连接仍旧，需要使用已更新 uv tool 的离线只读方法 | [更新后临时本地 MCP](updated-local-mcp.md) |
| 失败、拒绝、冲突或结果不明 | [恢复](recovery.md) |
| 报告完成、交接或阻塞 | [完成交付](completion.md) |

## 安装与更新

| 目标 | 合同 |
|---|---|
| 构建 sdist/wheel 或安装、重装项目工具包 | [项目工具](install-tooling.md) |
| 安装或更新已安装的 Skill 快照 | [Skill](install-skill.md) |
| 创建、接管或更新 Codex 全局 AGENTS.md | [全局指令](install-global-agents.md) |
| 安装、更新 Codex MCP 或修复转发 | [Codex MCP](install-codex-mcp.md) |
| 安装或更新 Pi MCP 及注册 | [Pi MCP](install-pi-mcp.md) |
