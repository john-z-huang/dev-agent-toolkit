# 更名为 Dev Agent Toolkit

`dev-workflow-standards` 这个名字容易让人期待一套团队必须遵循的开发流程规范。在开发 token-io-decoupling 的过程中，我们发现维护详细、固定的 Agent workflow 很困难。随着模型能力提高，Agent 已能根据上下文自行处理一些原本需要逐步指导的操作。继续强制执行这些步骤会增加维护负担，也可能让 Agent 错过更适合当前任务的做法。

Dev Agent Toolkit 收录具体开发操作的指南、Skills 和可执行工具，Agent 可以在需要时调用。例如，当任务涉及 Git worktree 的基线变化时，Agent 根据当前任务判断是否需要同步。同步工具读取实际 Git 状态，检查工作区是否干净、是否有正在进行的 Git 操作，再决定是否允许执行。指南提示 Agent 何时考虑同步，工具按现场状态执行安全检查，具体执行顺序由任务决定。相关条件见 [Worktree 基线同步](../skills/dev-agent-toolkit/references/worktree-base-sync.md)。

- **Dev** 覆盖编码、Git worktree、Issue 和 PR 等研发活动。
- **Agent** 表明这套能力供团队已有的研发 Agent 使用。
- **Toolkit** 表明团队可以在现有流程中按需选用这些能力，并保留确实需要统一的研发约定。

这次更名更新了发行包、命令、Skill、MCP 注册和安装标识。使用新名称时，请在干净的配置中按 [安装与构建指南](../INSTALL.md) 安装。
