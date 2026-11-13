# 已有 worktree 的基线同步

GitLab 仓库同样适用本文的通用 Git、拓扑、授权和保留条件；PR 对应 MR，平台工具、字段及例外按 [GitLab 兼容规则](gitlab.md) 选择，不直接执行本文的 GitHub 专属命令。

适用：需求 worktree 已存在，而其实际目标 base 已合入其他 PR；或用户要求检查、更新该需求分支。只检查已有 checkout 不要求重新创建 worktree，也不授权同步其他 checkout。创建新的 worktree 仍遵循 [`worktree.md`](worktree.md) 的创建前同步门禁。

多个 worktree 共享大部分分支引用，各自的 HEAD、index 和工作目录独立。获取远端引用或更新本地默认分支不会自动让需求分支包含新提交。同步的验收条件是需求分支包含本次核验的目标 base，且自身需求提交得到保留；不是让所有 worktree 的 HEAD 相同。

## 确认目标与授权

- 用 `audit_repository_state` 核对准确的需求 checkout 根路径、仓库身份、默认分支和 Fork parent；用 `list_repository_worktrees` 确认分支所在路径。所有 repo-bound 工具明确传入该目标的绝对 `repo_path`。
- 已有 PR 使用核验过的实际 base；尚无 PR 时，使用用户批准的依赖分支或仓库约定。Fork 按 [`fork-maintenance.md`](fork-maintenance.md) 使用个人维护基线；不得机械地选择 `main`。堆叠 PR 另读 [`stacked-pr.md`](stacked-pr.md)。
- 区分只读审计、fetch 的本地引用写入、merge/rebase 的工作区及历史写入、推送与 PR 更新。只读结果、工具可用或同步成功都不授予后续写入权限；沿用已有明确授权，不扩大到其他分支、checkout 或外部动作。

## 获取基线与审计快照

在授权范围内调用 `fetch_repository_branch` 获取已确认 remote 的实际 base。该工具不切换 checkout、不更新本地 `main`、不合并、不推送；无需为了更新需求分支先切换或修改另一个 worktree。只能采用成功回读的引用和 OID；失败、不完整或结果不确定时停止，不拿旧缓存冒充成功获取。

随后调用 `audit_worktree_base_sync`，核对当前分支、head/base OID、merge-base、ahead/behind、dirty、detached、锁定及进行中的 Git 操作。审计不会隐式 fetch；其关系判断针对本地已存在的对象，不能单独证明远端此刻没有新提交。发布状态未知、认证或网络失败时，不得把本地缺少远端跟踪引用解释成未发布。

保存本次成功获取的 base OID、需求 head OID 和对应来源。使用工具 Schema 支持的预期 OID 参数在写入前重新核验；同名分支引用若已移动，重新审计，不把旧快照用于新的写入。

## 策略选择

| 已核验状态 | 动作 |
|---|---|
| 需求 head 已包含目标 base | 无需同步；继续检查验证证据是否适用。 |
| head 可快进到 base | 在对应授权内快进；仍使用有前置校验与回读的同步工具。 |
| 未发布需求分支与 base 分叉 | 使用 `rebase_repository_branch`；先核实发布状态，重放自己的需求提交。 |
| 已发布需求分支与 base 分叉 | 使用 `merge_repository_branch`，保留已有公开提交；后续仍使用普通非强制 push。 |
| 发布状态或提交边界不明 | 停止依赖这些事实的修改，补齐证据。 |
| dirty、detached、锁定、未完成操作或冲突 | 保留现场，按 [`恢复条件`](../hooks/recovery.md) 处理。 |

已发布包括已有远端需求分支；已知有 PR、协作者或下游分支消费者时，不能仅凭某个远端同名引用不存在就当作可改写的私有分支。工具的发布状态核验只证明其明确查询的范围，不取代这些已知事实。没有远端配置也不证明历史上从未发布。

当前策略不支持改写已发布分支后的强推；不要为绕过拒绝而删除远端分支、另换推送入口或使用裸 `--force`。merge 失败也不自动切换为 rebase。

## 堆叠分支与 squash

父 PR squash 合入目标分支后，原父提交通常不成为 squash 提交的祖先；不能只凭祖先检查就断言内容尚未集成。先核验父 PR 的合并结果、旧父分支边界及子需求自己的提交范围。

未发布子分支需要迁移时，可使用增强 rebase 的旧边界参数，在新 base 上仅重放属于子需求的提交。边界必须是核验过的具体提交，并满足工具的祖先校验；工具不证明这些提交的业务归属。缺少旧边界或无法排除其他需求时停止，不猜测 merge-base、不重复带入父需求。

已发布子分支继续采用 merge。若这不能得到可独立审查的 PR 差异，报告需要调整的拓扑和差异，等待该调整的明确决定，不悄悄改写公开历史。PR base 更新是独立动作，当前同步工具不执行它。

## 并发、冲突与重新验证

- 多个需求可以并行实现；同一目标 base 的集成依次进行。一个 PR 集成后，仅审计和更新接下来准备交付的需求分支，不批量修改其他 Agent 正在使用的 checkout。
- 固定本次 base OID；执行前复核当前分支身份、head/base OID、干净状态和未完成操作。工具内部协作锁仅协调遵守该锁的调用，不是对所有 Git、编辑器或普通文件修改的全局锁。
- 不自动 stash、commit、reset、clean、删除、移动或覆盖用户内容，不让 rebase 的隐式 updateRefs/autostash 扩大动作范围。正常 Git hooks 仍可能执行，工具结果不能替代对 hooks 副作用的授权判断。
- 冲突或失败保留现场；查看结构化状态、冲突路径及回读结果。服务发起的同步会在当前 worktree 的 Git 元数据目录保留专属恢复记录；只有明确选择继续或撤销时，才按 [`受限恢复`](worktree-recovery.md) 重新审计并调用对应工具，不自动 continue/abort 或回滚。命令失败或回读不确定不等于没有发生写入，先只读检查，不盲目重试。
- 同步后重新运行适用测试和检查，记录实际需求 head OID 与本次 base OID。同步成功只证明 Git 操作及其回读满足工具条件，不证明业务正确或测试通过。
- 推送/合并前重新核对实际 PR base、head 和远端变化。base 已前进时重新评估同步及验证；旧 head 或旧 base 上的通过记录不能冒充新提交的验证。已获推送授权时继续使用 `push_issue_branch_to_origin`，不增加强推能力。

Git 行为依据：[worktree 引用共享](https://git-scm.com/docs/git-worktree#_refs)、[rebase --onto](https://git-scm.com/docs/git-rebase#_transplanting_a_topic_branch_with_onto)。参数、错误分类和副作用以 [`MCP 工具目录`](mcp-tools.md) 与实际发现的 Schema 为准。
