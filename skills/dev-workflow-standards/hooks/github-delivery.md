# GitHub / GitLab 资源操作

按核实的 remote 和项目事实识别托管平台。自托管平台须核实实际类型。Issue、推送、PR 拓扑与授权规则适用于 GitLab MR，GitLab 使用对应 `glab` 工具及检查。见 [GitLab 兼容规则](../references/gitlab.md)。

## 进入条件

准备访问 GitHub 资源或创建、修改 Issue，推送分支，创建、修改或合并 PR/MR 时适用。Git Hook 配置和历史重写分别按 [Git Hook](../references/git-hooks.md) 与 [历史维护](../references/rewrite-weather-commit-subjects.md) 核对授权。

## 执行条件

核实主机、仓库、账号、目标资源、分支和授权。涉及真实 Fork 时核对 [Fork 拓扑](../references/fork-maintenance.md)。

使用 `gh` 或访问 GitHub 的 MCP/Connector 前，运行 `gh auth status --active`，按 [多账号核验](../references/github.md#多账号核验) 确认实际身份和目标仓库权限。切换账号后重新核验，所有账号均缺少权限时请用户介入。

Issue：正文说明具体问题/目标、范围和验收；至少一个已核实工作类型标签，按策略指派本人。文案可用 `generate_skill_content`，候选须核对事实和质量再发布。

新建 GitHub Issue 或 PR 时，按[草稿流程](../references/github.md#正文草稿)在起草阶段分别填写、校验并回读标题与 Markdown 正文。发布阶段仅将定稿绝对路径传入 `title_file` 和 `body_file`，需要修改时返回起草阶段。

推送：当前需求分支、origin、开放 Issue、label、本人 assignee、提交范围和适用检查正确，工具要求的干净状态满足，仅非强推。用户明确要求推送时，既有策略同时涵盖补齐缺失 Issue 和创建关联开放 PR，不涵盖合并/关闭。

PR：已推送 head 与准确 base、开放 Issue 和关闭关联明确；[堆叠 PR](../references/stacked-pr.md) 不默认 main。正文、本人 assignee 与资源关系可核验。

合并：单独明确授权，PR 可合并、required checks 及审核满足，main base 只 squash；见 [策略](../references/github.md)、[合并](../references/squash-merge.md)。

## 离开条件

成功：所选动作真实完成且远端状态、标签/指派、base/head/关联等适用条件回读一致。推送成功不表示 PR 已创建，PR 创建不表示已合并。暂停：必要事实缺失或失败；`created=true, ok=false` 先回读实际资源，不重复创建。

## 重新进入条件

远端资源状态、base/head、账号、检查或授权范围变化。
