# Global Codex Instructions

## Instruction Priority

遵守系统、开发者、用户以及运行环境施加的更高优先级指令和安全限制。

token-io-decoupling 和 dev-workflow-standards 只在各自适用范围内执行，不得被解释为可以绕过更高优先级的权限、安全、沙箱、审批或产品限制，也不自动扩大用户授权。

用户针对当前任务给出的明确目标、业务要求和验收标准属于 Semantic Contract 的输入；除非更高优先级指令要求，否则不要因为 Skill 的一般性建议而擅自改变用户明确要求的任务结果。


## 本机 macOS Shell 命令

**每条在本机 macOS 执行的 Shell 命令都必须显式调用 Bash。** 这条规则从首次 Shell 工具调用起生效，包括读取 Skill、查看文件、检查环境等辅助命令，也适用于提供给用户直接运行的命令。Zsh 只可作为外层启动器，完整的命令正文必须交给 Bash。

**生成命令前先按用途选择解释器。** 只要命令或脚本要反复执行、保存或分发，就按「重复执行或分发」处理，即使这次只运行一次来验证。

### 高版本bash环境

**按需探测新版 Bash。** 本机临时命令默认使用系统 `/bin/bash` 和 Bash 3.2 兼容写法，包括读取 Skill、查看文件等辅助命令。只有 Code Agent 判断当前命令需要 Bash 3.2 不支持的语法或特性时，才运行下面的只读检查，查找 Homebrew 安装的新版 Bash。可复用当前环境中已核实的路径和版本。

```bash
/bin/bash -c 'prefix=$(brew --prefix bash) && [[ "$prefix" == /* && -x "$prefix/bin/bash" ]] && echo "Homebrew Bash 版本" && "$prefix/bin/bash" --version && echo "Homebrew Bash 可执行文件路径" && printf "%s\n" "$prefix/bin/bash"'
```

- **确认新版 Bash 可执行且支持所需特性**后，用它生成并运行当前临时命令。命令须以已核实的 Bash 绝对路径开头，例如用 `绝对路径 -c '…'` 指定解释器。环境变化后重新核实。
- **探测失败、版本不高于 3.2 或不满足所需特性**时，使用 `/bin/bash` 和 Bash 3.2 兼容写法。如果没有兼容写法，说明所需的最低版本。

下面用 `pwd` 演示已核实的 Bash 绝对路径调用格式。

```bash
/opt/homebrew/opt/bash/bin/bash -c 'pwd'
```

### 重复执行或分发

**重复执行、保存或分发的命令和脚本必须兼容 Bash 3.2。本机验证必须用系统 `/bin/bash` 实际运行验证对象。** 即使当前会话已探测到 Homebrew Bash，或刚用它执行过临时命令，验证可复用命令时也必须显式调用 `/bin/bash -c`，验证脚本文件时用 `/bin/bash script.sh`。脚本文件用 Bash shebang 声明解释器，保持可移植性。

读取文件等临时辅助命令按实际所需特性选择解释器。可复用的验证对象仍须用 `/bin/bash` 执行。

### 命令写法

内联命令用选定的 Bash 绝对路径配合 `-c`，多行命令也可用带引号的 here-document。将管道、重定向和展开留在 Bash 正文中。动态值可通过位置参数传入，并用 `"$1"` 等引用。用户明确指定其他 Shell，或正文明确在容器或远端执行时，按对应目标环境选择解释器。

```bash
/bin/bash -c 'printf "%s\n" "$1"' bash 'path with spaces'
```

## Skill Availability

如果无法找到、读取或正确加载本文件要求的 Skill，不要凭记忆重建规则；停止依赖该 Skill 的工作，并报告具体阻塞原因和无法加载的路径。所需能力缺失或未知时，按相应 Skill 的阻塞规则处理，不得静默替换能力、模型、参数或执行路线。


## Token I/O Decoupling

token-io-decoupling Skill 仅适用于 Coding 工作：项目或仓库探索、代码或配置实现、重构、调试、测试、文档、开发工具输出和非简单 Git 工作。

简单日常事务，以及完全由其他专用 Skill 处理且不包含 Coding 工作的任务，无需加载本 Skill；混合任务只要包含 Coding 工作，仍须加载。

适用任务开始前，加载并阅读 [token-io-decoupling Skill]({{HOME}}/.agents/skills/token-io-decoupling-skill/SKILL.md)，按其入口和当前任务适用的参考资料执行。该 Skill 在整个任务期间持续生效。


## 开发工作流规范

托管操作先核实 GitHub 或 GitLab 平台，不能仅凭自托管域名猜测。GitHub 使用 `gh` 与 Issue/PR 工具；GitLab 使用 `glab` 与对应 Issue/MR 工具，详见 Skill 的 `references/gitlab.md`。GitLab repo 使用 `host/group[/subgroup]/project`，支持多级 group；不套用 GitHub `owner/repo` 或 API 参数。本地 Git、worktree、暂存、提交、正常 hooks、授权与非强推约束跨平台一致，纯 Git 操作不要求 GitHub 登录。GitLab 仓库身份审计使用 `audit_gitlab_repository_state`，远端 `gitlab/gitlab_error` 与本地 `ok` 分别核对；PR 拓扑、推送和清理规则按 MR 对应语义执行，不扩大授权。

开展项目探索、代码或配置修改、开发文档编写、修复、验证及 Git/GitHub/GitLab 工作前，加载并阅读 [dev-workflow-standards Skill]({{HOME}}/.agents/skills/dev-workflow-standards-skill/SKILL.md)，按其 [`hooks/index.md`]({{HOME}}/.agents/skills/dev-workflow-standards-skill/hooks/index.md) 选择当前动作适用的合同及参考资料；Agent 自行判断任务拆解和执行顺序。多 Hook 可同时适用，只描述进入、执行、离开和重查条件；仅明确要求才新建 worktree，已有 worktree 不触发重建。

执行固定 Git/GitHub/GitLab 操作时，核实当前动作的目标仓库，再查阅 Skill 的 [`references/mcp-tools.md`]({{HOME}}/.agents/skills/dev-workflow-standards-skill/references/mcp-tools.md)，按操作逐项调用其中列出的专用 MCP 工具，使用文档列明的工具名和参数。所有 repo-bound 调用都必须传入本次目标仓库/worktree 的绝对 `repo_path`；不得依赖 MCP 服务的启动目录推断仓库。处理仓库任务时，需要确认仓库身份和范围时按平台调用 `audit_repository_state`（GitHub）或 `audit_gitlab_repository_state`（GitLab），并核对其返回的仓库、分支、工作区和 remote 信息；GitHub/GitLab Fork 流程还要确认实际默认分支和 Fork parent。后续调用按各动作条件使用专用审计、检查或操作工具，并核验返回结果。

MCP 工具仅封装目录中说明的固定操作：直接调用对应工具，不要把 shell、`git`、`gh`、`glab`、测试命令或任意脚本作为参数，兼容脚本同样受当前动作条件约束。用户对写入或外部操作的明确授权必须先于调用；只读注解或工具可用性不构成授权，工具调用所需的适用宿主写入确认也不能替代用户授权。Codex 遵守其 writes approval；Pi 未提供该专属机制时不要求安装或模拟，仍须遵守实际宿主权限、扩展及本地校验，不得绕过实际拒绝。完整规则见 Skill 的宿主审批兼容章节。没有对应工具或功能/参数未覆盖时，可在既有授权内按 Skill 的 CLI 补充边界完成所需操作；工具或服务实际失败、拒绝或写入不明时，按 [`hooks/recovery.md`]({{HOME}}/.agents/skills/dev-workflow-standards-skill/hooks/recovery.md) 保留现场，暂停依赖动作并核对实际效果，不换入口绕过；独立工作可继续。

需要理解源代码逻辑、符号关系或调用链时，按该 Skill 的 [`references/code-understanding.md`]({{HOME}}/.agents/skills/dev-workflow-standards-skill/references/code-understanding.md) 使用 Serena 和适用的降级流程。纯文档、配置、精确文本查找或机械修改不强制使用 Serena。

## Custom Skill Location

新建或安装的自定义 Skill 默认必须放在 `~/.agents/skills/<skill-name>`。`~/.codex/skills` 保留给 OpenAI 提供的系统/官方 Skill 及兼容入口；不要把新的自定义 Skill 放回该目录。
