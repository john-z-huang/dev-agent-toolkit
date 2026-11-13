# GitHub 仓库迁移到 GitLab

本规则用于把本地 GitHub 仓库迁移到 GitLab 账号或指定 group 下同名项目。迁移是多阶段的本地核验、Git refs 操作及远端写入，不是单次 MCP 操作；当前 MCP 没有批量迁移工具。迁移期间不得修改源 checkout 的 Git 配置。按 [MCP 优先与 CLI 补充](cli-fallback.md) 使用 Git、`gh`、`glab` 等实际 CLI 补足缺口；命令不得传给 MCP 工具。

## 范围与授权

先区分：

1. **Git 仓库数据**：提交对象/历史、分支、标签，以及按需 Git LFS 对象。正常 Git 推送不包含 GitHub 上托管的其他资源。
2. **服务与项目数据**：Issues、PR、Discussions、Releases/附件、Wiki、Projects、Actions/Secrets、webhooks、deploy keys、Packages、Pages、保护规则等。它们不是 Git refs，迁移方法和可保留字段各异。

如果用户未明确范围，先询问是否只迁移 Git 仓库数据，还是还要求迁移哪些 GitHub 资源。缺省不得把平台数据说成已迁移；不得假定 Git push 会迁移它们。范围未明确时可继续独立只读盘点，但不开始相关远端写入。若只要求仓库迁移，按获准的 Git 数据范围处理，**保留 GitHub 源项目和源 checkout 现有 Git 配置不变**。

用户意图、目标项目和每类写入必须明确：创建 GitLab 项目、推送 Git refs/LFS、调整 GitLab 可见性/default branch、迁移 GitHub 资源、归档或删除 GitHub 项目是不同动作。源 checkout 的 Git 配置变更（remote、URL、upstream、push 默认值等）不属于迁移步骤，迁移过程中禁止执行。只执行用户授权范围内的其他动作；授权不足时询问最小缺失决定。不要要求用户粘贴或输出 `GH_TOKEN`、`GITLAB_TOKEN`、`OAUTH_TOKEN`、含凭据 URL 或认证响应。

## 1. 核实源仓库和迁移范围

- 确认目标 checkout 的绝对 Git 根目录；按 GitHub 平台使用 `audit_repository_state`，阅读其 GitHub 远端信息与错误字段。`ok` 只说明本地读取成功，不独自证明账号、remote 和源项目匹配。核实 GitHub 完整 owner/repo、准确源 remote、默认分支及当前实际 GitHub 项目；不只凭本地目录名或 remote 名称判断身份。必要时使用受限只读 `gh`/`git` 查询，remote URL 仅在本地解析，报告前移除 userinfo，不输出原始 URL。
- 记录 `git status`、当前分支、所有本地分支/tag 及 OID，并分别用只读 `git ls-remote --heads <source-remote>` 与 `git ls-remote --tags <source-remote>` 核对 GitHub 上现存 refs。区分远端分支、仅本地分支/提交、远端未有的本地标签；不得因为分支名相同就认为 OID 相同。核实默认分支和是否浅克隆。
- 若 index、tracked/untracked 工作区存在改动，明确哪些内容不会随 Git push 迁移；不自动 commit、stash、丢弃或暂存。用户要求把未提交内容也迁移时，先取得具体纳入范围和相应操作授权，再作为独立步骤处理。
- 检查 Git LFS 是否存在、`git lfs` 是否可用，以及 `.gitmodules` 中的子模块 URL。浅克隆、LFS、子模块和本地独有分支/标签都要列入迁移计划；缺少必要工具、历史或来源证据时暂停相应部分，不宣称完整迁移。

## 2. 核实 GitLab 身份、命名空间和目标

- 确认 `glab` 版本和 `gitlab.com` 上的当前认证身份（例如只读 `glab auth status --hostname gitlab.com` / `glab api --hostname gitlab.com --method GET user`）。`glab` API 认证不自动证明 Git-over-HTTPS/SSH 推送也可用；按仓库现有且已核实的 credential helper 或 SSH 配置选择 Git remote 协议，不打印凭据。
- 从用户指令核实 GitLab namespace（个人账号或 group）和目标完整路径：`gitlab.com/<namespace>/<与 GitHub 同名的 project>`。同名不证明 namespace、账号或访问权限正确；不得自动把 GitHub owner 当作 GitLab namespace。
- 先只读查询目标项目是否存在、项目身份、可见性、default branch 和远端 refs。目标存在但身份不符、包含任意分支/tag/提交、或是否可覆盖无法确认时停止并与用户决定；不得向非空/冲突目标强推、覆盖或自动合并。404/认证/网络错误不能自动当作“项目不存在”。
- 目标不存在时，只有在用户明确授权创建并确认 namespace、可见性（`private`、`internal` 或 `public`）和 default branch 后才能创建空项目。glab CLI 版本/帮助核实后可采用以下合成形状；将路径、branch 和可见性替换成已确认事实，不能省略可见性并依赖实例默认值：

  ```bash
  glab repo create gitlab.com/example-group/example-project --private --defaultBranch main --skipGitInit
  ```

  `--skipGitInit` 避免创建项目时顺手改造当前本地仓库或 clone；不选择 `--readme`，以免产生与源仓库不相干的初始提交。创建后立即回读项目路径、可见性和 default branch。若 glab 当前版本不支持该参数组合，按帮助/官方文档调整，不猜参数、不改用隐藏默认值。

## 3. 迁移 Git refs 和对象

仅在源、目标都已核实，目标为空或 refs 已被逐项证明兼容，并且用户授权推送后开始。保留 GitHub 源项目和源 checkout 的现有 Git 配置：不得新增、删除、重命名或改写 remote，不得写入 `.git/config`，不得修改 remote URL、fetch/push URL、分支 upstream 或 push 默认值。将经核实且不含凭据的 GitLab 目标 URL 作为单次 Git/LFS 命令参数；若某 CLI 或认证方式要求在源 checkout 添加 remote、改配置或设置 upstream，则停止该路径，改用原项目之外的隔离临时 clone/copy，或报告无法安全继续。若 Git credential 未就绪，停止并说明缺口，不把认证失败改写成能力缺口。

- 用源端当前 ref 清单作为范围，不以工作区或 `git show HEAD` 代表完整仓库。确认本地没有将与临时抓取 ref 冲突的 `refs/migrate/github/` 命名空间后，可将 GitHub 远端 refs 抓取到独立命名空间，避免覆盖本地分支和标签：

  ```bash
  git fetch --no-tags <github-source-remote> 'refs/heads/*:refs/migrate/github/heads/*'
  git fetch --no-tags <github-source-remote> 'refs/tags/*:refs/migrate/github/tags/*'
  ```

  第二条仅在源仓库有 tags 时执行。禁止加 `--prune` 或 `+` 强制 refspec；目标命名空间已有内容、非快进冲突或抓取失败时停止并回读，不清理/覆盖旧 refs。若仓库为 shallow，先明确取得完整历史所需授权；不能把浅历史上传说成完整迁移。
- 用抓取前记录的精确分支/tag 名称及 OID 核对临时 refs。可将源端 refs 映射到空 GitLab 目标（示例是映射形状，不是可直接复制的目标仓库）：

  ```bash
  git push <verified-gitlab-target-url> 'refs/migrate/github/heads/*:refs/heads/*'
  git push <verified-gitlab-target-url> 'refs/migrate/github/tags/*:refs/tags/*'
  ```

  无对应 refs 时省略相应 push。不要用 `git push --mirror`：它可能强制改写或删除目标端 refs；不要用 `--force`、`--force-with-lease` 或自动删除目标端 refs。受保护分支拒绝时保留保护并停止，由用户/项目管理员决定合规配置，不绕过保护。
- 另行对比本地分支/tag 与 GitHub 源 refs。用户要求纳入的本地独有分支/标签，可在不存在同名冲突且可正常快进写入时逐项推送；同名 refs 指向不同历史、彼此分叉或标签对象冲突时停止，展示安全的名称/OID 摘要并询问保留、改名或排除，不自动 merge、改写历史或覆盖。不得将本地未提交文件包装成已迁移提交。
- 若检测到 Git LFS 文件，必须验证 LFS 客户端和 GitLab LFS 可用性，并按授权将相关 refs 的 LFS 对象传至 GitLab，例如 `git lfs push --all <verified-gitlab-target-url> <approved-ref>...`，显式列出本次获准迁移的分支/tag；仅 Git refs 推送成功不足以证明 LFS 完整。执行前按本机 Git LFS 版本核实目标 URL 是否受支持、参数和 refs 范围；若需在源 checkout 配置 remote，则改用原项目之外的隔离临时 clone/copy 或停止，不修改源 Git 配置。LFS 上传失败/不明时先只读核对，不盲目重试。
- Git submodule 的 repository 是独立仓库，普通 push 不会把它们迁入目标。记录 `.gitmodules` 中已核实的 URL 和可达性；只有用户明确要求时，才可将子仓库作为独立仓库按同一流程迁移。迁移流程不得修改父项目的 `.gitmodules` URL 或源 checkout Git 配置；若后续工作必须变更这些配置，停止该迁移步骤并单独报告，不自行修改。

命令必须由宿主按当前 CLI 能力、安全边界和既有授权执行；先后依赖的步骤依次核验。Git refs 写入、项目创建及 LFS 上传分别评估副作用；不得把 shell 命令传入 MCP 领域参数。迁移期间不得变更源 checkout 的 Git 配置。

## 4. 回读验收

push 的退出码不够。分别用只读 `git ls-remote --heads <verified-gitlab-target-url>` 与 `git ls-remote --tags <verified-gitlab-target-url>` 回读目标 refs，与迁移范围内的源 OID 清单逐项比较分支/tag 名和对象 ID；所有应迁移的 refs 都须存在且匹配。另核实 GitLab 项目 namespace、可见性、default branch，LFS 对象可读，以及所需子模块仍可取用。任何缺失、差异或 API/网络错误均为未完成；先回读实际效果，不重复创建或盲目推送。

GitLab default branch 若与确认的 GitHub default branch 不一致，只有在 refs 已存在且用户明确授权调整项目设置后修改并回读；保护/权限策略不能由默认分支名称推定。

## 5. 保持本地 Git 配置不变

- 本迁移流程绝不对源 checkout 执行本地 cutover：不把 GitLab 设为 `origin`，不把 GitHub remote 改名为 `github`，不添加临时 remote，不改 remote URL、fetch/push URL、分支 upstream、push 默认值或 `.git/config`。现有配置必须保持原样。需要使用命名 remote 的 CLI 操作只能在源项目之外的隔离临时 clone/copy 中进行；优先将经核实的 GitLab URL 作为单次命令参数。迁移期间不因用户提出切换要求而修改源配置；将其留作迁移之外的独立后续任务。
- GitHub 项目保持原状。归档、删除、改名、转移 owner、关闭 Issue/PR、改写外部链接、撤销 secrets/keys 或修改可见性都是单独操作，须有分别覆盖该动作的明确授权及回读。
- 若用户要迁移 Issues/PRs、Releases、Wiki、CI、保护规则等 hosted data，先逐类列出源对象范围、GitLab 目标表示、缺失/不可映射字段和可验证结果；按目标 GitLab.com 当前官方功能及必要的 `gh`/`glab` 文档确认方法。PR→MR、Issue 编号、标签/里程碑、评论/审核、附件、wiki refs、CI secrets 与保护策略不能假定一一对应。凭据只使用本机已认证 CLI/安全凭据机制，不嵌入 URL、日志或文件；无官方、可核对的路径或授权不足时，明确报告该类未迁移，不声称全量完成。

## 完成报告

按类别报告：已核实的 GitHub 源和 GitLab 目标；迁移的分支/tag 数量及 OID 验证结果；LFS/submodule 状态；default branch/可见性；源 checkout 的 Git 配置是否保持不变；仍保留在 GitHub 或未迁移的 hosted data；实际验证及失败/不明项。不要把“Git refs 已迁移”说成“整个 GitHub 项目及其服务数据全部迁移”。
