# Git Worktree 工作流

仅当用户在当前指令中明确要求 worktree 时适用；remote、GitHub 交付、分支或并行任务都不会单独触发。下文操作优先使用 [`mcp-tools.md`](../references/mcp-tools.md) 指定的工具；未提供工具或功能未覆盖时按 [`cli-fallback.md`](../references/cli-fallback.md) 补足，保留必要检查和授权，不能代替成功同步。只读细节见 [`read-only-queries.md`](../references/read-only-queries.md)。操作细节与例外见 [`worktree.md`](../references/worktree.md)；Fork 拓扑见 [`fork-maintenance.md`](../references/fork-maintenance.md)。

原始工作区只用于同步基线和管理 worktree。需求代码、测试、文档、暂存与提交都在对应需求 worktree 中完成。同步、隔离、清理均须符合用户授权及项目权限；创建 worktree 不自动授权提交或 GitHub 操作。

## 队列

| 步骤 | 完成条件 |
|---|---|
| 记录未跟踪内容 | 逐项路径和内容指纹已保存 |
| 审计并同步基线 | remote、默认分支、Fork 状态和工作区已核验，快进同步成功 |
| 创建 worktree | 新目录和分支基于批准的最新基线 |
| 携带未跟踪文件 | 按指纹安全复制，无覆盖 |
| 在 worktree 中实现 | 代码修改和验证均位于需求 worktree |
| 串行交付 | 一个工作项集成后，按发布状态同步下一个需求分支并重验 |
| 合并后状态 | 默认保留 worktree 与本地分支 |

## 1. 记录未跟踪文件

先调用 `capture_untracked_file_manifest`，传入原始工作区的绝对 `repo_path`。工具返回未忽略普通文件的相对路径、SHA-256 和大小；按需求归属分类并保留返回清单。符号链接、特殊文件和 ignored 文件不由该工具复制；对这些内容保留现场并按 [`worktree.md`](../references/worktree.md) 处理，不擅自删除或覆盖。

## 2. 审计并同步基线

调用 `audit_repository_state` 确认仓库、remote、实际默认分支、当前分支、跟踪改动和 Fork `parent`。若有已跟踪未提交内容或无法安全切换/同步，停止并保留现场。

- 普通仓库：调用 `switch_repository_branch` 切到实际默认分支，然后调用 `pull_origin_branch_fast_forward` 快进同步 `origin` 同名分支。
- 个人 Fork：依序调用 `fetch_upstream_branch`、切换到 `main`、`merge_upstream_branch_fast_forward`，再在 `main` 调用 `push_fork_main_fast_forward`；随后切到已核验的个人维护分支。若维护分支存在保护或同步拓扑不明确，停止并读取 [`fork-maintenance.md`](../references/fork-maintenance.md)。
- 未跟踪文件冲突、网络/认证失败、非快进、权限不足或同步结果不确定时，立即停止；不得使用旧 remote-tracking 信息、SHA 或旧分支绕过同步门禁。

只有在最新基线确认同步成功后，才能继续创建需求 worktree。

## 3. 创建并准备 worktree

先用 `check_branch_names` 检查分支名，再用 `list_repository_worktrees` 确认分支未被其他 worktree 使用。调用 `create_repository_worktree` 时明确传入原仓库 `repo_path`、目标绝对路径、唯一分支名和起始基线。普通仓库从刚同步的默认分支创建；Fork 从刚同步的个人维护分支创建。依赖分支只在上层流程已明确批准时使用。

创建成功后，调用 `copy_untracked_files_to_worktree`，将初始清单里允许携带的文件按相对路径复制。工具拒绝覆盖并复核源内容指纹；失败时停止，不手动覆盖。原始工作区副本继续保留，文件不自动暂存或提交。

## 4. 实现与串行交付

在需求 worktree 中实现并按要求验证。只有用户授权暂存和提交时，才用 `stage_repository_paths` 指定完整文件，再用 `commit_repository_changes` 提交；工具只支持整文件暂存。

多个 worktree 可以并行实现，共享同一目标基线的集成依次进行。一个 PR 集成后，按 [`已有 worktree 的基线同步`](../references/worktree-base-sync.md) 获取并固定实际 base OID，再审计接下来准备交付的需求 checkout：已发布分支采用 `merge_repository_branch`，已核实未发布的分支采用增强的 `rebase_repository_branch`。已包含 base 时无需修改，可快进时优先快进；不自动更新所有 worktree，不增加强推能力。同步后按新的 head/base OID 重验，集成前 base 又前进时重新评估。冲突或结果不确定时保留现场，工具不自动 continue/abort/reset。

明确决定继续或撤销本服务发起的冲突操作时，按 [`受限恢复`](../references/worktree-recovery.md) 审计操作记录和最新快照后选择专用 continue/abort 工具；工具不解决冲突、不自动暂存、不调用 skip。未管理操作和不一致状态不自动接管。

合并后默认保留 worktree 与本地分支，不 checkout、pull、merge、rebase、delete 或移除已集成的需求 worktree。只有用户另行明确要求移除 worktree 时才调用 `remove_repository_worktree`；它只移除干净的 worktree 目录，不删除分支。若需清理分支，另按 [`verification-and-cleanup.md`](verification-and-cleanup.md) 中的 PR 清理工具处理。对应工具未暴露时，可按 CLI 补充规约完成已授权清理，仍须核实干净状态、准确路径、分支与 OID；工具拒绝或状态不明时停止。

## 空远端例外

远端确认为空、没有默认分支或没有 PR base 时，先按用户授权处理最小 bootstrap；bootstrap 不得包含需求内容。当前 MCP 未覆盖的初始化操作可按 CLI 补充规约执行；回读核实默认分支与 PR base 后恢复标准流程，不得把需求文件混入初始化提交。
