# GitHub 操作策略

GitLab 按 [GitLab 兼容规则](gitlab.md) 选择对应工具及字段。Issue、推送、PR/MR 拓扑、证据和授权策略跨平台一致；不能把 `gh` 或 GitHub `owner/repo` 直接用于 GitLab。

下文操作优先使用 [`mcp-tools.md`](mcp-tools.md) 中对应工具或当前已授权的 GitHub Connector/App；未提供工具或功能未覆盖时，按 [`cli-fallback.md`](cli-fallback.md) 补足查询或已授权写入，保留必要检查。只读细节见 [`read-only-queries.md`](read-only-queries.md)。禁止浏览器和浏览器自动化。服务器调用本机 `gh` 身份，不收集、不输出令牌。

## 授权、网络与身份

- 每次外部写操作都须有覆盖该操作的用户授权并满足执行层审批；已有授权在原范围内持续有效，无须重复索取。Skill 加载、工具可用或注解均不自动授权。
- GitHub 网络/认证问题按恢复条件处理；不得因代理/API 不通直接判定登录凭据失效，也不得要求用户粘贴 token。
- `GH_TOKEN` 与其他凭据不得打印、回显、插值、记录或写入文件/参数/错误报告。出错时只保留非敏感摘要。
- 目标仓库、Issue/PR 编号、assignee 和 base/head 必须来自当前任务或工具返回值，不猜测账号/权限。

### 多账号核验

1. 先从准确的本地仓库根目录和本次操作对应的 remote 核实目标 `HOST/OWNER/REPO`。Fork 的源仓库和目标仓库分别核对。运行任何 `gh` 命令或调用访问 GitHub 的 MCP/Connector 工具前，先运行 `ghwho` 查看当前账号。命令不可用或无法确认身份时，暂停相关 GitHub 操作并报告具体原因。
2. 确认当前账号是目标仓库所属账号，或具备本次操作所需的访问权限。需要进一步核实时，按准确仓库只读查询，例如 `gh repo view HOST/OWNER/REPO --json nameWithOwner,viewerPermission`。公开仓库可读取只说明能读取。写操作还须核对所需权限与动作条件。使用独立凭据的 MCP/Connector 还须核实该连接实际使用的账号及权限。本地账号切换只影响使用该本地登录配置的入口。
3. 运行 `ghwho` 后，可用 `gh auth status` 查看本地所有已登录的 GitHub 账号及其认证状态，输出按主机分组并标记活动账号。仅核对目标主机的候选账号时，可用 `gh auth status --hostname HOST --no-refresh`。当前账号不适用时，按需使用 `gh auth switch --hostname HOST --user LOGIN` 切换。每次切换后重新运行 `ghwho`，再核验目标仓库和所需权限。切换会改变该主机的本地活动账号，须遵守宿主写入审批。若环境凭据覆盖了本地选择，或工具运行环境不同，须确认实际生效的身份后再继续。
4. 该主机已登录的账号均缺少所需权限时，停止目标 GitHub 操作，向用户报告目标仓库、所需操作、已核验账号及非敏感结果，请用户介入。网络故障、认证状态不明或权限核验失败时，按实际原因报告，避免把未知状态归为所有账号均无权限。

命令参数见 [GitHub CLI 账号状态](https://cli.github.com/manual/gh_auth_status)、[账号切换](https://cli.github.com/manual/gh_auth_switch)和[仓库查询](https://cli.github.com/manual/gh_repo_view)。

## Issue

任何待推送功能或修复必须有关联的开放 Issue。用户明确要求推送时，若没有相关 Issue，可以按该用户指令直接补建，不再另问。

- 用 `audit_repository_state` 确认目标仓库与 GitHub 身份；用 `list_github_issue_labels` 读取仓库现有标签。
- 按 Issue 的主要目的选择至少一个已有工作类型 label；辅助标签不能替代工作类型 label。不得把未核验的 GitHub 默认标签说成仓库已有标签。
- 正文说明需求/缺陷、影响、预期行为和验收标准，必要时补充复现、约束或依赖。
- 获得创建授权后调用 `create_github_issue`。工具只接受已存在的 label，默认指派当前账号并回读状态/labels/assignee；校验失败时停止推送。

## Issue/PR 文案的提交证据范围

Issue/PR 若用于交付已有 Git 改动，必须参考所有待交付的 git commit patch，而不仅是最后一个 commit patch。调用方先核实目标 base/head、比较基点（通常为 merge-base）及完整提交列表，逐个读取该范围内的 patch（含已推送但尚未进入目标 base 的提交，不以未推送范围替代 PR 范围），再提供覆盖每个提交的有界事实摘要和可追溯 SHA/路径；结合整个范围的最终净 diff 归纳重要变更，后续修正或回退不得描述为仍生效。不得仅用 git show HEAD、最后一次提交或工作区 diff 代表全部改动；无需向模型发送所有原始 patch，可分批收集但不得静默截断或遗漏提交。范围未知、patch 未读全或摘要仅覆盖部分提交时，在 missing_facts 标明缺口，不得声称完整。纯需求/缺陷 Issue 尚无对应提交时此规则不适用，不得编造提交或强制索要 patch。

## 推送与 PR

- 推送前检查开放 Issue、分类 label、本人 assignee、分支拓扑、测试、提交范围和用户授权。
- `push_issue_branch_to_origin` 只推送当前同名分支到 `origin`，不强推；Fork 的镜像 main 使用独立工具并遵守 Fork 流程。
- PR 正文需说明范围和验收，并用 `Closes #N`、`Fixes #N` 或 `Resolves #N` 关联 Issue。获授权后使用 `create_github_pull_request`；工具通过临时 body-file 创建、默认指派本人并保持 PR 开放。
- 创建后用 `audit_issue_pr_policy` 核对开放状态、关联关系和预期 base/head。推送/创建/审计失败时停止后续交付。

## 合并

不自动合并 PR。只有用户明确授权且 required checks 通过、PR 可合并、无 changes-requested 时调用 `merge_github_pull_request`。Fork 需求 PR 合并到个人维护分支；`main` base 只允许 squash。合并后回读实际 base 和状态。

## 能力边界

MCP 不提供 branch protection/rulesets 的增删改查、首次 upstream URL 配置或 GitHub 账号修复工具。能力缺口可按 CLI 补充规约处理；保护规则回读遵守只读规约，修改须有对应授权并回读确认。权限/认证等实际失败仍须先处理原因，不能换入口绕过或把失败解释为无规则；不通过打印 token 修复账号。
