# Dev Agent Toolkit

项目为 Codex 和 Pi 提供开发操作指南、Skill 和本地 Python MCP 工具。Skill 的声明式 Hooks 说明各动作适用的条件，由 Agent 规划顺序。MCP 提供 Git 仓库和托管资源操作、Codex 会话与项目 Memory 的只读辅助，以及 OpenAI 判断和内容生成。项目定位与命名缘由见 [改名说明](docs/project-rename.md)。

## 安装与构建

构建发行包、安装或更新 uv tool 和 Skill、注册 Codex 或 Pi MCP，以及管理全局指令，见 [安装与构建指南](INSTALL.md)。

## 使用

从 [Skill 入口](skills/dev-agent-toolkit/SKILL.md) 和 [Hook 索引](skills/dev-agent-toolkit/hooks/index.md) 查找当前动作的合同。工具选择与参数见 [MCP 工具目录](skills/dev-agent-toolkit/references/mcp-tools.md)。

- 通过 [独立 MCP Client](docs/mcp-client.md) 在 Shell 或 Python 中按需调用本地 STDIO MCP Server。
- 分支与 worktree 的场景见 [原地建分支](skills/dev-agent-toolkit/references/mcp-tools.md#原地创建工作分支)、[基线同步](skills/dev-agent-toolkit/references/worktree-base-sync.md) 和 [冲突恢复](skills/dev-agent-toolkit/references/worktree-recovery.md)。
- 托管操作与 CLI 查询见 [GitHub](skills/dev-agent-toolkit/references/github.md)、[CLI 补充](skills/dev-agent-toolkit/references/cli-fallback.md) 和 [只读查询规约](skills/dev-agent-toolkit/references/read-only-queries.md)。

### MCP 客户端可见的使用说明

调用前读取服务初始化指令、工具描述与参数 Schema。

### 项目 Memory 只读工具

`serena_memory_tail_read` 读取 MCP 启动项目中指定 Memory 的尾部，`serena_memory_write_check` 检查预期文本是否出现在同一范围。两个工具均离线运行，从实际启动目录下的 `.serena/memories/` 读取。路径范围、参数和状态见 [MCP 工具目录](skills/dev-agent-toolkit/references/mcp-tools.md#项目-memory-只读工具)。

### Codex 会话事实辅助工具

- `get_codex_session_summary_guidance`：获取默认阅读问题与完整摘要模板；可传自定义问题或模板，以用户明确要求为准。
- `order_codex_session_sources`：按 thread ID 去重，按明确的会话创建时间排序；元数据冲突、缺失或时间相同时提示需要澄清。
- `prepare_codex_session_memory`：校验来源、项目路径与 Memory 名称，生成 Serena 写入参数；不读取原会话、不写入文件或 Memory。

原会话通过宿主的 `read_thread` 工具读取，实际保存仍通过 Serena 的项目激活、Memory 读取、写入与回读完成。这些辅助工具只能校验结构，不能证明摘要忠实于原文，也不能授予持久化权限。工具签名见 [`references/mcp-tools.md`](skills/dev-agent-toolkit/references/mcp-tools.md)，事实来源和更新边界见 [`references/codex-session-facts.md`](skills/dev-agent-toolkit/references/codex-session-facts.md)。

### API 判断与生成工具

- `check_api_input` 审核通用外发输入。准入规则、失败处理及其他服务的接入见 [API 输入审核](skills/dev-agent-toolkit/references/api-input-review.md)。
- `decide_codex_session_action`：判断查询历史、查询项目、澄清/阻塞，以及摘要创建、更新或跳过的分支。
- `generate_skill_content`：根据证据、查询重点和用户格式生成 Issue、PR、提交信息、计划、交接或历史会话摘要候选内容。

- `web_search` 为缺少原生联网能力的 Agent 检索公开资料并返回带引用摘要。见 [公开网络搜索](skills/dev-agent-toolkit/references/web-search.md)。

Decisions API（含出站审核）固定用 `gpt-6-luna`。Responses API 的生成、质量审查和公开网络搜索固定用 `gpt-6.2-sol`。进程需取得 `OPENAI_API_KEY` 和 `OPENAI_BASE_URL`。代理、超时、审核与出站约束见 [OpenAI 工具协议](skills/dev-agent-toolkit/references/openai-workflow-tools.md#配置与请求边界)。

## Git commit 信息生成

需要起草提交信息时调用 `generate_git_commit_message`，提交本次选定 patch/hunk 的事实与来源，复用现有内容生成链路返回完整 `message`。经审阅并用 `check_commit_message` 检查后，才在独立授权及其他检查满足时提交。工具不读取 Git、不执行提交；用户已有完整提交信息时保留原文。详见 [提交信息生成与检查](skills/dev-agent-toolkit/references/check-commit-message.md)。

## Issue/PR 多轮修订

新增 `start_issue_pr_draft`、`revise_issue_pr_draft`、`get_issue_pr_draft`、`close_issue_pr_draft`：由外层 Agent 每轮反馈，MCP 保存受限进程内上下文，仍使用 Responses API 和独立质量审查，不引入 Agents SDK。重启或 `/reload` 会丢失草稿；不写文件或 Memory，不自动发布。协议、容量、错误和最小示例见 [多轮草稿](skills/dev-agent-toolkit/references/openai-workflow-tools.md#issuepr-多轮修订草稿)。

## 开发本仓库

仓库结构、验证命令、MCP 开发原则与交付边界见 [`.agents/README.md`](.agents/README.md)；任务导航入口是 [AGENTS.md](AGENTS.md)。这些文档不随发行包交付。
