# Hook 条件索引

按准备执行的动作或当前状态选读合同。共用规则见 [Skill 入口](../SKILL.md)。

| 动作或状态 | 合同 |
|---|---|
| 修改项目内容 | [项目修改](project-change.md) |
| 判断代码逻辑、符号或调用关系 | [代码理解](code-understanding.md) |
| 选择运行环境，编写或执行 Python、JavaScript 命令或 Shell 脚本 | [执行环境](environment.md) |
| 创建、同步、恢复或移除 worktree | [Worktree](worktree.md) |
| 暂存或提交 | [暂存与提交](git-commit.md) |
| 使用 `gh` 或访问 GitHub 的 MCP/Connector，或操作 Issue、推送分支、创建、修改或合并 PR/MR | [托管资源](github-delivery.md) |
| 引用历史会话事实或保存摘要 | [会话事实](session-facts.md) |
| 发送外部 API 请求 | [外部 API](external-api.md) |
| 失败、拒绝、冲突或结果不明 | [恢复](recovery.md) |
| 报告完成、交接或阻塞 | [完成交付](completion.md) |
