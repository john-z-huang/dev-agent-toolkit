# 可选原生 Codex Hooks

本 Skill 中的 `hooks/*.md` 是指令合同。源码仓库另外提供 `codex-hooks/runtime.py` 和 `scripts/setup-codex-hooks.py`，将其中一部分规则转换为 Codex 原生生命周期回调；完整映射、安装与验证说明位于源码仓库的 `codex-hooks/README.md`。这些可执行组件不包含在本 Skill 的 Markdown 安装快照中。

- `SessionStart`：注入范围、授权、代码语义和历史事实边界。
- `UserPromptSubmit`：每回合提示最终交付需要真实证据；不因分析任务额外运行测试或提交。
- `PreToolUse`：检查本服务 MCP 调用中显式提供的非 null `repo_path` 是绝对 Git 根目录；对 Shell 和 apply_patch 注入环境或修改范围提示。
- `PostToolUse`：识别结构化失败，提示回读实际状态、保留现场和停止盲目重试。

提示不等于硬校验，路径通过不等于授权。Git 提交规则继续由 Git hooks 及 MCP 实现执行；OpenAI 请求继续由统一客户端审核。用户意图、来源可信度、复杂命令语义和任务完成状态不由正则或最终回复关键词判定，不自动改写命令或批准权限，也不注册会循环阻塞的 `Stop` 检查。

配置通过显式安装命令写入指定项目 `.codex/hooks.json`，脚本复制到 `.codex/hooks/dev_workflow.py`；默认只预览且拒绝覆盖已有资源。安装独立于 Skill/MCP 更新，不修改全局配置、Git 配置或宿主信任。需要在支持 hooks 的 Codex 中审阅、信任并核对触发；不具备启用条件时继续遵循原合同。协议和信任机制见 [官方 Hooks 文档](https://learn.chatgpt.com/docs/hooks)。
