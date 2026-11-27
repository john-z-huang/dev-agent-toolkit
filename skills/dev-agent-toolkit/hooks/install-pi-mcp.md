# 安装、更新或注册 Pi MCP

## 进入条件

需要让 Pi Code Agent 加载已安装的 stdio MCP，或从本仓库刷新软件包与 Pi 注册。

## 执行条件

核实 `uv` 和支持原生 `pi mcp add` 的 `pi` 位于 PATH。默认注册名为 `dev_agent_toolkit`，启动入口为 uv tool 安装的 `dev-agent-toolkit-tools`。默认写用户级 `~/.pi/agent/mcp.json`。使用 `--local` 时，从目标项目目录运行，并通过脚本绝对路径明确源码；写入目标为调用目录的 `.pi/mcp.json`，需 Pi 信任该项目后才加载。写入会通过 `pi mcp add` 替换同名条目，包括其自定义环境、超时及暴露设置。先核对现有条目，在获准范围内保留所需设置、改用其他服务名或执行替换。

在源码仓库使用下列对应命令，或改用脚本绝对路径。

| 意图 | 命令 |
| --- | --- |
| 预览安装和注册计划 | `/bin/bash -c 'exec uv run --managed-python -- scripts/setup-pi-mcp.py --install --dry-run'` |
| 给 Pi 注册已安装工具 | `/bin/bash -c 'exec uv run --managed-python -- scripts/setup-pi-mcp.py'` |
| 从当前源码安装并注册 | `/bin/bash -c 'exec uv run --managed-python -- scripts/setup-pi-mcp.py --install'` |
| 强制重新安装并更新注册 | `/bin/bash -c 'exec uv run --managed-python -- scripts/setup-pi-mcp.py --install --force'` |

预览不运行安装或注册子命令，不读写目标配置。`--install` 只安装本仓库的 MCP，可能联网。注册其他已安装且无需启动参数的 stdio 服务可用 `--server NAME --command EXECUTABLE`；脚本通过 `uv tool dir --bin` 选择绝对入口。`--exposure` 默认 `codemode`，可选 `deferred`、`direct`、`hidden`。使用非原生 MCP 扩展时先核实其配置方式。

例如，从目标项目目录把已安装工具注册为项目级服务，并按需延后工具暴露。

```bash
/bin/bash -c 'exec uv run --managed-python -- "$1" --local --exposure deferred' _ '/absolute/path/to/source/scripts/setup-pi-mcp.py'
```

Pi stdio 继承启动环境，使用 `timeout`（秒）。按需让 Pi 主进程持有非空的 `OPENAI_API_KEY`、`OPENAI_BASE_URL` 和所需代理变量。[Pi 环境传递和工具发现](../references/openai-workflow-tools.md#pi-stdio-环境传递与工具时限) 说明时限与 codemode 行为。Codex 全局指令、原生 Hooks 和 `env_vars` 属于 Codex。

## 离开条件

核对实际安装版本、Pi 注册作用域、入口与 exposure。按需运行 `pi mcp list` 核对连接，此命令会连接已启用服务。已有 Pi 会话用 `/reload`，按当前 exposure 核对工具发现。安装与注册分别生效，后续阶段失败时先回读已有结果。

## 重新进入条件

Pi 配置作用域、服务名、exposure、源码、安装版本或宿主发生变化时，重新核对对应部分。
