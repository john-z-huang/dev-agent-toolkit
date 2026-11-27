# Codex 会话内临时调用更新后的本地 MCP

## 进入条件

当前 Codex 会话仍连接旧版 `dev_agent_toolkit` 服务，本次任务已经完成并核对 `dev-agent-toolkit-tools` 的 uv tool 更新，且当前动作需要新版的离线只读方法或 Schema。软件包更新不代表当前会话的连接已重载。仅在有版本、入口或新旧工具发现差异等实际证据时启用。

## 执行条件

1. 按[项目工具安装合同](install-tooling.md)核对成功退出、实际安装入口、版本和来源。同版本重装时，用 [`get_mcp_server_build_info`](../references/mcp-tools.md#正在运行的-mcp-构建信息) 比较当前连接与新进程的构建提交，并核对预期的 wheel 来源及新工具或 Schema。若更新仍在进行、失败或结果不明，先回读状态。
2. 当前会话提供 `call_updated_local_mcp` 时，先传 `{}` 发现。若旧连接尚未发现桥接方法，由宿主的 Shell 使用已经核实的同一 uv tool 管理入口 `dev-agent-toolkit mcp`。两种入口使用同一请求形状，均启动一个新 stdio 进程。每次调用按目标工具的新 Schema 构造最小输入，显式传入准确的绝对 `repo_path` 等必需字段。
3. 用该方式补足本次已授权的离线只读请求。工具被禁用、隐藏、拒绝，或实际调用失败时，按[恢复 Hook](recovery.md)处理。遵守宿主权限和审批。写入、联网、凭据、其他 uv 工具和旧进程内状态超出此入口范围。

以下示例在 Bash 中调用已安装入口。执行前先核对 `uv tool dir --bin` 及其中的实际入口。

```bash
/bin/bash -c 'tool_bin=$(uv tool dir --bin) && exec "$tool_bin/dev-agent-toolkit" mcp' <<'JSON'
{}
JSON

/bin/bash -c 'tool_bin=$(uv tool dir --bin) && exec "$tool_bin/dev-agent-toolkit" mcp' <<'JSON'
{"tool_name":"get_codex_session_summary_guidance","arguments":{}}
JSON
```

调用只在当前请求期间保留子进程，结果及失败状态见 [MCP 工具目录](../references/mcp-tools.md#更新后临时本地-mcp)。该声明式 Hook 由 Agent 按事实进入。

## 离开条件

本次请求取得可核对的结果，或记录具体失败原因并停止该入口。Codex 正常连接完成重载且直接发现目标工具后，恢复直接调用。

## 重新进入条件

安装、目标工具 Schema、当前宿主连接或授权范围再次变化时，只重查受影响条件。
