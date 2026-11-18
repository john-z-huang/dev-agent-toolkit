# Hook 条件索引

按准备执行的动作或当前观察到的状态选择相关合同。这里没有第一步、唯一路线、后继节点或必须调用的评估 API；Agent 自行决定执行顺序。不满足执行条件时暂停对应动作，独立工作仍可继续。

| 动作或状态 | 合同 | 按需参考 |
|---|---|---|
| 准备修改项目内容 | [项目修改](project-change.md) | [工具目录](../references/mcp-tools.md) |
| 结论依赖代码逻辑、符号、调用关系 | [代码理解](code-understanding.md) | [Serena](../references/code-understanding.md) |
| 准备生成或运行 Python/Shell | [执行环境](environment.md) | [Python](../references/python-environment.md)、[Shell](../references/shell-environment.md) |
| 准备创建、同步、恢复或移除 worktree | [Worktree](worktree.md) | [基线同步](../references/worktree-base-sync.md)、[受限恢复](../references/worktree-recovery.md) |
| 准备暂存或提交 | [暂存与提交](git-commit.md) | [暂存检查](../references/check-staged-changes.md)、[Git Hook](../references/git-hooks.md) |
| 准备调用 gh 或访问 GitHub 的 MCP/Connector，或准备创建 Issue、推送、创建 PR/MR、合并 | [托管资源](github-delivery.md) | [GitHub 策略](../references/github.md)、[GitLab 兼容](../references/gitlab.md)、[Fork](../references/fork-maintenance.md)、[堆叠 PR](../references/stacked-pr.md) |
| 引用历史会话事实或准备保存摘要 | [会话事实](session-facts.md) | [来源与格式](../references/codex-session-facts.md) |
| 准备外发 API 请求 | [外部 API](external-api.md) | [审核](../references/api-input-review.md)、[请求协议](../references/openai-workflow-tools.md) |
| 失败、拒绝、冲突、结果不明 | [恢复](recovery.md) | [环境权限](../references/environment.md)、[CLI](../references/cli-fallback.md) |
| 准备报告完成或交接 | [完成交付](completion.md) | [合并后清理](../references/pr-merge-cleanup.md) |

每个合同说明进入、执行、成功/暂停离开和重新进入条件。不适用的合同不执行；事实未知时收集必要证据，不能用默认值补齐。离开只说明本动作的结果；任何后续动作按它自身条件判断。

其中可自动执行的路径条件与提示另有可选的 [原生 Codex Hooks 适配](../references/codex-hooks.md)。未安装或未信任时不会自动触发；合同仍由 Agent 按实际动作遵循。
