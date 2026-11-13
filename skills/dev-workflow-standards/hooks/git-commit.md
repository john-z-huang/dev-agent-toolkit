# 暂存与提交

GitHub 与 GitLab 托管仓库均适用；纯 Git 动作不要求 GitHub 登录，PR/MR 及平台工具差异见 [GitLab 兼容规则](../references/gitlab.md)。

## 进入条件

准备修改 Git index 或创建 commit 时适用；仅编辑文件或分析不触发。

## 执行条件

暂存：授权覆盖准确路径/hunk，内容归属明确；整文件用 `stage_repository_paths`，混合修改按 [CLI](../references/cli-fallback.md) 精确选择本任务 hunk。核对实际 staged diff，保留无关内容。

提交信息生成：需要起草时调用 `generate_git_commit_message`，复用现有 `generate_skill_content(kind="commit_message")` 链路，Agent 提供本次选定提交全部 patch/hunk 的事实、路径、原因和验证来源，不先自行写完整 message。已暂存以实际 cached diff 为准；未暂存明确拟提交范围；多个 commit 分别生成，不用整个 PR 或最后一次历史提交代替。用户已提供完整 message 时保留原文并检查，不强制重写。返回 `message` 为候选，核对 `ok`、`adoptable`、缺失事实及实际暂存范围，再用 `check_commit_message` 检查最终完整 message；生成失败不可视为检查通过或自动降级手写绕过。生成不授权 stage/commit，详见 [提交信息](../references/check-commit-message.md)。

提交：授权涵盖 commit；分支名、完整提交信息、暂存范围、空白及项目适用检查满足要求。标题为 `<type>: 中文说明`，type 使用既有合法枚举，无禁止署名；见 [分支](../references/check-branch-name.md)、[提交信息](../references/check-commit-message.md)、[暂存检查](../references/check-staged-changes.md)。`expected_paths` 必须等于实际 staged paths，但路径相同不能替代内容审阅。保留正常 [Git Hook](../references/git-hooks.md)，不使用绕过参数。

## 离开条件

成功：暂存内容精确符合范围；提交还须实际成功并核对 OID、消息、内容与后续状态。暂停：检查失败或范围不一致。`committed=true` 且 `ok=false` 表示已提交而回读不全，适用 [恢复](recovery.md)，不直接重试。

## 重新进入条件

暂存内容、目标分支、HEAD、提交信息或相关验证依据变化。
