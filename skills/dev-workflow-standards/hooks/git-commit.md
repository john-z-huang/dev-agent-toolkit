# 暂存与提交

## 进入条件

准备修改 Git index 或创建 commit 时适用；仅编辑文件或分析不触发。

## 执行条件

暂存范围须涵盖于授权且变更归属明确。整文件用 `stage_repository_paths`，混合修改按 [CLI](../references/cli-fallback.md) 选择准确 hunk。核对实际 staged diff。

用户提供完整提交信息时保留原文并检查。需要起草时按 [提交信息生成协议](../references/openai-workflow-tools.md) 调用 `generate_git_commit_message`，提供每个拟提交 commit 的完整 patch/hunk 范围及变更和验证事实。核对候选的 `ok`、`adoptable`、缺失事实与实际暂存内容，再用 `check_commit_message` 检查最终完整信息。生成失败按 [恢复](recovery.md) 处理。

提交需获得对应授权，通过 [分支](../references/check-branch-name.md)、[提交信息](../references/check-commit-message.md)、[暂存](../references/check-staged-changes.md) 及项目检查。标题使用合法 `<type>: 中文说明`。核对 `expected_paths` 与实际 staged paths 一致，并审阅暂存内容。保留正常 [Git Hook](../references/git-hooks.md)。

## 离开条件

成功：暂存内容精确符合范围；提交还须实际成功并核对 OID、消息、内容与后续状态。暂停：检查失败或范围不一致。`committed=true` 且 `ok=false` 表示已提交而回读不全，适用 [恢复](recovery.md)，不直接重试。

## 重新进入条件

暂存内容、目标分支、HEAD、提交信息或相关验证依据变化。
