# 个人 Fork 的上游同步与长期维护

GitLab 仓库同样适用本文的通用 Git、拓扑、授权和保留条件；PR 对应 MR，平台工具、字段及例外按 [GitLab 兼容规则](gitlab.md) 选择，不直接执行本文的 GitHub 专属命令。

仅当 `audit_repository_state` 返回非空 GitHub `parent` 时启用。独立仓库跳过本文，沿用项目自己的默认分支、开发分支和保护规则。

## 拓扑

```text
upstream/main → origin/main → personal-<project> → feat/fix/docs/... → PR
```

- `upstream` 是原项目，只读同步来源；`origin` 是个人 Fork。
- `main` 只镜像上游默认分支，不承载个人需求提交。
- 个人长期改动放入 `personal-<project>` 或 `personal/<project>`；以已核验的项目约定为准。
- 需求分支从最新个人维护分支创建，PR base 默认是该分支。

## 同步上游

同步操作要求已核实 Fork、仓库、实际默认分支、remote 和工作区，`audit_repository_state` 可提供相关观测。

- 获取上游：`upstream` 必须已配置且对应真实 Fork parent。MCP 不猜 URL 或首次添加 remote；缺失时只有准确 URL 和配置授权明确，才可按 [CLI 边界](cli-fallback.md) 补足并回读。
- 更新本地镜像：`merge_upstream_branch_fast_forward` 要求当前目标为本地 `main`，已获取的上游引用可信且可快进；工作区允许安全切换/合入，不改写个人内容。获取、切换和合入分别满足各自条件。
- 更新远端镜像：只有 `main` 与 `upstream/main` 的快进关系已核实且推送授权有效，才适用 `push_fork_main_fast_forward`。
- 个人维护分支：需求工作要求基线和拓扑准确；创建或设置 tracking 是单独动作，不因上游同步而自动执行。工具未覆盖的部分按既有授权补足，基线不明则暂停。

任何 fetch、切换、快进或推送失败都保留现场，不使用过期 remote-tracking 信息、任意 SHA、重置或强推绕过。

## 日常开发与保护

- 需求提交和推送只在需求分支进行；`push_issue_branch_to_origin` 的固定规则拒绝把需求分支推入主分支。
- 需求 PR 显式以个人维护分支为 base，通过 `create_github_pull_request` 提交并核验。
- `main` 和个人维护分支应禁止删除及强推；个人维护分支应要求通过 PR。保护规则尚未封装为本服务 MCP 工具；回读可按 [`read-only-queries.md`](read-only-queries.md) 使用已授权 Connector 或显式 GET CLI。创建/修改可在对应授权内按 CLI 补充规约执行并回读；权限失败不能绕过或当作无规则。

## 发现拓扑异常

- `origin/main` 含个人需求提交时，先核验提交归属；不能继续把它当作上游镜像。
- `merge_upstream_branch_fast_forward` 失败表示发生分叉或基线不符；保留状态并检查差异，不改写公开历史。
- 个人维护分支含未合并需求时，确认 PR base/head；不要直接 rebase 已公开分支或裸强推。
- 更改默认分支、规则集或保护策略需要用户明确授权和执行层审批；MCP 未覆盖时可按 CLI 补充规约执行，不因工具缺口重复请求授权。只读回读按前述规约处理。
