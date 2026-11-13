# 受限的 merge/rebase 恢复

GitLab 仓库同样适用本文的通用 Git、拓扑、授权和保留条件；PR 对应 MR，平台工具、字段及例外按 [GitLab 兼容规则](gitlab.md) 选择，不直接执行本文的 GitHub 专属命令。

适用：[`基线同步`](worktree-base-sync.md) 发起的 merge/rebase 因冲突或失败停止，需要继续或撤销本次操作。恢复是独立的写入动作，不能把原同步授权、错误返回或恢复记录当作继续、撤销或丢弃用户内容的授权。

## 可恢复范围

只处理本服务发起、具有当前 worktree 专属恢复记录、且能与 Git 原生操作状态逐项对应的简单 merge/rebase。记录用于关联操作 ID、原分支、原 head、固定 base 和操作范围；不是权限凭证，也不证明冲突内容正确。

- 原服务版本发起但没有记录的操作、手工发起的操作、记录丢失或损坏的操作不自动接管。
- 不恢复其他 worktree 的操作；不将共同 Git 目录、相同分支名或相同 OID 当作同一 checkout。
- 只支持单一 merge 或使用 merge backend 的简单 rebase；不接管 rebase apply backend、用户自定义交互重排、exec/edit、复杂合并重放、多头 merge、混合操作、autostash、未知或已被改写的重放计划。普通 rebase 也可能有内部 `interactive` 标记，校验依据是记录与实际重放指令，不是这个文件名。
- 已在服务外继续、撤销或修改元数据而使记录与 Git 状态不一致时停止；不重建记录、不篡改元数据、不删除记录来绕过保护。
- 没有有效恢复上下文时，保留现场并报告需要的明确恢复决定；不把普通 Git reset、skip、quit 或自动回滚当作后备。

恢复快照是有界的：记录最多 256 KiB，单个原生操作元数据文件最多 1 MiB，index 最多 16 MiB，单个受检工作文件最多 8 MiB、合计最多 32 MiB，最多 4096 个路径及 20000 个待重放提交；记录序列化上限也可能更早限制提交数。超限、链接或特殊文件导致无法安全核验时拒绝恢复，不截断后放行，也不为通过检查修改文件。ignored 检查限定于与管理范围重叠的路径，不读取无关的依赖目录内容。

## 先审计，再选择动作

1. 对准确的需求 checkout 调用 `audit_worktree_base_sync`，使用该操作固定的 `base_oid` 作为 `base_ref`，省略 `remote` 或传 `null`，获取恢复上下文、当前操作状态和最新状态指纹。rebase 进行中可能暂时处于 detached HEAD；恢复工具按匹配记录中的原分支处理，普通同步入口仍拒绝 detached HEAD。无需在此审计联网查询临时 HEAD；rebase continue 会自行核验记录中的远端。
2. 核对操作 ID、类型、原分支/原 head、base、当前 head、冲突路径及阻塞项。修改冲突文件或 index 后必须重新审计；旧快照不能用于新状态。
3. 按用户明确意图选择一种动作；将 `recovery_context.operation_id` 传入 `operation_id`，将 `recovery_context.current_head_oid` 传入 `expected_current_head_oid`，将审计顶层的 `current_state_fingerprint` 传入 `expected_state_fingerprint`。工具在协作锁内重新核对，过期或不一致则停止。

同步审计的顶层 `status` 在存在未完成操作时为 `blocked`，表示不能另起同步，并不单独决定是否可以恢复。恢复需检查 `recovery_context.status`：`managed_in_progress` 表示已核验的受管理操作；`none` 表示没有恢复目标；`unmanaged` 表示原生操作缺少本服务记录；`needs_review` 表示记录或原生状态无法安全匹配。只有第一种状态和非空 `current_state_fingerprint` 可用于准备恢复调用，仍需满足所选动作的内容与授权条件。

| 目标 | 工具 | 条件与结果 |
|---|---|---|
| 完成已解决的 merge | `continue_repository_merge` | 冲突已解决并正确暂存，无未合并 index 或未暂存的解决内容；可能创建 merge commit，保留原 head 与固定 base。 |
| 继续未发布分支的 rebase | `continue_repository_rebase` | 同样核对已暂存解决内容；再次联网确认指定远端同名分支未发布，再执行一次 continue。 |
| 撤销本次 merge | `abort_repository_merge` | 明确授权撤销并确认丢弃本次冲突解决内容，核对最新快照；离线执行原生 abort 并核对恢复原分支/head。 |
| 撤销本次 rebase | `abort_repository_rebase` | 同上；不依赖远端可用性，不另行调用 reset、stash 或其他补偿命令。 |

## Continue 的内容边界

工具不选择业务解决方案，不编辑文件、不自动 stage、不调用 skip，也不根据模型建议决定哪些提交可以丢弃。只有已批准的机械冲突解决可在现有范围内处理；需要新业务或架构决定时先停止。空提交或不受支持的重放状态需要另行决定，不能由工具通过 skip 或造出空提交来推进。

暂存解决内容是独立步骤。已有精确暂存工具不覆盖冲突 index 的情况时，不将它的安全拒绝解释成允许绕过；可以由用户在其环境中完成已批准的冲突解决与暂存，再审计后继续。不得伪造“已解决”或只凭文本冲突标记消失宣布可以继续。

正常 Git hooks 继续运行；非交互执行不等于跳过检查。工具不打开编辑器、不接收编辑器或 shell 命令、不触发自动 updateRefs/autostash。一次 rebase continue 可能推进多个提交，也可能停在下一个冲突；`still_in_progress` 不是最终完成，需要审阅新的冲突和快照后再次决定，不自动循环。

Continue 成功后核对操作已经结束、需求分支身份、固定 base 的祖先关系及工作区状态，再按新的 head/base 重新运行项目检查。工具创建了提交或结束了 Git 操作，不代表业务测试通过、已推送或 PR 已更新。

## Abort 的丢弃边界

Abort 会丢弃本次操作的冲突解决内容，不能作为“无损检查”使用。调用前必须有对该动作和丢弃范围的明确授权，并使用 Schema 中必填的丢弃确认值；该值须明确为 `true`，不是 `null`、省略或由工具自行默认。参数本身不提供用户授权。

无关文件编辑、未跟踪或 ignored 文件不能被静默删除或覆盖。工具核对管理范围和恢复原树时的路径碰撞，无法确认保留条件就拒绝，不自动 clean、移动、暂存或保存临时副本。明确授权本次 abort 也不扩大为删除其他工作或撤销其他 worktree 的操作。

## 失败与结果不确定

恢复工具不会自动重试、abort、skip 或 reset。每次调用后核对 `action_started`、`completed` 或 `aborted`、`still_in_progress`、`needs_review` 及恢复上下文；`ok=false` 或回读失败不能解释成没有副作用。先进行只读审计，确认事实后再决定下一步。`completed=true` 表示 continue 经最终回读完成，`aborted=true` 表示 abort 经回读恢复原分支/head；只有同时满足工具的成功条件才可采纳，不得用单个动作标志宣称完成。

经过最终状态回读确认的完成或撤销才清理本次恢复记录。仍有冲突或状态不确定时保留记录；记录清理失败也必须如实报告，不能伪装成普通成功。协作锁和状态指纹提供有边界的并发检查，不能阻止不遵守锁的其他 Git 进程或普通文件编辑。

记录在 Git 动作前写入，因此启动中断也可能留下记录。记录存在而原生操作未开始或已经结束时，先核对真实分支、head、index 和工作目录；不要为重试同步直接删除记录或重新创建操作。该不一致状态需要明确的检查与恢复决定，四个受限入口不负责自动清理或接管它。

Git 原生语义见 [rebase 的 continue/abort](https://git-scm.com/docs/git-rebase#_mode_options) 与 [merge 的恢复选项](https://git-scm.com/docs/git-merge#_options)。具体参数、限制、输出和联网注解以 [`MCP 工具目录`](mcp-tools.md) 与实际发现结果为准。
