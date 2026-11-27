# 安装与构建 Dev Agent Toolkit

## 首次安装

需要 Git 和 `uv`。发行包要求 Python 3.11 或更新版本，构建和安装由 uv 选择受管 Python。Code Agent 通过 MCP Client CLI 调用已安装的本地 STDIO 服务。

1. 获取源码。已有本地 checkout 时，可以跳过克隆。从本地源码仓库的根目录执行后续命令。

   ```bash
   /bin/bash -c 'git clone https://github.com/john-z-huang/dev-agent-toolkit.git'
   ```

2. 安装 Skill 并检查状态。默认安装到 `~/.agents/skills/dev-agent-toolkit`。也可在此时[安装全局 AGENTS.md](#版本管理与更新全局-agentsmd)。文档操作用现有 Python 直接读取 checkout。

   ```bash
   /bin/bash ./dev-agent-toolkit --skills-install
   /bin/bash ./dev-agent-toolkit --skills-show
   ```

3. 需要使用项目 MCP 工具时，从源码仓库根目录构建并安装 MCP Server。构建产物放在 `dist/`，安装时选用与 Server 当前版本匹配的 wheel。

   ```bash
   /bin/bash ./dev-agent-toolkit --help
   /bin/bash ./dev-agent-toolkit --mcp-server-build
   /bin/bash ./dev-agent-toolkit --mcp-server-install
   /bin/bash -c 'uv tool list --show-paths && tool_bin=$(uv tool dir --bin) && "$tool_bin/dev-agent-toolkit" --help'
   ```

4. 安装 [MCP Client CLI](#独立-mcp-client)，将已安装的 `dev-agent-toolkit-tools` 登记到客户端注册表。用 `uv tool dir --bin` 核对实际可执行文件路径，在客户端中登记为 `dev-agent-toolkit-tools`，或复用已有服务 ID。配置示例见 [登记下游服务](mcp-client/README.md#注册-server)。

5. 通过客户端调用只读工具，核对实际处理请求的服务版本。已有注册项使用其实际服务 ID。

   ```bash
   /bin/bash -c 'exec dev_agent_toolkit_mcp_client_cli registry list'
   /bin/bash -c 'exec dev_agent_toolkit_mcp_client_cli call dev-agent-toolkit-tools get_mcp_server_build_info'
   ```

   使用 OpenAI 工具时，启动 CLI 的进程须提供非空的 `OPENAI_API_KEY` 和 `OPENAI_BASE_URL`。详见 [客户端环境传递与排查](skills/dev-agent-toolkit/references/openai-workflow-tools.md#本地-mcp-client-环境传递与排查)。

## 构建与安装 MCP Server

`/bin/bash ./dev-agent-toolkit --mcp-server-build` 在仓库的 `dist/` 生成 Server 的 sdist 和 wheel。`/bin/bash ./dev-agent-toolkit --mcp-server-install` 默认安装与 Server 当前版本匹配的 wheel。重装时可加 `--force`，也可显式传入 wheel 路径和 `uv tool install` 选项。旧命令 `--uv-build` 和 `--uv-tool-install` 分别是这两个 Server 命令的别名。详细步骤见 [项目工具合同](skills/dev-agent-toolkit/hooks/install-tooling.md)。

## 独立 MCP Client

### 从源码安装 CLI

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

Code Agent 在终端运行 `dev_agent_toolkit_mcp_client_cli`，通过客户端注册表调用本地 STDIO 服务。Serena 和 `dev-agent-toolkit-tools` 的配置示例见 [登记下游服务](mcp-client/README.md#注册-server)。

### 从 wheel 安装

在 macOS 或 Linux 上，从仓库根目录构建并安装 `dev_agent_toolkit_mcp_client`，再通过启动器检查 CLI。

```bash
/bin/bash ./dev-agent-toolkit --mcp-client-build
/bin/bash ./dev-agent-toolkit --mcp-client-install
/bin/bash ./dev-agent-toolkit --mcp-client --help
```

构建后的 sdist 和 wheel 位于仓库的 `dist/`。`--mcp-client-install` 默认安装 Client 当前版本对应的 wheel，重装时可加 `--force`，也可显式传入 wheel 路径和 `uv tool install` 选项。`--mcp-client` 将后续参数转发给 uv 已安装的 Client，例如 `/bin/bash ./dev-agent-toolkit --mcp-client registry list`。Server 注册、请求参数和 Python API 见 [独立 MCP Client](mcp-client/README.md)。

## 独立安装 Skill

选择 `/bin/bash ./dev-agent-toolkit --skills-install` 或 `/bin/bash ./dev-agent-toolkit --skills-update`。启动器通过 `uv` 查找现有 Python 3.11 或更新版本，从源码管理文档。用 `--skills-show` 回读状态。默认目标为 `~/.agents/skills/dev-agent-toolkit`，也可通过 `--target` 选择独立的仓库外目录。见 [Skill 合同](skills/dev-agent-toolkit/hooks/install-skill.md)。

## 版本管理与更新全局 AGENTS.md

选择 `/bin/bash ./dev-agent-toolkit --agents-install` 或 `/bin/bash ./dev-agent-toolkit --agents-update`，从当前源码模板创建或更新用户的 `~/.codex/AGENTS.md`。用 `--dry-run` 预览，用 `--agents-show` 回读。见 [全局指令合同](skills/dev-agent-toolkit/hooks/install-global-agents.md)。

## 安装排查

### 发布包缺少 Skill 资源

先核对是否使用了完整 wheel 安装的管理 CLI。见 [Skill 命令入口排查](skills/dev-agent-toolkit/references/installation.md#包资源缺失与命令入口排查)。

### CLI 缺少 OpenAI 环境变量

检查启动 CLI 的进程是否持有非空变量，以及实际服务声明的变量名。环境变更后使用新会话。见 [客户端环境传递与排查](skills/dev-agent-toolkit/references/openai-workflow-tools.md#本地-mcp-client-环境传递与排查)。
