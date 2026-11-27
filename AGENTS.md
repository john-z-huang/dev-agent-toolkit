# Dev Agent Toolkit 仓库开发入口

本文件是仓库内开发的唯一入口：先按任务查表，只读需要的文档。`.agents/` 仅用于开发和维护本仓库，不随 wheel/sdist 交付；面向使用者的安装与使用说明见 [`README.md`](README.md) 和 [`INSTALL.md`](INSTALL.md)。

Python 代码必须用 `ruff format` 处理格式，禁止通过 Edit、补丁或其他编辑工具手工修正。

## 任务导航

| 任务 | 阅读 |
|---|---|
| 了解仓库结构、启动器与构建流程 | [`.agents/development.md`](.agents/development.md) |
| 修改 MCP 服务、输入协议、模型指令、Schema 或测试 | [`.agents/mcp-server-guidelines.md`](.agents/mcp-server-guidelines.md) |
| 运行格式化、静态检查、离线与冒烟测试 | [`.agents/verification.md`](.agents/verification.md) |
| 构建/发布并核对交付内容与 `.agents/` 边界 | [`.agents/distribution.md`](.agents/distribution.md) |
| 安装、使用与面向用户的说明 | [`README.md`](README.md)、[`INSTALL.md`](INSTALL.md) |
| 交付 Skill 的入口与 Hooks 合同 | [`skills/dev-agent-toolkit/SKILL.md`](skills/dev-agent-toolkit/SKILL.md) |
