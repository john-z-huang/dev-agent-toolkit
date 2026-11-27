# 暂存与提交

## 进入条件

准备修改 Git index 或创建 commit 时适用；仅编辑文件或分析不触发。

## 执行条件

暂存范围须在授权内且变更归属明确。通过 [本地 MCP Client](../references/mcp-tools.md#通过本地-mcp-client-调用) 调用本流程的 MCP 工具。整文件用 `stage_repository_paths`，混合修改按 [命令行补充](../references/cli-fallback.md) 选择准确 hunk。核对实际 staged diff。

用户提供完整提交信息时保留原文并检查。需要起草时先暂存本次改动，再用 [Toolkit 的提交草稿](../references/mcp-tools.md#提交草稿) 生成候选。这个命令只向生成工具传 `repo_path`，自动保存候选及暂存快照。确认 `adoptable=true` 后按实际暂存内容审阅。生成失败按 [恢复](recovery.md) 处理。

提交需获得对应授权并通过项目检查。使用已审阅的草稿时，`commit apply` 自动运行分支、暂存区和提交信息检查，并比对分支、HEAD、暂存路径和指纹。手工消息仍按 [分支](../references/check-branch-name.md)、[提交信息](../references/check-commit-message.md) 和 [暂存](../references/check-staged-changes.md) 要求验证。两种方式均保留正常 [Git Hook](../references/git-hooks.md)。

## 离开条件

成功：暂存内容精确符合范围；提交还须实际成功并核对 OID、消息、内容与后续状态。暂停：检查失败或范围不一致。`committed=true` 且 `ok=false` 表示已提交而回读不全，适用 [恢复](recovery.md)，不直接重试。

## 重新进入条件

暂存内容、目标分支、HEAD、提交信息或相关验证依据变化。
