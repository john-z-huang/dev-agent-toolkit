# Git Worktree 开发与交付

仅当用户明确要求 worktree 时使用。Git 仓库、remote、GitHub 交付或并行任务本身不触发该模式。下文操作优先使用 [`mcp-tools.md`](mcp-tools.md) 中的对应工具；未提供工具或功能未覆盖时按 [`cli-fallback.md`](cli-fallback.md) 补足，保留必要检查、授权及创建前同步门禁。只读细节见 [`read-only-queries.md`](read-only-queries.md)。

## 工作区边界

- 一个完整需求使用独立 worktree 和工作分支；仅可独立审查的拆分工作项才并行。
- 原始工作区用于基线同步、查看和管理 worktree；代码、测试、配置、文档、暂存与提交都在需求 worktree 完成。
- worktree 不授权 GitHub 写入或提交。保留原始工作区现有文件和用户改动。

## 已有 checkout 原地建分支

当前 checkout（包括宿主已经准备好的 detached worktree）仅需从当前 HEAD 建立工作分支时，走普通开发工作流，使用 `create_repository_branch`；无需再创建 worktree。先审计该 checkout 的准确根目录，再按授权传入 `repo_path`、新 `branch_name` 和可选 `expected_head_oid`，核对返回的分支及 OID。

该工具保留已有文件和 index，只新增分支、更新 HEAD 及对应 reflog。它不提供任意起点、同步基线、复制文件或配置 tracking 的能力；也不能代替下述“新建另一个 worktree”所需的同步门禁。锁定、未完成 merge/rebase、引用冲突、有效的 reference-transaction Hook 或不支持的 Git 事务语法均须先处理，工具不会强制继续或自动提权。详细边界见 [工具目录](mcp-tools.md#原地创建工作分支)。

## 创建前的同步门禁

先用 `audit_repository_state` 检查准确仓库根目录、分支、tracked 状态、remote、默认分支和 Fork parent。已跟踪改动妨碍切换或同步时，先停止；不得暂存、清理、移动或覆盖用户内容。

- 普通仓库：`switch_repository_branch` 切换到实际默认分支，`pull_origin_branch_fast_forward` 同步同名远端分支。
- Fork：按 [`fork-maintenance.md`](fork-maintenance.md) 快进同步上游 `main`，再基于个人维护分支创建需求 worktree。
- 只有同步成功后才能创建需求 worktree；remote-tracking 引用、SHA 或旧本地分支不能代替成功同步。
- 网络、认证、权限、非快进或文件冲突失败时，保留现场并按恢复流程处理。

## 保留未跟踪文件

`capture_untracked_file_manifest` 为未忽略的未跟踪普通文件生成相对路径、SHA-256 与字节数；清单需要保留在当前任务上下文中，并标记是否属于需求。工具不包括 ignored 文件，也拒绝符号链接或特殊文件。

创建基线冲突时，不覆盖文件、不使用 reset/clean/stash，也不改名或移动。目标 worktree 建立后，用 `copy_untracked_files_to_worktree` 按清单复制；工具会再次核验源指纹、路径安全、目标仓库及目标未占用状态。若调用返回部分复制，依据 `copied` 列表核对，保留原始副本并停止继续处理失败项。文件不会自动暂存或提交。

要携带 ignored、symlink 或特殊文件时，先核实是否在授权范围、实际文件类型及目的地安全性；工具不覆盖的类型可按 CLI 补充规约单独处理，不能绕过已发生的工具安全拒绝。跨 worktree 恢复未跟踪文件也可按该规约核实来源、目标和指纹后复制；不猜测、不覆盖，保留原始副本。

## 创建并实现

1. 用 `check_branch_names` 校验新分支名；用 `list_repository_worktrees` 确认目标分支未被检出。
2. 用 `create_repository_worktree` 传入原仓库路径、目标绝对路径、新分支和已同步的本地基线。它拒绝已存在的路径/分支以及在源仓库目录内创建。
3. 按上一节复制允许携带的未跟踪内容；然后只在该 worktree 中实现和验证。

若 Fork 的个人维护分支缺失，先核对初始化方案：`create_repository_branch` 只允许以当前 HEAD 原地建分支，不能代替首次添加 `upstream`、确认维护基线或配置 tracking；未封装步骤按 CLI 补充规约在既有授权内完成。维护基线不明时停止，不自行猜测。

## 并行工作与串行交付

共享同一目标基线的工作项依次集成。一个 PR 集成后，按 [`已有 worktree 的基线同步`](worktree-base-sync.md) 获取实际 base 并审计接下来准备交付的 checkout；已发布分支 merge，已核实未发布分支 rebase，可快进时优先快进。该流程可直接从已有需求 worktree 进入，不创建新 worktree，也无需先切换另一个 checkout 更新本地 `main`。固定并复核 head/base OID，同步后重新验证；冲突或结果不确定时保留现场，不自动继续、abort、reset 或强推。

用户明确选择继续或撤销本服务发起的操作时，改读 [`受限恢复`](worktree-recovery.md)；恢复记录不是授权，操作ID、head与最新状态指纹必须匹配，不能把别的worktree或手工操作当作当前恢复目标。

已集成 worktree 默认保持原状。只有用户明确要求移除时，才调用 `remove_repository_worktree`；该工具只移除干净的指定 worktree 目录，不删本地分支或远端分支。清理分支另按 [`pr-merge-cleanup.md`](pr-merge-cleanup.md) 执行。

## 空远端

空远端、无默认分支或无 PR base 时，标准同步门禁不成立。先核实最小 bootstrap 范围与授权；当前 MCP 未覆盖的步骤按 CLI 补充规约执行，回读确认默认分支/PR base 后再恢复标准同步流程，不要把需求内容混入初始化操作。
