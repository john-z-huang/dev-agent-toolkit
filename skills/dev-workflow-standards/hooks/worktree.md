# Worktree 与基线操作

## 进入条件

准备新建、同步、恢复或移除 worktree/相关基线时适用。只有用户明确要求新建时才创建；remote、并行工作或已有 worktree 不触发重建。

## 执行条件

创建：准确源仓库、目标路径、分支和基线明确且授权覆盖操作；创建基线需已成功同步，不能用旧引用替代。目标未占用、分支合法且未被检出；携带文件有来源清单和匹配指纹，复制不覆盖且保留原副本。空远端需单独明确最小 bootstrap 范围，初始化不夹带需求内容。见 [worktree](../references/worktree.md)。

同步：准确实际 PR base、发布状态、预期 head/base OID 和干净状态已核验；已发布 merge，未发布 rebase，可快进时快进。不得强推；同步后的验证绑定新状态，base 变化使相关证据失效。见 [同步](../references/worktree-base-sync.md)。

恢复：仅接管本服务受管理的简单操作，操作 ID、HEAD 和最新指纹匹配。continue 要求已解决且正确暂存；abort 要求明确丢弃本次解决内容的授权。见 [恢复协议](../references/worktree-recovery.md)。

移除/清理：用户明确要求且资源身份和干净状态符合工具条件；默认保留已集成 worktree 和本地分支。删除目录不等于授权删除分支。见 [分支清理](../references/pr-merge-cleanup.md)。

## 离开条件

成功：实际资源、OID、复制/同步/恢复/删除结果回读满足所选动作条件。暂停：冲突、失败、过期快照或部分效果，保留现场，不自动 continue/abort/reset。

## 重新进入条件

目标、内容、分支发布状态、head/base OID、操作记录或状态指纹变化；独立动作各自核验。
