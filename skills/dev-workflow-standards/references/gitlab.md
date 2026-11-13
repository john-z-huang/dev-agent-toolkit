# GitLab 托管仓库兼容规则

从当前任务、已核实 remote 和平台信息确定 GitHub 或 GitLab，不能仅凭域名猜自托管平台；混合平台、多 remote 和 Fork 分别核实目标。纯 Git、worktree、暂存和提交不依赖 GitHub 登录。授权、正常 hooks、保留用户改动、非强推、已发布分支不 rebase、基线和清理条件跨平台一致。

## 项目、身份与编号

GitLab 使用本机已认证的 `glab`。所有 GitLab 工具必填绝对 `repo_path` 和 `repo=host/group[/subgroup]/project`，例如 `gitlab.example.com/team/sub/project`；支持自托管主机和多级 group；host 不含端口（glab `--hostname` 不接受端口），自定义 API 地址/端口使用已核实的 glab `api_host` 配置，不含协议、凭据、`.git` 后缀。不沿用 GitHub `owner/repo` 校验，不猜默认主机。

工具固定传 `--hostname`，完整项目路径 URL 编码后进入 endpoint。Issue `#N` / MR `!N` 均使用项目内 `iid`，不是全局 `id`。`target_branch` / `source_branch` 对应 base / head，`opened` / `merged` 对应开放 / 已合并。不得输出、记录或要求用户粘贴 `GITLAB_TOKEN`、`OAUTH_TOKEN`、认证响应或含凭据的 remote URL。

## 工具对应关系

| GitHub | GitLab | 区别与采用条件 |
|---|---|---|
| `audit_repository_state` | `audit_gitlab_repository_state` | `ok` 只表示本地读取成功；远端看 `gitlab` / `gitlab_error`，不证明账号或 remote 对应关系。 |
| `list_github_issue_labels` | `list_gitlab_issue_labels` | 前 100 项，含继承 group labels；未返回的标签不能假定存在。 |
| `create_github_issue` | `create_gitlab_issue` | 现存工作类型标签、默认指派本人并回读 opened/labels/assignee。 |
| `push_issue_branch_to_origin` | `push_gitlab_issue_branch_to_origin` | 开放 Issue、label、本人 assignee、干净状态、origin 匹配后同名非强推当前需求分支。 |
| `create_github_pull_request` | `create_gitlab_merge_request` | 显式 base/target 和 head/source；开放 Issue、正文关闭关联、本人 assignee 并回读。 |
| `audit_issue_pr_policy` | `audit_issue_mr_policy` | 请求范围内的开放状态、显式分支和关闭引用检查；GitLab 为确定性审计，不调用 OpenAI Decisions。 |
| `merge_github_pull_request` | `merge_gitlab_merge_request` | GitLab 状态、pipeline、项目合并配置及 head SHA 门禁，不套用 GitHub required checks。 |
| `push_fork_main_fast_forward` | `push_gitlab_fork_main_fast_forward` | 真实 Fork、默认/当前 main、准确 origin、干净状态和 upstream/main 祖先条件；调用方仍核实 upstream 是真实 parent。 |
| `cleanup_merged_pr_local_branch` | `cleanup_merged_mr_local_branch` | 单独清理授权、已合并、同项目 MR、准确 origin；同步实际 target，普通删除 source，强删保留合并前精确 OID 门禁。 |

这些封装通过固定 `glab api` 联网，不调用 OpenAI，不提供任意命令/endpoint，不读会话或写 Memory/配置。JSON 正文从标准输入传递，不用 shell 拼接。`created=true,ok=false` 表示已创建但核验不符；`write_attempted=true` 且 `created=null` / `merged=null` 表示写入不明，均先回读实际资源，禁止自动重试。

## Issue、推送与 MR

用户明确要求推送时，既有策略涵盖补齐缺失 Issue 和创建关联开放 MR，不涵盖合并、关闭、删除或清理。Issue 说明具体问题/目标、范围与验收，至少一个已核实工作类型标签及本人 assignee；工具只校验标签存在，工作类型语义由 Agent 核对。

已有改动的文案证据继续遵循 [完整提交证据范围](github.md#issuepr-文案的提交证据范围)：读取全部待交付 commit patch 并结合最终净 diff，不能只取最后一次提交。`generate_skill_content` 可复用 `kind=pr` 生成 MR 候选，在事实中明确 GitLab/MR、source/target、关联 Issue 和格式要求；复核术语与事实后采用，不能把机器协议值改成不支持的 `mr`。

正文使用 `Closes #N`、`Fixes #N` 或 `Resolves #N` 关联同项目 Issue。堆叠 MR 的 target 是实际依赖分支，不默认 main；父 MR 合并后的基线迁移和公开分支不重写规则继续适用。

MR 创建封装只覆盖同项目 source/target；跨项目 Fork MR 先核实两个项目和源分支，用已授权 Connector 或受限 CLI 补足。本地清理拒绝跨项目 MR，防止删除 target 项目的同名分支。能力缺口不等于允许绕过已发生的失败。

## 合并与清理

合并需单独明确授权。要求 `state=opened`、`draft=false`、`has_conflicts=false`、`detailed_merge_status=mergeable`，以及 `head_pipeline.status=success`、pipeline SHA 精确匹配 MR head SHA。服务端审批、讨论、状态检查和保护仍执行；未知、缺失或等待不能算通过。无 CI 或只有 SHA 不同的 merged-results pipeline 时封装会停止，不能声称 CI 已通过。

main target 只 squash。其他分支的 `merge_method=merge` 仅用于项目现有 `merge`；`rebase` 仅用于已配置 `rebase_merge` / `ff`，不额外执行 rebase；squash 必须被 `squash_option` 允许。不修改配置或自动降级合并方式。合并请求绑定 head SHA，禁用自动合并和删除 source，并回读 merged 状态。

合并后默认保留需求分支/worktree。只有单独授权同步 base 和删除本地 head 才调用清理工具；`merged_head_oid` 来自合并前记录的 `pre_merge_head_oid`，不能用合并后猜测的 SHA。部分成功看 `completed/actions/error` 并回读。详见 [清理条件](pr-merge-cleanup.md)。

## CLI 能力缺口

遵守 [CLI 补充边界](cli-fallback.md)，优先覆盖需求的工具/已授权 GitLab Connector。只读查询核实主机、完整项目路径、编号、endpoint 与 HTTP 方法：

```bash
glab api --hostname gitlab.example.com --method GET projects/team%2Fsub%2Fproject/merge_requests/7
```

`glab api` 不使用 `gh --repo owner/repo`；`glab mr/issue view/list` 使用其支持的显式仓库参数，自托管场景使用完整 URL（例如 `--repo https://gitlab.example.com/team/sub/project`），按当前版本帮助核实。`-f` / `-F` 会改变默认 HTTP 方法，REST 查询必须显式 `--method GET`；GraphQL 只允许已审阅 query。禁止 `GLAB_DEBUG_HTTP` 的请求头/正文进入日志或报告。权限、认证、网络或规则失败按恢复条件处理，不改用 CLI/浏览器绕过。

实现依据：[glab api](https://docs.gitlab.com/cli/api/)、[MR API](https://docs.gitlab.com/api/merge_requests/)、[Issue API](https://docs.gitlab.com/api/issues/)。字段随 GitLab 版本、许可证及配置变化，缺失时失败关闭，不承诺全部实例具有相同能力。

本次命令参数也核对了本地 `libs-local-docs-skill/docs/glab/docs/source/api/_index.md` 与 `mr/merge.md`（文档缓存提交 `c6e96df`；本机 glab `1.130.0`）。缓存跟踪上游 main，不等同于本机发布版本；`--hostname`、显式 `--method`、`--input -` 同时经本机帮助核实。
