# dev-workflow-standards

项目为 Codex 和 Pi 提供开发操作 Skill 和本地 Python MCP 服务。Skill 的声明式 Hooks 说明各动作适用的条件，由 Agent 规划顺序。MCP 提供 Git 仓库和托管资源操作、Codex 会话与项目 Memory 的只读辅助，以及 OpenAI 判断和内容生成。

## 安装与构建

构建发行包、安装或更新 uv tool 和 Skill、注册 Codex 或 Pi MCP，以及管理全局指令和原生 Hooks，见 [安装与构建指南](INSTALL.md)。

## 使用

可选的 [原生 Codex Hooks](codex-hooks/README.md) 提供会话与交付提示、MCP 目标仓库路径校验，以及结构化失败后的恢复提示。安装和更新步骤见 [原生 Codex Hooks 安装说明](INSTALL.md#安装与更新原生-codex-hooks)。

从 [Skill 入口](skills/dev-workflow-standards/SKILL.md) 和 [Hook 索引](skills/dev-workflow-standards/hooks/index.md) 查找当前动作的合同。工具选择与参数见 [MCP 工具目录](skills/dev-workflow-standards/references/mcp-tools.md)。

- 分支与 worktree 的场景见 [原地建分支](skills/dev-workflow-standards/references/mcp-tools.md#原地创建工作分支)、[基线同步](skills/dev-workflow-standards/references/worktree-base-sync.md) 和 [冲突恢复](skills/dev-workflow-standards/references/worktree-recovery.md)。
- 托管操作与 CLI 查询见 [GitHub](skills/dev-workflow-standards/references/github.md)、[CLI 补充](skills/dev-workflow-standards/references/cli-fallback.md) 和 [只读查询规约](skills/dev-workflow-standards/references/read-only-queries.md)。

### MCP 客户端可见的使用说明

调用前读取服务初始化指令、工具描述与参数 Schema。维护要求见 [MCP 可发现说明](AGENTS.md#mcp-可发现说明)。

### 项目 Memory 只读工具

`serena_memory_tail_read` 读取 MCP 启动项目中指定 Memory 的尾部，`serena_memory_write_check` 检查预期文本是否出现在同一范围。两个工具均离线运行，从实际启动目录下的 `.serena/memories/` 读取。路径范围、参数和状态见 [MCP 工具目录](skills/dev-workflow-standards/references/mcp-tools.md#项目-memory-只读工具)。

### Codex 会话事实辅助工具

- `get_codex_session_summary_guidance`：获取默认阅读问题与完整摘要模板；可传自定义问题或模板，以用户明确要求为准。
- `order_codex_session_sources`：按 thread ID 去重，按明确的会话创建时间排序；元数据冲突、缺失或时间相同时提示需要澄清。
- `prepare_codex_session_memory`：校验来源、项目路径与 Memory 名称，生成 Serena 写入参数；不读取原会话、不写入文件或 Memory。

原会话通过宿主的 `read_thread` 工具读取，实际保存仍通过 Serena 的项目激活、Memory 读取、写入与回读完成。这些辅助工具只能校验结构，不能证明摘要忠实于原文，也不能授予持久化权限。工具签名见 [`references/mcp-tools.md`](skills/dev-workflow-standards/references/mcp-tools.md)，事实来源和更新边界见 [`references/codex-session-facts.md`](skills/dev-workflow-standards/references/codex-session-facts.md)。

### API 判断与生成工具

- `check_api_input` 审核通用外发输入。准入规则、失败处理及其他服务的接入见 [API 输入审核](skills/dev-workflow-standards/references/api-input-review.md)。
- `decide_codex_session_action`：判断查询历史、查询项目、澄清/阻塞，以及摘要创建、更新或跳过的分支。
- `generate_skill_content`：根据证据、查询重点和用户格式生成 Issue、PR、提交信息、计划、交接或历史会话摘要候选内容。

- `web_search` 为缺少原生联网能力的 Agent 检索公开资料并返回带引用摘要。见 [公开网络搜索](skills/dev-workflow-standards/references/web-search.md)。

Decisions API（含出站审核）固定用 `gpt-6-luna`。Responses API 的生成、质量审查和公开网络搜索固定用 `gpt-6.2-sol`。进程需取得 `OPENAI_API_KEY` 和 `OPENAI_BASE_URL`。代理、超时、审核与出站约束见 [OpenAI 工具协议](skills/dev-workflow-standards/references/openai-workflow-tools.md#配置与请求边界)。

## 项目结构

- `skills/dev-workflow-standards/SKILL.md`：唯一 Skill 入口、共用边界及按需条件索引。
- `skills/dev-workflow-standards/hooks/`：独立动作的进入、执行、离开及重新核验条件。
- `skills/dev-workflow-standards/references/`：按需加载的决策细节、独立安装说明和 MCP 工具映射。
- `mcp-server/`：Python/uv MCP v2 stdio 服务和固定操作工具。
- `instructions/codex-global.md`：版本化的全局指令源；通过独立 CLI 显式同步到用户目录。
- `archive/mcp-server-ts/`：已归档且不再支持的历史 TypeScript MCP 实现；其历史说明见该目录的 [`README.md`](archive/mcp-server-ts/README.md)。
- `scripts/`：Codex 安装配置脚本，以及供标准 Git Hook 集成使用的可移植校验资产；`.githooks/`：Hook 入口。

当前 MCP 服务实现与调用约束见 [`mcp-server/pyproject.toml`](mcp-server/pyproject.toml) 和 [`references/mcp-tools.md`](skills/dev-workflow-standards/references/mcp-tools.md)。

## 本地验证

### Python 代码格式化与静态检查

从仓库根目录运行下列命令。前三条用 MCP 项目的 Ruff 配置覆盖 `mcp-server/`、`scripts/`、`skills/` 和 `tests/` 中的 Python 文件。最后一条用 ty 检查 `mcp-server/` 中的 Python 文件。

```bash
/bin/bash -c 'cd mcp-server && uv run --locked -- ruff format --config pyproject.toml . ../scripts ../skills ../tests'
/bin/bash -c 'cd mcp-server && uv run --locked -- ruff format --check --config pyproject.toml . ../scripts ../skills ../tests'
/bin/bash -c 'cd mcp-server && uv run --locked -- ruff check --no-fix --config pyproject.toml . ../scripts ../skills ../tests'
/bin/bash -c 'cd mcp-server && uv run --locked -- ty check'
```

`ruff format` 写入源码。其余命令用于检查。只格式化本次改动时，把目录参数换成目标文件。`codex-hooks/` 使用独立环境和配置，见 [Hooks 验证命令](codex-hooks/README.md#验证)。

### 离线测试

在 `mcp-server/` 使用项目环境运行离线测试：

```bash
/bin/bash -c 'uv sync --managed-python && uv run --managed-python -- python -m unittest discover -s ../tests -v'
```

构建测试会在临时目录生成并解包 sdist、重建 wheel、安装到隔离环境后运行 CLI，不会写入现有用户 Skill 目录。

### OpenAI 官方 API 冒烟测试

`tests/openai_official_smoke.py` 使用统一客户端发起最小 Responses 请求，固定 `gpt-6.2-sol`、`medium` 推理强度和 512 token 输出上限，出站审核用 `gpt-6-luna`。只有显式传入 `--live` 才联网并产生实际 API 用量。不传参数输出 `skipped`，退出码为 2。常规离线测试验证该入口的行为。

先在终端中配置并导出所需的 API 和代理环境变量，再从 `mcp-server/` 目录通过 Bash 运行；Bash 子进程继承当前终端已导出的配置：

```bash
/bin/bash -c 'uv run --frozen -- python ../tests/openai_official_smoke.py --live'
```

测试按原拼写读取 `OPENAI_API_KEY_OFFICAL` 和 `OPENAI_BASE_URL_OFFICAL`，任一缺失或为空就停止，不能回退到其他配置。入口只在调用期间将它们映射为统一客户端要求的 `OPENAI_API_KEY` 和 `OPENAI_BASE_URL`，之后恢复原环境；生产客户端的配置规则保持不变。代理继续读取当前进程的标准代理变量，遵循 `NO_PROXY`。

输出仅含安全 JSON 状态、固定请求模型、成功时的 token 计数或失败分类，不输出真实配置、响应正文或原始异常。请求仅在超时时按统一配置重试，不切换模型；只有完整、未拒绝、模型匹配且结构正确的响应才返回 `success` 和退出码 0，失败退出码为 1。

### Codex App Server 测试已移除

本项目已移除 Codex App Server 专用测试用例、JSON-RPC 客户端和冒烟驱动。`tests/test_mcp_registration.py` 等仍验证标准 MCP stdio 初始化及工具发现；这些结果不代表 Codex App Server 集成测试已运行或通过。

## Git commit 信息生成

需要起草提交信息时调用 `generate_git_commit_message`，提交本次选定 patch/hunk 的事实与来源，复用现有内容生成链路返回完整 `message`。经审阅并用 `check_commit_message` 检查后，才在独立授权及其他检查满足时提交。工具不读取 Git、不执行提交；用户已有完整提交信息时保留原文。详见 [提交信息生成与检查](skills/dev-workflow-standards/references/check-commit-message.md)。

## Issue/PR 多轮修订

新增 `start_issue_pr_draft`、`revise_issue_pr_draft`、`get_issue_pr_draft`、`close_issue_pr_draft`：由外层 Agent 每轮反馈，MCP 保存受限进程内上下文，仍使用 Responses API 和独立质量审查，不引入 Agents SDK。重启或 `/reload` 会丢失草稿；不写文件或 Memory，不自动发布。协议、容量、错误和最小示例见 [多轮草稿](skills/dev-workflow-standards/references/openai-workflow-tools.md#issuepr-多轮修订草稿)。

## 异步与指令迁移（#95 / #96）

OpenAI 工具通过 `AsyncOpenAI` 和 `httpx2.AsyncClient` 原生异步等待；MCP 名称、参数 Schema、注解和返回结构保持兼容，仍一次调用完成后返回。同步本地工具继续由 MCP 工作线程执行；异步服务中的阻塞 Git/gh 查询仅局部交给线程。审核、生成及质量审查保持数据依赖，不自动并行；取消停止后续阶段与重试，通过有界屏蔽清理释放客户端。

请求数据与 JSON Schema 在首次等待前固定，同一请求超时重试复用已审核内容；每次实际请求和重试仍重新读取当前两项环境配置。每次尝试独立创建/关闭客户端，不共享全局连接池；配置轮换后，任务内日志仍脱敏进行中请求的旧配置。审核自身只豁免递归语义审核，不豁免本地检测。

本次移除公开 `decide_skill_workflow` 及固定路由输入/返回字段；调用方直接按当前动作条件选择工具，没有替代路由 API。Python 直接调用联网服务的方法现在需要 `await`，独立脚本可在顶层使用 `asyncio.run`，不能在 MCP 请求内嵌套事件循环。已检查本仓库及可访问的 token-io-decoupling、Serena 源码，未发现这两个外部项目的直接调用；这不证明其他用户没有集成。发布/更新前，下游应迁移同步 Python 调用和已移除的路由接口，旧工作流路径需更新为 Hook 路径。

源码改动不自动安装发布包、更新已安装 Skill/全局 AGENTS 或重新加载 MCP；这些是独立动作。现有 `.githooks` 继续承担本地提交校验，与指令 Hooks 分开。
