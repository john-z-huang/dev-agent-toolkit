# 独立 MCP Client

`dev-agent-toolkit-mcp` 在 macOS 和 Linux 上按需启动本地 STDIO MCP Server。Shell、脚本和 Code Agent 使用同一个 CLI，Python 程序可以通过 `dev_agent_toolkit_tools.mcp_client` 使用同一套请求和会话逻辑。安装项目发行包后即可使用 CLI。 [安装与构建](../INSTALL.md#独立-mcp-client)

## 注册 Server

默认注册表为 `$XDG_CONFIG_HOME/dev-agent-toolkit/mcp-servers.json`，未设置时使用 `~/.config/dev-agent-toolkit/mcp-servers.json`。`--registry` 可指定独立文件。仅注册可信的可执行文件。`allowed_tools` 由用户列出获准的只读工具，默认列表为空。

例如，将配置保存为 `server.json`，填入已安装 Server 的路径与参数，并把 `lookup` 改成该 Server 的只读工具名。

```json
{
  "transport": "stdio",
  "command": "/absolute/path/to/mcp-server",
  "args": [],
  "allowed_tools": ["lookup"]
}
```

```bash
/bin/bash -c 'exec dev-agent-toolkit-mcp registry add local --file "$1"' _ 'server.json'
/bin/bash -c 'exec dev-agent-toolkit-mcp server info local'
/bin/bash -c 'exec dev-agent-toolkit-mcp request local tools/list'
/bin/bash -c 'exec dev-agent-toolkit-mcp request local tools/schema --json "$1"' _ '{"name":"lookup"}'
```

- `registry list` 列出 Server ID。`registry get` 显示配置和环境变量名。`registry update` 使用完整配置替换该项，`registry remove` 删除该项。
- `cwd` 可指定绝对工作目录，默认使用创建会话时的工作目录。`env` 可以为 Server 显式设置环境变量并保存到用户注册表。Server 进程会收到基本环境和显式配置的变量。
- `startup_timeout`、`request_timeout`、`input_timeout`、`idle_timeout` 和 `max_session_age` 的单位为秒，默认分别为 15、120、60、60 和 3600。执行中和等待输入期间，空闲计时暂停。
- 更新只影响新会话。删除会使旧会话拒绝尚未发出的请求。已经发出的请求可以完成，同名重新注册会得到新的身份。

## 执行请求

`request <server> <method>` 执行一次并回收连接及进程。`batch <server>` 接收 `[{"method":"tools/list"}, {"method":"tools/call","params":{"name":"lookup"}}]`，在同一连接顺序执行，首次失败时保留已完成结果并返回跳过数量。`--json`、`--stdin` 和 `--file` 接收请求参数或批量数组。

`session open <server>` 返回 `session_id`，首次请求时启动 Server。使用 `session request <id> <method>` 发起后续请求，`session status <id>` 查看状态与待答输入，`session cancel <id>` 取消正在执行的请求，`session close <id>` 停止会话并回收进程。每个显式会话拥有独立的临时 Worker 与用户私有 Unix socket。请求进程断连时取消当前工作，空闲到期、总寿命到期或主动关闭时回收 Worker 及 Server。进程树回收覆盖 Server 和留在受管进程组的后代。

每条命令默认输出一个带 `schema_version` 的 JSON 结果。成功时退出码为 `0`，操作失败为 `1`，CLI 参数、JSON 或配置输入错误为 `2`，中断为 `130`。`tools/call` 返回 `isError` 时保留原结果并附 `tool_error`。JSON-RPC 错误带 `rpc_code`。发出调用后断连或超时且结果无法得知时标记 `outcome_unknown`。`--events` 放在子命令前，以 JSON Lines 输出工具调用进度、通知、输入请求、Tasks 状态及最终结果，诊断走 stderr。

显式会话需要提交输入时，从事件流或 `session status` 取得 `input_id`，再从另一个终端执行 `session respond <id>` 并提供 `{"input_id":"…","response":{"action":"accept","content":{"label":"示例"}}}`。使用 `decline` 或 `cancel` 可以拒绝或取消表单输入。

## Python API

```python
from dev_agent_toolkit_tools.mcp_client import Registry, open_session


async def discover(registry_path):
    registry = Registry(registry_path)
    async with open_session(registry, "local") as session:
        info = await session.request("server/info")
        page = await session.request("tools/list")
        return info, page
```

`Registry` 提供 `list`、`get`、`add`、`update` 和 `remove`，写入配置时使用 `ServerConfig`。`execute`、`execute_batch` 分别执行单次调用与批量调用。`open_session` 支持协程回调 `on_event` 和 `on_input`。`Session.request` 返回原协议结果，协议和客户端错误通过带 `code` 的 `ClientError` 报告。调用方可关闭会话，或取消正在等待请求的异步任务。

## 协议支持矩阵

| STDIO 协议版本 | 连接和标准请求 | 交互与扩展 |
| --- | --- | --- |
| `2025-11-25` | `initialize`、`ping`、Tools、Resources、Prompts、Completion、旧版资源订阅和日志级别 | 进度、取消、服务端发起的 Elicitation、Roots 和 Sampling |
| `2026-07-28` | `server/discover`、逐请求版本与能力声明、Tools、Resources、Prompts、Completion、`subscriptions/listen` | 进度、取消、通过 MRTR 处理追加输入，可选 Tasks 轮询、输入和取消 |

默认 `mode` 为 `auto`。对需要旧版握手的服务可以设置 `legacy`。`server info` 展示实际协商的版本和服务端声明。`tools/list`、`resources/list`、`resources/templates/list` 和 `prompts/list` 接受 `cursor` 并保留 `nextCursor`，`tools/schema` 会翻页寻找指定工具。

可选能力默认关闭。将 `elicitation` 或 `sampling` 设为 `true` 并提供输入处理器，或使用显式 CLI 会话处理表单和 Sampling 应答。`roots` 指定允许公开的绝对路径。`tasks` 仅适用于双方声明支持 `io.modelcontextprotocol/tasks` 的新版连接。旧版实验性 Tasks、其他协议版本和网络传输当前不在支持矩阵内。

离线测试覆盖双版本工具和能力发现、分页、资源、提示词、补全、多轮输入、进度和取消、配置热更新、会话隔离、子进程回收，以及新版 Tasks 和订阅。
