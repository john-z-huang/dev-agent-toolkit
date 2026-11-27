# 安装与构建 Dev Agent Toolkit

## 首次安装

需要 Git 和 `uv`。发行包要求 Python 3.11 或更新版本，构建和安装由 uv 选择受管 Python。注册 Dev Agent Toolkit 的 MCP Server 时还需要选择一个支持 STDIO 的宿主。曾使用旧版的用户请从干净的宿主配置安装。

1. 获取源码。已有本地 checkout 时，可以跳过克隆。从本地源码仓库的根目录执行后续命令。

   ```bash
   /bin/bash -c 'git clone https://github.com/john-z-huang/dev-agent-toolkit.git'
   ```

2. 从源码仓库根目录构建并安装 MCP Server。构建产物放在 `dist/`，安装时选用与 Server 当前版本匹配的 wheel。

   ```bash
   /bin/bash ./dev-agent-toolkit --help
   /bin/bash ./dev-agent-toolkit --mcp-server-build
   /bin/bash ./dev-agent-toolkit --mcp-server-install
   /bin/bash -c 'uv tool list --show-paths && tool_bin=$(uv tool dir --bin) && "$tool_bin/dev-agent-toolkit" --help'
   ```

3. 安装 Skill 并检查状态。默认安装到 `~/.agents/skills/dev-agent-toolkit`。

   ```bash
   /bin/bash -c 'tool_bin=$(uv tool dir --bin) && "$tool_bin/dev-agent-toolkit" skills install && "$tool_bin/dev-agent-toolkit" skills show'
   ```

4. 选择宿主，将 MCP 服务注册为 `dev_agent_toolkit`。两个宿主均通过已安装的 `dev-agent-toolkit-tools` 可执行文件启动服务。

   - **Codex** 从仓库根目录运行以下命令。重载 MCP 或重新打开客户端，并在宿主中确认工具可用。

     ```bash
     /bin/bash ./dev-agent-toolkit --server dev_agent_toolkit
     /bin/bash -c 'exec codex mcp get dev_agent_toolkit'
     ```

   - **Pi** 从仓库根目录运行以下命令。已有会话用 `/reload` 重新加载，再通过工具发现确认服务可用。

     ```bash
     /bin/bash -c 'exec uv run --managed-python -- scripts/setup-pi-mcp.py'
     /bin/bash -c 'exec pi mcp list'
     ```

   离线工具可以直接使用。使用 OpenAI 工具前，给宿主进程配置非空的 `OPENAI_API_KEY` 和 `OPENAI_BASE_URL`。详见 [Codex 环境传递与排查](skills/dev-agent-toolkit/references/openai-workflow-tools.md#codex-stdio-环境传递与排查)和 [Pi 环境传递与时限](skills/dev-agent-toolkit/references/openai-workflow-tools.md#pi-stdio-环境传递与工具时限)。

5. 在宿主中调用只读工具 `get_mcp_server_build_info`，输入 `{}`，查看运行中的发行包版本。Codex 默认工具全名为 `mcp__dev_agent_toolkit__get_mcp_server_build_info`。也可通过已安装的管理命令执行同一个只读调用。

   ```bash
   /bin/bash -c 'tool_bin=$(uv tool dir --bin) && printf "%s\n" "{\"tool_name\":\"get_mcp_server_build_info\",\"arguments\":{}}" | "$tool_bin/dev-agent-toolkit" mcp'
   ```

## 构建与安装 MCP Server

`/bin/bash ./dev-agent-toolkit --mcp-server-build` 在仓库的 `dist/` 生成 Server 的 sdist 和 wheel。`/bin/bash ./dev-agent-toolkit --mcp-server-install` 默认安装与 Server 当前版本匹配的 wheel。重装时可加 `--force`，也可显式传入 wheel 路径和 `uv tool install` 选项。旧命令 `--uv-build` 和 `--uv-tool-install` 分别是这两个 Server 命令的别名。详细步骤见 [项目工具合同](skills/dev-agent-toolkit/hooks/install-tooling.md)。

## 独立 MCP Client

### 供 Codex 调用

从仓库根目录执行以下命令。安装会从当前源码刷新 uv tool，包括版本号未变化的情况，并验证 `dev_agent_toolkit_mcp_client_cli`。

```bash
/bin/bash ./dev-agent-toolkit --codex-mcp-client-install --dry-run
/bin/bash ./dev-agent-toolkit --codex-mcp-client-install
/bin/bash ./dev-agent-toolkit --mcp-client --help
```

强制重装时加 `--force`。也可直接执行安装脚本。

```bash
/bin/bash -c 'exec uv run --managed-python -- scripts/setup-codex-mcp-client.py'
```

Codex 通过终端运行 `dev_agent_toolkit_mcp_client_cli`，请求客户端注册表中的本地 STDIO 服务。Serena 和 `dev-agent-toolkit-tools` 的配置示例见 [登记下游服务](mcp-client/README.md#注册-server)。

### 从 wheel 安装

在 macOS 或 Linux 上，从仓库根目录构建并安装 `dev_agent_toolkit_mcp_client`，再通过启动器检查 CLI。

```bash
/bin/bash ./dev-agent-toolkit --mcp-client-build
/bin/bash ./dev-agent-toolkit --mcp-client-install
/bin/bash ./dev-agent-toolkit --mcp-client --help
```

构建后的 sdist 和 wheel 位于仓库的 `dist/`。`--mcp-client-install` 默认安装 Client 当前版本对应的 wheel，重装时可加 `--force`，也可显式传入 wheel 路径和 `uv tool install` 选项。`--mcp-client` 将后续参数转发给 uv 已安装的 Client，例如 `/bin/bash ./dev-agent-toolkit --mcp-client registry list`。Server 注册、请求参数和 Python API 见 [独立 MCP Client](mcp-client/README.md)。

## 独立安装 Skill

选择 `/bin/bash ./dev-agent-toolkit --skills-install` 或 `/bin/bash ./dev-agent-toolkit --skills-update`。默认目标为 `~/.agents/skills/dev-agent-toolkit`，也可选择独立的仓库外目录。见 [Skill 合同](skills/dev-agent-toolkit/hooks/install-skill.md)。

## 版本管理与更新全局 AGENTS.md

选择 `/bin/bash ./dev-agent-toolkit --agents-install` 或 `/bin/bash ./dev-agent-toolkit --agents-update`，从当前源码模板创建或更新用户的 `~/.codex/AGENTS.md`。见 [全局指令合同](skills/dev-agent-toolkit/hooks/install-global-agents.md)。

## 安装排查

### 发布包缺少 Skill 资源

先核对是否使用了完整 wheel 安装的管理 CLI。见 [Skill 命令入口排查](skills/dev-agent-toolkit/references/installation.md#包资源缺失与命令入口排查)。

### Codex 缺少 OpenAI 环境变量

检查服务的变量名转发、Codex 主进程是否具有非空变量以及是否已重载。见 [Codex stdio 环境排查](skills/dev-agent-toolkit/references/openai-workflow-tools.md#codex-stdio-环境传递与排查)。
