# 构建与安装项目工具

## 进入条件

用户要求构建 MCP Server 或 MCP Client 发行包、授权刷新对应的 uv tool，或要求登记已安装的本地服务时使用。日常项目 MCP 调用复用已配置的 [本地 MCP Client](../references/mcp-tools.md#通过本地-mcp-client-调用)。更新已安装 Skill 或全局指令时按 [安装与更新索引](index.md#安装与更新) 执行。

## 执行条件

核对源码 checkout、目标项目的 `pyproject.toml` 版本及 `uv tool dir --bin` 对应的安装环境。构建写入仓库的 `dist/`，安装写入 uv tool 环境。构建或解析依赖可能联网。在源码根目录按目标项目选择命令。

### MCP Server

```bash
/bin/bash ./dev-agent-toolkit --mcp-server-build
/bin/bash ./dev-agent-toolkit --mcp-server-install
```

旧命令 `--uv-build` 和 `--uv-tool-install` 分别是 Server 构建与安装命令的别名。

### MCP Client

```bash
/bin/bash ./dev-agent-toolkit --mcp-client-build
/bin/bash ./dev-agent-toolkit --mcp-client-install
```

两个安装命令都默认使用 `dist/` 中与所选项目及其当前版本匹配的 wheel。缺少对应 wheel 时，安装命令会提示先构建所选项目。更新或重装同版本 wheel 时，在对应安装命令后加 `--force`。指定其他 wheel 时，传入 uv 选项和 wheel 路径。显式相对路径以调用目录为准。

供 Codex 通过终端调用时，可用 `/bin/bash ./dev-agent-toolkit --codex-mcp-client-install` 从当前源码刷新 uv tool 并验证 `dev_agent_toolkit_mcp_client_cli`。可用 `--dry-run` 预览，或用 `--force` 强制重装。通过 `/bin/bash ./dev-agent-toolkit --mcp-client --help` 查看 CLI 用法。

每次将一个操作参数放在首位。`/bin/bash ./dev-agent-toolkit` 无参数只打印帮助。可在所选操作后加 `--help`。从其他目录调用时用 `dev-agent-toolkit` 的绝对路径，保持入口和源码组件的相对布局。Skill 和全局指令预览依赖已安装的管理 CLI。选择安装前核对它的来源。

### 登记本地服务

先核对客户端中的服务 ID 和已安装可执行文件的绝对路径。将启动路径、参数及所需工作目录作为配置对象传给 `registry add <服务 ID>`。已有匹配注册项时直接复用，获准修改时用 `registry update <服务 ID>`。启动配置只包含运行服务所需的参数和路径，凭据由 [进程环境](../references/openai-workflow-tools.md#本地-mcp-client-环境传递与排查) 提供。用 `registry get` 回读，再通过客户端确认工具可发现。

## 离开条件

构建后核对 wheel 和 sdist 路径及版本。安装后用 `uv tool list --show-paths` 确认实际版本和入口，按目标验证入口。安装完成只证明 uv tool 环境已更新。发生部分成功时按 [恢复](recovery.md) 核对已生成产物及已安装版本。

按 [调用已更新的本地 MCP](updated-local-mcp.md) 通过现有客户端注册项验证新版入口和工具 Schema。

## 重新进入条件

源码 checkout、版本、wheel、uv tool 环境或安装范围变化时，复核受影响部分。
