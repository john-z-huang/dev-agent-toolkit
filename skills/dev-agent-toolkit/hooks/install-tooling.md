# 构建与安装项目工具

## 进入条件

需要构建 MCP Server 或 MCP Client 发行包，或只刷新对应的 uv tool。若目标是更新已安装 Skill、全局指令或 Codex 中的 MCP Server 注册，直接使用 [对应合同](index.md)。

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

供 Codex 通过终端调用时，可用 `/bin/bash ./dev-agent-toolkit --codex-mcp-client-install` 从当前源码刷新 MCP Client 的 uv tool 并验证 CLI。可用 `--dry-run` 预览，或用 `--force` 强制重装。通过 `/bin/bash ./dev-agent-toolkit --mcp-client --help` 查看客户端用法。

每次将一个操作参数放在首位。`/bin/bash ./dev-agent-toolkit` 无参数只打印帮助。可在所选操作后加 `--help`。从其他目录调用时用 `dev-agent-toolkit` 的绝对路径，保持入口和源码组件的相对布局。Skill 和全局指令预览依赖已安装的管理 CLI。选择安装前核对它的来源。

## 离开条件

构建后核对 wheel 和 sdist 路径及版本。安装后用 `uv tool list --show-paths` 确认实际版本和入口，按目标验证入口。安装完成只证明 uv tool 环境已更新。发生部分成功时按 [恢复](recovery.md) 核对已生成产物及已安装版本。

Codex 当前连接仍旧且本次需要新版离线只读方法时，按 [更新后临时本地 MCP](updated-local-mcp.md) 使用已核实的新入口。

## 重新进入条件

源码 checkout、版本、wheel、uv tool 环境或安装范围变化时，复核受影响部分。
