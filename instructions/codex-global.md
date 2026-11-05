# Global Codex Instructions

## Instruction Priority

遵守系统、开发者、用户以及运行环境施加的更高优先级指令和安全限制。

token-io-decoupling 和 dev-workflow-standards 只在各自适用范围内执行，不得被解释为可以绕过更高优先级的权限、安全、沙箱、审批或产品限制，也不自动扩大用户授权。

用户针对当前任务给出的明确目标、业务要求和验收标准属于 Semantic Contract 的输入；除非更高优先级指令要求，否则不要因为 Skill 的一般性建议而擅自改变用户明确要求的任务结果。


## Skill Availability

如果无法找到、读取或正确加载本文件要求的 Skill，不要凭记忆重建规则；停止依赖该 Skill 的工作，并报告具体阻塞原因和无法加载的路径。所需能力缺失或未知时，按相应 Skill 的阻塞规则处理，不得静默替换能力、模型、参数或执行路线。


## Token I/O Decoupling

token-io-decoupling Skill 仅适用于 Coding 工作：项目或仓库探索、代码或配置实现、重构、调试、测试、文档、开发工具输出和非简单 Git 工作。

简单日常事务，以及完全由其他专用 Skill 处理且不包含 Coding 工作的任务，无需加载本 Skill；混合任务只要包含 Coding 工作，仍须加载。

适用任务开始前，加载并阅读 [token-io-decoupling Skill]({{HOME}}/.agents/skills/token-io-decoupling-skill/SKILL.md)，按其 `Start here` 完成 Contract、Environment 和 Mode 检查点，选择且只选择一条执行路线，并按该路线完成检查点和 Acceptance。该 Skill 在整个任务期间持续生效。

运行环境分支、模型与参数绑定、角色和 Session 拓扑、Context Firewall、验证边界以及其他调度规则，以该 Skill 和它引用的 owner 文档为准；本文件不重复维护这些策略。运行环境与模型规则见 [运行环境与模型厂商支持]({{HOME}}/.agents/skills/token-io-decoupling-skill/references/coding/layer-01-fundamental-concepts/session-runtime/runtime-provider-support_zh_cn.md)。


## 开发工作流规范

开展项目探索、代码或配置修改、开发文档编写、修复、验证及 Git/GitHub 工作前，加载并阅读 [dev-workflow-standards Skill]({{HOME}}/.agents/skills/dev-workflow-standards-skill/SKILL.md)，再读取其 `workflows/index.md`，只选适用工作流及该工作流指定的参考文档，按序完成步骤和 Completion Gate。只有用户明确要求 worktree 时才选择 worktree 工作流。

执行固定 Git/GitHub 操作时，先按工作流确认目标仓库，再查阅 Skill 的 [`references/mcp-tools.md`]({{HOME}}/.agents/skills/dev-workflow-standards-skill/references/mcp-tools.md)，按操作逐项调用其中列出的专用 MCP 工具，使用文档列明的工具名和参数。所有 repo-bound 调用都必须传入本次目标仓库/worktree 的绝对 `repo_path`；不得依赖 MCP 服务的启动目录推断仓库。处理仓库任务时，按适用工作流在确认仓库身份和范围时调用 `audit_repository_state`，并核对其返回的仓库、分支、工作区和 remote 信息；GitHub/Fork 流程还要确认实际默认分支和 Fork parent。后续调用按工作流要求使用专用审计、检查或操作工具，并核验返回结果。

MCP 工具仅封装目录中说明的固定操作：直接调用对应工具，不要把 shell、`git`、`gh`、测试命令或任意脚本作为参数，也不要把兼容脚本当成交互式工作流的后备方案。用户对写入或外部操作的明确授权必须先于调用；只读注解或工具可用性不构成授权，工具调用所需的 Codex 写入确认也不能替代用户授权。若工具缺失、失败，或所需操作未被封装，停止该操作，按 Skill 的 [`workflows/recovery-and-exceptions.md`]({{HOME}}/.agents/skills/dev-workflow-standards-skill/workflows/recovery-and-exceptions.md) 保留现场并报告证据、影响和所需的最小决定；不要改用手写 CLI 命令绕过专用工具。

需要理解源代码逻辑、符号关系或调用链时，按该 Skill 的 [`references/code-understanding.md`]({{HOME}}/.agents/skills/dev-workflow-standards-skill/references/code-understanding.md) 使用 Serena 和适用的降级流程。纯文档、配置、精确文本查找或机械修改不强制使用 Serena。

## Custom Skill Location

新建或安装的自定义 Skill 默认必须放在 `~/.agents/skills/<skill-name>`。`~/.codex/skills` 保留给 OpenAI 提供的系统/官方 Skill 及兼容入口；不要把新的自定义 Skill 放回该目录。
