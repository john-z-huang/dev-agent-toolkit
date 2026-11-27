# 仓库结构与开发流程

本文件说明本仓库的目录、启动器入口和若干历史实现决定。用户安装与使用说明见 [安装与构建指南](../INSTALL.md)。

## 目录结构

- `skills/dev-agent-toolkit/SKILL.md`：唯一 Skill 入口、共用边界及按需条件索引。
- `skills/dev-agent-toolkit/hooks/`：独立动作的进入、执行、离开及重新核验条件。
- `skills/dev-agent-toolkit/references/`：按需加载的决策细节、独立安装说明和 MCP 工具映射。
- `mcp-server/`：Python/uv MCP v2 stdio 服务和固定操作工具。
- `instructions/codex-global.md`：版本化的全局指令源；通过独立 CLI 显式同步到用户目录。
- `archive/mcp-server-ts/`：已归档且不再支持的历史 TypeScript MCP 实现；其历史说明见该目录的 [`README.md`](../archive/mcp-server-ts/README.md)。
- `scripts/`：Codex 安装配置脚本，以及供标准 Git Hook 集成使用的可移植校验资产；`.githooks/`：Hook 入口。
- `.agents/`：本目录，仅用于开发和维护本仓库，不随发行包交付。

当前 MCP 服务实现与调用约束见 [`mcp-server/pyproject.toml`](../mcp-server/pyproject.toml) 和 [`references/mcp-tools.md`](../skills/dev-agent-toolkit/references/mcp-tools.md)。

## 启动器入口

仓库根的 `dev-agent-toolkit` 是构建与安装入口，所有实现路径都相对脚本所在目录解析，不依赖调用者的工作目录：

- `--uv-build`：调用 `uv build mcp-server --out-dir dist`。
- `--uv-tool-install [--force]`：安装 `dist/` 中与项目版本匹配的 wheel。
- `--skills-install|--skills-update|--agents-install|--agents-update`：先重建并刷新 `dev-agent-toolkit-tools` uv tool，再调用已安装的 `dev-agent-toolkit` 管理命令；`--agents-*` 固定传入 `--source instructions/codex-global.md`，调用方仍可用后面的 `--source` 覆盖。
- `--mcp-install|--mcp-update`：转发到 `scripts/setup-codex-mcp.py`。
- `--hooks-install|--hooks-update`：转发到 `scripts/setup-codex-hooks.py`。

`--help` 与 `--dry-run` 预览跳过构建和工具刷新。交付边界与硬编码路径见 [交付边界与发行包](distribution.md)。

## 异步与指令迁移（#95 / #96）

以下内容记录当时的实现决定，保留作为历史背景。

OpenAI 工具通过 `AsyncOpenAI` 和 `httpx2.AsyncClient` 原生异步等待；MCP 名称、参数 Schema、注解和返回结构保持兼容，仍一次调用完成后返回。同步本地工具继续由 MCP 工作线程执行；异步服务中的阻塞 Git/gh 查询仅局部交给线程。审核、生成及质量审查保持数据依赖，不自动并行；取消停止后续阶段与重试，通过有界屏蔽清理释放客户端。

请求数据与 JSON Schema 在首次等待前固定，同一请求超时重试复用已审核内容；每次实际请求和重试仍重新读取当前两项环境配置。每次尝试独立创建/关闭客户端，不共享全局连接池；配置轮换后，任务内日志仍脱敏进行中请求的旧配置。审核自身只豁免递归语义审核，不豁免本地检测。

本次移除公开 `decide_skill_workflow` 及固定路由输入/返回字段；调用方直接按当前动作条件选择工具，没有替代路由 API。Python 直接调用联网服务的方法现在需要 `await`，独立脚本可在顶层使用 `asyncio.run`，不能在 MCP 请求内嵌套事件循环。已检查本仓库及可访问的 token-io-decoupling、Serena 源码，未发现这两个外部项目的直接调用；这不证明其他用户没有集成。发布/更新前，下游应迁移同步 Python 调用和已移除的路由接口，旧工作流路径需更新为 Hook 路径。

源码改动不自动安装发布包、更新已安装 Skill/全局 AGENTS 或重新加载 MCP；这些是独立动作。现有 `.githooks` 继续承担本地提交校验，与指令 Hooks 分开。
