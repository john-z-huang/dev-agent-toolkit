# 可选原生 Codex Hooks

本适配仅面向 Codex，不是 Pi Code Agent 的扩展或审批机制。Pi 无须安装；不要把 Codex 事件名、hooks.json 或信任配置复制为 Pi 配置。Pi 中仍按当前动作遵循声明式 Hook 合同及实际权限机制。

本 Skill 中的 `hooks/*.md` 是指令合同。源码仓库在 `codex-hooks/` 中独立发布 `dev-agent-toolkit-hooks` 包，由 `scripts/setup-codex-hooks.py` 通过 uv tool 安装并注册，将其中一部分规则转换为 Codex 原生生命周期回调；事件映射与开发验证位于源码仓库的 `codex-hooks/README.md`。这些可执行组件不包含在本 Skill 的 Markdown 安装快照中。

- `SessionStart`：注入范围、授权、代码语义和历史事实边界。
- `UserPromptSubmit`：每回合提示最终交付需要真实证据；不因分析任务额外运行测试或提交。
- `PreToolUse`：检查本服务 MCP 调用中显式提供的非 null `repo_path` 是绝对 Git 根目录；对 Shell 和 apply_patch 注入环境或修改范围提示。
- `PostToolUse`：识别结构化失败，提示回读实际状态、保留现场和停止盲目重试。

提示不等于硬校验，路径通过不等于授权。Git 提交规则继续由 Git hooks 及 MCP 实现执行；OpenAI 请求继续由统一客户端审核。用户意图、来源可信度、复杂命令语义和任务完成状态不由正则或最终回复关键词判定，不自动改写命令或批准权限，也不注册会循环阻塞的 `Stop` 检查。

安装、合并、更新或核对触发时查阅 [原生 Codex Hooks 合同](../hooks/install-codex-hooks.md)。事件协议与信任机制见 [官方 Hooks 文档](https://learn.chatgpt.com/docs/hooks)。
