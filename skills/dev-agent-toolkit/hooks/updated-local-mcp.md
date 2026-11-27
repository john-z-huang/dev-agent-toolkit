# 调用已更新的本地 MCP

## 进入条件

项目依赖的本地 MCP 服务已更新，需要核对实际版本、构建信息或工具 Schema。

## 执行条件

1. 按 [项目工具安装合同](install-tooling.md) 核对实际安装入口、版本和来源。若更新结果不明，先回读状态。
2. 按 [本地 MCP Client](../references/mcp-tools.md#通过本地-mcp-client-调用) 核对注册项指向已更新的可执行文件。用单次调用或新会话查询工具 Schema。Toolkit 可调用 [`get_mcp_server_build_info`](../references/mcp-tools.md#正在运行的-mcp-构建信息) 核对构建版本和提交。
3. 显式 CLI 会话可能仍复用更新前启动的进程。用新会话调用新版工具，并按需要重新绑定项目。完成已授权操作后关闭不用的会话。实际失败时按 [恢复 Hook](recovery.md) 处理。

下面以客户端注册表中名为 `dev-agent-toolkit-tools` 的服务为例。

```bash
/bin/bash -c 'exec dev_agent_toolkit_mcp_client_cli call dev-agent-toolkit-tools get_mcp_server_build_info'
```

## 离开条件

核对实际入口和目标 Schema，或记录具体缺口。后续项目请求继续使用 Client CLI。

## 重新进入条件

安装入口、工具 Schema、客户端会话或授权范围变化时，只重查受影响条件。
