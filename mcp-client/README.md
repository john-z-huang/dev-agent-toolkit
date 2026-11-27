# dev_agent_toolkit_mcp_client

`dev_agent_toolkit_mcp_client` 是面向本地 STDIO MCP Server 的客户端，支持 macOS、Linux 和 Python 3.11 及更新版本。Shell、脚本和 Code Agent 通过 `dev_agent_toolkit_mcp_client_cli` 发起请求。Python 程序可导入同名发行包的客户端 API，两种方式共用注册表和请求逻辑。

## 安装

在本项目目录执行以下命令，安装并验证 CLI。旧版本中以 `dev_agent_toolkit_mcp_client` 开头的 CLI 命令须换用 `dev_agent_toolkit_mcp_client_cli`。

```bash
/bin/bash -c 'exec uv tool install --managed-python .'
/bin/bash -c 'exec dev_agent_toolkit_mcp_client_cli --help'
```

使用 Python API 时，在调用方的 Python 环境中安装 `dev_agent_toolkit_mcp_client` 发行包，再从同名包导入。

也可以从完整源码仓库的根目录刷新已有 uv tool 安装。加 `--dry-run` 可预览，加 `--force` 可强制重装。

```bash
/bin/bash ./dev-agent-toolkit --codex-mcp-client-install
/bin/bash ./dev-agent-toolkit --mcp-client --help
```

也可从仓库根目录使用启动器构建 wheel、安装并运行 Client。

```bash
/bin/bash ./dev-agent-toolkit --mcp-client-build
/bin/bash ./dev-agent-toolkit --mcp-client-install
/bin/bash ./dev-agent-toolkit --mcp-client --help
```

## 注册 Server

默认注册表为 `$XDG_CONFIG_HOME/dev-agent-toolkit/mcp-servers.json`，未设置时使用 `~/.config/dev-agent-toolkit/mcp-servers.json`。`--registry` 可指定独立文件。只注册可信的可执行文件。已有注册表可直接读取，旧字段 `allowed_tools`、`env` 和 `env_vars` 会被忽略，下次写入注册表时移除。

例如，将配置保存为 `server.json`，填入已安装 Server 的路径与参数。运行下方命令时，把示例中的 `lookup` 改成目标工具名。

```json
{
  "transport": "stdio",
  "command": "/absolute/path/to/mcp-server",
  "args": []
}
```

```bash
/bin/bash -c 'exec dev_agent_toolkit_mcp_client_cli registry add local --file "$1"' _ 'server.json'
/bin/bash -c 'exec dev_agent_toolkit_mcp_client_cli server info local'
/bin/bash -c 'exec dev_agent_toolkit_mcp_client_cli request local tools/list'
/bin/bash -c 'exec dev_agent_toolkit_mcp_client_cli request local tools/schema --json "$1"' _ '{"name":"lookup"}'
/bin/bash -c 'exec dev_agent_toolkit_mcp_client_cli call local lookup'
```

对于 uv tool 安装的服务，先用 `uv tool dir --bin` 查询可执行文件目录，把下表中命令的绝对路径填到 `command`。按上面的命令登记为各自的服务 ID。

| 服务 ID 示例 | 可执行文件 | `args` |
| --- | --- | --- |
| `serena` | `serena` | `["start-mcp-server", "--context", "codex", "--project-from-cwd", "--open-web-dashboard", "false"]` |
| `dev_agent_toolkit` | `dev-agent-toolkit-tools` | `[]` |

按项目使用 Serena 时，可在配置中把 `cwd` 设为项目绝对路径。

- `registry list` 列出 Server ID。`registry get` 显示启动配置。`registry update` 使用完整配置替换该项，`registry remove` 删除该项。
- `cwd` 可指定绝对工作目录，默认使用创建会话时的工作目录。
- `startup_timeout`、`request_timeout`、`input_timeout`、`idle_timeout` 和 `max_session_age` 的单位为秒，默认分别为 15、120、60、60 和 3600。执行中和等待输入期间，空闲计时暂停。
- 更新只影响新会话。删除会使旧会话拒绝尚未发出的请求。已经发出的请求可以完成，同名重新注册会得到新的身份。

### 服务环境发现

客户端先在基础 STDIO 环境中查找服务公布的只读工具 `get_mcp_environment`。支持此约定的服务应接受空参数，并在 MCP 工具响应的 `structuredContent` 中返回变量名。

```json
{
  "names": ["MY_SERVICE_TOKEN"]
}
```

发现工具须能在基础 STDIO 环境中完成查询。客户端从自己的进程环境读取声明的名称，跳过未设置的变量并保留已设置的空字符串。取到值时，客户端关闭初始连接并带着这些值启动处理请求的进程。服务未公布该工具或没有取到值时，客户端复用初始连接。变量值只供该下游进程使用，无需写入注册表。

`dev-agent-toolkit-tools` 的发现工具会返回 OpenAI 凭据、端点、重试和代理所需的变量名。持久会话从执行 `session open` 的进程继承环境。变量值变化后，开启新会话可让下游取到新值。

## 执行请求

`call <server> <tool>` 直接调用已登记服务的工具。省略参数时使用空对象。重复传入 `--arg NAME VALUE` 可设置字符串参数，有数字、布尔值或嵌套对象时，用 `--json`、`--stdin` 或 `--file` 直接传入工具参数对象。

```bash
/bin/bash -c 'exec dev_agent_toolkit_mcp_client_cli call serena get_current_config'
/bin/bash -c 'exec dev_agent_toolkit_mcp_client_cli call serena get_symbols_overview --arg relative_path "$1"' _ 'src/app.py'
```

`request <server> <method>` 适用于直接发出 MCP 方法请求。`call` 和 `request` 默认执行一次并回收连接及进程。加 `--session <id>` 可复用指定会话的下游连接。

`session open <server>` 返回 `session_id`，首次请求时启动 Server。使用 `call` 或 `request` 加 `--session <id>` 发起后续请求，也可以用 `session request <id> <method>`。`--session` 要求与创建会话时使用同一注册表和服务 ID。会话关闭或过期时，请求会返回会话错误。

使用 `session status <id>` 查看状态与待答输入，`session cancel <id>` 取消正在执行的请求，`session close <id>` 停止会话并回收进程。每个显式会话拥有独立的临时 Worker 与用户私有 Unix socket。请求进程断连时取消当前工作，空闲到期、总寿命到期或主动关闭时回收 Worker 及 Server。进程树回收覆盖 Server 和留在受管进程组的后代。

对 Serena，先执行 `session open serena`，随后在同一个 CLI 会话里调用 `initial_instructions`、`activate_project` 和需要该项目的工具。`activate_project` 的 `arguments.session` 使用 Serena 返回的会话标识，CLI 的 `--session` 使用 `session open` 返回的 `session_id`。

分页时也保留同一个 CLI 会话。以下示例从第一页的 `result.nextCursor` 取得游标，作为下一页请求的 `cursor`。

```bash
/bin/bash -c 'exec dev_agent_toolkit_mcp_client_cli request local tools/list --session "$1"' _ '<session_id>'
/bin/bash -c 'exec dev_agent_toolkit_mcp_client_cli request local tools/list --session "$1" --json "$2"' _ '<session_id>' '{"cursor":"<nextCursor>"}'
```

### 用 JSON 执行多步调用

`batch <server>` 从 `--json`、`--stdin` 或 `--file` 读取步骤数组，在同一连接中按顺序执行，退出时关闭该连接。每步使用 `tool` 和可选的 `arguments`，或者使用 `method` 和可选的 `params`。

`bind` 将前面某一步返回的数据填入此步的参数。每个绑定的 `path` 以从零开始的步骤序号开头，从该步的 `result` 读取。用字符串访问对象字段，用从零开始的数字访问数组元素。绑定保留原来的 JSON 类型。设定 `between` 时，从文本中取第一个起始标记和其后第一个结束标记之间的内容。

例如，在已登记的 Serena 中切换到指定项目并查看活动配置。将 `project` 替换为目标项目的绝对路径。

```bash
/bin/bash -c 'exec dev_agent_toolkit_mcp_client_cli batch serena --stdin' <<'JSON'
[
  {"tool":"initial_instructions"},
  {"tool":"activate_project","arguments":{"project":"/absolute/path/to/project"},
   "bind":{"session":{"path":[0,"content",0,"text"],"between":["Your Serena session id is `","`"]}}},
  {"tool":"get_current_config"}
]
JSON
```

分页也可以直接组成两步。在可分页的服务上，用 `[{"method":"tools/list"},{"method":"tools/list","bind":{"cursor":{"path":[0,"nextCursor"]}}}]` 获取前两页。

批处理先校验步骤结构和绑定来源。绑定的参数名必须与该步骤的固定参数不同。调用失败、字段缺失或文本标记不匹配时，结果保留已完成步骤，以及失败步骤和跳过数量。

每条命令默认输出一个带 `schema_version` 的 JSON 结果。成功时退出码为 `0`，操作失败为 `1`，CLI 参数、JSON 或配置输入错误为 `2`，中断为 `130`。`tools/call` 返回 `isError` 时保留原结果并附 `tool_error`。JSON-RPC 错误带 `rpc_code`。发出调用后断连或超时且结果无法得知时标记 `outcome_unknown`，应先核实下游状态再考虑重试。`--events` 放在子命令前，以 JSON Lines 输出工具调用进度、通知、输入请求、Tasks 状态及最终结果，诊断走 stderr。

显式会话需要提交输入时，从事件流或 `session status` 取得 `input_id`，再从另一个终端执行 `session respond <id>` 并提供 `{"input_id":"…","response":{"action":"accept","content":{"label":"示例"}}}`。使用 `decline` 或 `cancel` 可以拒绝或取消表单输入。

## Python API

```python
from dev_agent_toolkit_mcp_client import Registry, open_session


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

## 开发与构建

在本项目的源码目录执行以下命令。发行包写入项目的 `dist/`。

```bash
/bin/bash -c 'exec uv run --locked -- python -m unittest discover -s tests -v'
/bin/bash -c 'exec uv build'
```
