# 可选原生 Codex Hooks

本 Skill 中的 `hooks/*.md` 是指令合同。源码仓库在 `codex-hooks/` 中独立发布 `dev-workflow-standards-hooks` 包，由 `scripts/setup-codex-hooks.py` 通过 uv tool 安装并注册，将其中一部分规则转换为 Codex 原生生命周期回调；完整映射、安装与验证说明位于源码仓库的 `codex-hooks/README.md`。这些可执行组件不包含在本 Skill 的 Markdown 安装快照中。

- `SessionStart`：注入范围、授权、代码语义和历史事实边界。
- `UserPromptSubmit`：每回合提示最终交付需要真实证据；不因分析任务额外运行测试或提交。
- `PreToolUse`：检查本服务 MCP 调用中显式提供的非 null `repo_path` 是绝对 Git 根目录；对 Shell 和 apply_patch 注入环境或修改范围提示。
- `PostToolUse`：识别结构化失败，提示回读实际状态、保留现场和停止盲目重试。

提示不等于硬校验，路径通过不等于授权。Git 提交规则继续由 Git hooks 及 MCP 实现执行；OpenAI 请求继续由统一客户端审核。用户意图、来源可信度、复杂命令语义和任务完成状态不由正则或最终回复关键词判定，不自动改写命令或批准权限，也不注册会循环阻塞的 `Stop` 检查。

从源码仓库运行 `./dws --hooks-install --global --dry-run` 查看用户全局安装与注册计划（不执行目标校验），或用 `--project-root /absolute/path/to/project` 替代 `--global` 选择项目级范围；两个范围参数互斥且必须二选一。去掉 `--dry-run` 安装，后续用 `--hooks-update` 和相同范围显式更新。

目标仅有其他工具的 `hooks.json` 时，可用 `./dws --hooks-install --global --merge` 显式合并；在包已安装时先用 `"$(uv tool dir --bin)/dev-workflow-standards-hooks" configure --global --install --merge --dry-run` 精确预览合并结果。`--merge` 只用于首次安装：备份原字节到 `hooks.json.backup-*`，保留原事件与配置字段；后续更新也保留原 Hooks。已有本工具脚本或清单时拒绝合并；合并安装后手工修改配置仍会阻止自动更新。

全局目录默认 `~/.codex`，显式 `CODEX_HOME` 必须是已有绝对目录；项目级目录为 `<project>/.codex`。所选目录只写入 `hooks.json` 和 `hooks/dev_workflow.manifest.json` 校验和清单。事件命令注册为已安装 `dev-workflow-standards-hooks` CLI 的绝对路径，不复制运行脚本，不依赖源码或项目 Python。首次安装拒绝已有资源；更新拒绝未知、缺失、符号链接或本地修改的受管文件，旧版无清单资源需手工审阅。直接调用安装脚本无操作参数时只显示计划；已安装 CLI 的 `configure` 子命令提供独立配置预览、安装与更新。校验通过的旧版受管脚本安装可通过更新迁移，原脚本保留但不再调用。安装独立于 Skill/MCP 更新，只管理所选目录的 Hooks 资源，不修改 `config.toml`、Git 配置或宿主信任。需要在支持 hooks 的 Codex 中审阅、信任并核对触发；不具备启用条件时继续遵循原合同。全局与项目级 Hooks 会累积运行，安装器不自动迁移或清理其他范围。协议和信任机制见 [官方 Hooks 文档](https://learn.chatgpt.com/docs/hooks)。
