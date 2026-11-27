# 注册 Codex MCP Server 或修复环境变量转发

## 进入条件

需要在 Codex 注册 `dev_agent_toolkit`，或修复已注册服务的环境变量转发。Pi 使用 [Pi MCP 合同](install-pi-mcp.md)。

## 执行条件

确认源码 checkout、uv tool 目录、预期服务名和 Codex 配置路径。默认服务名为 `dev_agent_toolkit`，启动入口为 uv tool 安装的 `dev-agent-toolkit-tools`。默认写 `$CODEX_HOME/config.toml`，没有设置 `CODEX_HOME` 时写 `~/.codex/config.toml`。需要 `uv`；注册需要 `codex`。在核实的源码根目录按意图选择一条命令。

需要安装或更新 MCP Server 时，先按 [项目工具](install-tooling.md#mcp-server) 构建并安装对应的 wheel，再检查 Codex 注册。

| 意图 | 命令 |
| --- | --- |
| 预览注册和转发计划 | `/bin/bash ./dev-agent-toolkit --server dev_agent_toolkit --dry-run` |
| 注册已安装的 MCP Server 并配置转发 | `/bin/bash ./dev-agent-toolkit --server dev_agent_toolkit` |
| 预览或修复已注册服务的转发 | `/bin/bash ./dev-agent-toolkit --env-only --dry-run` 或 `/bin/bash ./dev-agent-toolkit --env-only` |

注册预览只显示计划。修复预览读取并校验已有注册项。

`--server NAME` 选择服务，`--config PATH` 指定配置文件（注册时文件名必须是 `config.toml`），`--executable PATH` 显式选择已安装的绝对入口。注册匹配时直接复用；实际冲突时审阅现有条目，获准替换后才传 `--replace`。替换保留通用审批、工具策略和超时设置。无效 TOML、链接、特殊文件、变量远端来源冲突或并发修改时保留现场。`dev-agent-toolkit` 将这些选项转发给仓库内的 `scripts/setup-codex-mcp.py`。

只合并环境变量名称，包括 `OPENAI_API_KEY`、`OPENAI_BASE_URL`、`OPENAI_TIMEOUT_MAX_RETRIES` 和标准代理变量的大小写名称。校验和回读时只检查名称与存在性，避免输出配置值。Codex 主进程实际持有非空的 Key 和 Base URL 后，子进程才能使用转发变量。配置不会主动加载 Shell 初始化文件或 `.env`。按 [环境传递与时限](../references/openai-workflow-tools.md#codex-stdio-环境传递与排查) 排查 `missing_api_key` 和 `missing_base_url`。保留用户的审批策略，用户明确选择写入确认时使用对应服务的 `default_tools_approval_mode = "writes"`。该设置由 Codex 执行。

## 离开条件

核对安装版本、实际启动路径、目标服务和转发名称。重载 Codex MCP，缺少重载能力时重新打开客户端。需验证服务可用时，通过标准 MCP 初始化和工具发现或客户端实际工具发现核对，使用最小只读调用；真实 OpenAI 请求需要独立授权。安装、注册和转发是独立阶段，后续失败时先回读已发生的变更。

暂时保留当前旧连接且需要新版离线只读方法时，按 [更新后临时本地 MCP](updated-local-mcp.md) 处理。

## 重新进入条件

服务名、路径、配置、入口、环境转发、来源或宿主变化时，重新核对对应部分。
