---
name: dev-agent-toolkit
description: >-
  为代码理解、项目修改、终端命令的生成与执行、本地 Modal 代理依赖管理及 Git/GitHub 操作提供声明式 Hook 条件。也用于安装、注册和更新本项目的工具、Skill、全局指令和 MCP。
---

# 开发操作约束

按当前动作和资源状态查阅 [Hook 索引](hooks/index.md)，只读适用合同及所需参考。Agent 根据用户目标自行安排顺序。多个合同同时适用时，满足各自条件和实际依赖。

Hook 的进入、执行、离开和重新进入条件由 Agent 判断。未知、未查或不可访问须标明证据缺口。不适用与验证通过分别记录。事实变化时只重查受影响条件。

生成终端命令前，必须先在用户可见的对话中简短说明为什么需要命令、预期结果及判断标准，以及操作步骤和影响范围。说明必须出现在调用执行工具或展示命令文本之前。单条、批量和仅提供给用户运行的命令均适用，具体条件见 [执行环境 Hook](hooks/environment.md#命令前置说明)。

## 项目 MCP 调用

- 在 Codex、Pi 或其他 Code Agent 中，通过 `dev_agent_toolkit_mcp_client` 提供的 `dev_agent_toolkit_mcp_client_cli` 调用项目 MCP。复用客户端注册表中已配置的本地服务，包括 `dev-agent-toolkit-tools`、Serena 及项目使用的其他本地 STDIO 服务。工具发现、Schema 和调用命令见 [本地 MCP Client](references/mcp-tools.md#通过本地-mcp-client-调用)。
- 日常项目任务使用预先安装的服务程序。缺少客户端、服务程序或注册项时，报告具体缺口，继续可独立完成的步骤。项目服务的启动配置统一放在 MCP Client 注册表。构建、安装、更新或修改注册表按用户授权单独执行。
- 项目工具的领域参数、项目绑定、审批与检查条件仍适用。通过终端调用时遵守宿主命令审批及沙箱。服务不可用、工具拒绝或结果不明时按 [恢复 Hook](hooks/recovery.md) 处理。

## 宿主审批兼容

Skill、MCP 服务和参考资料中的 `Codex writes approval` 均指 Codex 宿主的写操作审批机制。

- **Codex** 遵守宿主实际配置的审批要求。
- **Pi Code Agent** 确认缺少 Codex 专属机制后，按 Pi 的实际权限和审批继续已授权操作。无需查找、安装或模拟 Codex 审批，也不得声称已获 Codex 审批。
- 写操作前核对用户对当前动作、目标及范围的明确授权、适用的宿主权限与审批，以及工具前置校验。已有授权仅在原范围有效，换工具无须重复询问。授权缺失或不清时先询问。内容修改授权不自动扩展到提交、推送、合并、删除、历史重写、配置或 Memory 写入，通过检查也不授予后续写入权限。
- 审批状态未知、实际拒绝、权限错误或校验失败时，暂停受影响操作并报告。按 [恢复 Hook](hooks/recovery.md) 处理，禁止经 CLI、其他工具或 Codex App Server 绕过。

## 共用边界

- 准确识别仓库、worktree 和目标资源，仓库工具显式传入绝对根路径 `repo_path`。保留用户现有内容，以实际回读和验证结果为准。
- 通用 Git、worktree 和提交规则跨平台适用，纯本地 Git 动作无需托管平台登录。GitHub 账号和仓库核验见 [托管资源 Hook](hooks/github-delivery.md)。
- 宿主会话 API 和已授权托管平台 Connector 按其适用条件使用。历史读取使用真实会话来源，缺少读取能力时只暂停依赖历史的部分。详见 [会话事实](hooks/session-facts.md)。项目工具能力缺口按 [CLI 补充边界](references/cli-fallback.md) 处理。
- 语义判断和文案生成提交最小结构化事实，由工具分析或生成后核对结果。涉及外发和审核时查阅 [外部 API Hook](hooks/external-api.md)。
- 涉及可运行 Web 页面、浏览器交互或页面验收时查阅 [真实浏览器验证](references/web-browser-validation.md)，再按需读取所用 CLI 的参考 Skill。
- 禁止输出或记录凭据及添加 Agent 署名或生成声明。

用户授权安装、注册或更新本项目资源时，从 [安装与更新索引](hooks/index.md#安装与更新) 核对命令、写入范围与验收条件。
