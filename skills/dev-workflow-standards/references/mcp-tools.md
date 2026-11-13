# MCP 工具目录

## GitLab 对应工具

GitLab 使用 `glab`，不使用 `gh` 或 GitHub `owner/repo` 校验。9 个对应工具及参数/副作用差异见 [GitLab 工具对应关系](gitlab.md#工具对应关系)；工具 Schema 与 MCP 初始化说明也暴露相同合同。所有 GitLab 工具必填 `repo_path` 与 `repo=host/group[/subgroup]/project`，支持自托管及多级 group；不调用 OpenAI、不读会话、不写 Memory/配置。具体写入仍需用户授权与适用宿主审批。GitHub→GitLab 仓库迁移是多阶段 CLI 操作，目前没有单一迁移 MCP 工具；迁移期间必须保持源 checkout 的 Git 配置不变，不得切换 origin 或增删 remote；范围、目标创建、refs/LFS 回读和 hosted data 边界见 [迁移指令](github-to-gitlab-migration.md)。

| 工具 | 其他参数 | 关键返回及副作用 |
|---|---|---|
| `audit_gitlab_repository_state` | 无 | `ok` 本地读取；`gitlab/gitlab_error` 独立，联网只读。 |
| `list_gitlab_issue_labels` | 无 | `ok/labels/limit`，联网只读前 100 项含继承标签。 |
| `create_gitlab_issue` | `title, body, labels` | 创建并回读 Issue，`ok/created/issue`；结果不明 `created=null,write_attempted=true`。 |
| `push_gitlab_issue_branch_to_origin` | `branch_name, issue_number` | `ok/error`，核实 Issue、origin 后非强推当前同名需求分支。 |
| `create_gitlab_merge_request` | `title, body, base_branch, head_branch, issue_number` | 创建并回读同项目开放 MR，`ok/created/merge_request`，不推送、不删 source。 |
| `audit_issue_mr_policy` | 可选 `issue_number, mr_number, expected_base, expected_head` | 至少一个编号，分支比较需 MR；`passed/errors`，确定性联网只读，不调用 Decisions。 |
| `merge_gitlab_merge_request` | `mr_number, merge_method` | `ok/merged/pre_merge_head_oid`，合并远端 MR；main 只 squash，不自动合并/删 source。 |
| `push_gitlab_fork_main_fast_forward` | 无 | `ok/error`，真实 Fork 镜像 main 的非强推。 |
| `cleanup_merged_mr_local_branch` | `mr_number`；可选 `branch_name, merged_head_oid` | `completed/actions/error`，单独清理授权后切换/快进 pull/删除本地 source，保留精确 OID 强删门禁。 |

可选字段默认 `null` 表示未请求；`merged_head_oid=null` 不允许强制删除。Issue/MR 编号为项目内正数 iid，不是全局 id。`created=true,ok=false` 或写入不明均先回读，不能自动重复写入。

本项目支持在 Codex 或 Pi Code Agent 中注册并使用 Python MCP 服务 `dev-workflow-standards-tools`。操作优先选择本表中覆盖需求的工具或已授权 Connector；无对应工具、工具未暴露或功能/参数未覆盖时，按 [`cli-fallback.md`](cli-fallback.md) 自行用 CLI 补足查询或已授权写入，保留必要检查，不绕过实际失败。MCP 仍只接受领域参数，不传 shell、git、gh 或测试命令。所有 repo-bound 工具都要求本次目标仓库的绝对 `repo_path`，且只在该 Git 根目录/worktree 内操作；不要假设 MCP 进程启动目录就是目标项目。

只读工具带 `read_only_hint`；其他工具带写入/破坏性注解，Codex 服务配置为 `default_tools_approval_mode="writes"`。`Codex writes approval` 仅指 Codex 宿主审批；Pi Code Agent 未提供该机制时，按 [Skill 宿主审批兼容](../SKILL.md#宿主审批兼容) 执行：不要求不存在的审批工具/Hook，仍须有对应用户明确授权，遵守实际宿主权限和本地校验，不得绕过实际拒绝或错误。这些确认与注解不取代 Skill 中的用户授权前置条件。`gh` 工具使用本机已授权的 GitHub CLI，不接受或输出令牌。

## OpenAI 判断与生成

所有 Decisions、Responses 和输入审核请求共用 `OPENAI_TIMEOUT_SECONDS=180` 秒；仅请求超时在调用处立即串行重试，`OPENAI_TIMEOUT_MAX_RETRIES` 环境变量为非负整数，未设置默认 `5`、`0` 关闭，空值或非法值在请求前安全失败。默认最多 6 次 API 尝试，SDK 内部重试关闭；预算耗尽返回 `api_timeout`，其他错误不自动重试。Agent 不再叠加整工具重试，按恢复条件处理。MCP 外层工具时限须覆盖多阶段请求与各自重试；细则见 [请求边界](openai-workflow-tools.md#配置与请求边界)。

以下工具通过 OpenAI Python SDK 调用固定的 `gpt-6-luna`，每次强制读取并显式使用 `OPENAI_API_KEY` 和 `OPENAI_BASE_URL`，不提供模型或配置覆盖参数。API 工具具有 `open_world_hint=true`、`idempotent_hint=false`；只读注解表示不修改本地或 GitHub 资源，不表示没有外部 API 请求。接口失败、未知分支、拒绝或未完成的生成不能当作成功结果。

所有 OpenAI 请求共用显式注入的 `httpx2.AsyncClient(trust_env=True)`，读取 MCP 进程的标准代理环境变量（`HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY`、`NO_PROXY` 及小写形式）。配置适用代理且未匹配 `NO_PROXY` 时通过代理；无代理配置时按库默认直连，代理失败不回退直连。Codex 启动时须转发所需变量名并重新加载服务，详见 [代理与环境传递](openai-workflow-tools.md#codex-stdio-环境传递与排查)。

| 工具 | 输入 | 返回 |
|---|---|---|
| `check_api_input` | 强类型 `request`，仅必填非空字符串 `purpose`、`content`；不接受目标工具名或仓库路径参数 | 默认允许联网审核，无需前置审核或逐次人工授权；自身仍先执行本地静态检测，再进行 Decisions 审核。不检查文件或目录路径，凭据、隐私及不透明载荷等审核继续。查看 `passed`、状态及安全修订提示。通过后允许当前任务所需项目内容向既定配置服务外发，无需重复确认；不扩大其他操作权限。实际出站仍强制复检，详见 [`API 输入审核`](api-input-review.md)。 |
| `decide_codex_session_action` | 强类型 `request`：历史读取状态、事实覆盖、保存限制和新增事实来源 | Decisions 的查询与持久化分支；不能用当前新事实更新历史摘要。 |
| `start_issue_pr_draft` / `revise_issue_pr_draft` | 首轮完整draft；修订携带会话ID、版本、唯一请求ID、反馈及显式证据变更 | 进程内有界修订，生成与独立审查；反馈不等于证据，重启失效。详见[多轮协议](openai-workflow-tools.md#issuepr-多轮修订草稿)。 |
| `get_issue_pr_draft` / `close_issue_pr_draft` | 草稿会话ID | 离线回读/释放进程状态，不发布或写Memory；运行中close拒绝。 |
| `generate_git_commit_message` | user_request、当前选定提交全部改动的evidence及可选重点/格式；不接受kind或模型覆盖 | 复用commit_message生成，返回candidate和完整message、adoptable与本地校验范围；须审阅并check_commit_message，不执行Git。详见[提交信息](check-commit-message.md)。 |
| `generate_skill_content` | 强类型 `request`：内容种类、用户目标/受众、分类型项目事实与来源、查询重点、格式、可选会话来源；Issue/PR 其他语言须 `language_override` 引用用户原文 | Responses 结构化候选；Issue/PR 生成后另做一次有界语义审查，须检查 `quality_status`/`adoptable` 与缺失项，`ok=true` 不等于可发布。不会自行读取仓库。 |

`check_branch_names`、`check_commit_message`、`audit_issue_pr_policy` 的公开参数保持不变：先执行原本地硬校验，通过后再调用 Decisions。API 结果不能放宽本地失败，API 不可用时不能默认为通过。其余精确计算、Git 写操作和 Hook 不迁移到模型。详细输入范式、Instruction Prompt、强度配置及错误边界见 [`openai-workflow-tools.md`](openai-workflow-tools.md)。

Pi 工具默认可能间接暴露：先用 `searchTools` / `describeTool` 核对名称和 Schema，完整服务指令用 `describeNamespace` 获取；未直接声明不等于工具缺失，不绕过 hidden。环境与时限见 [Pi stdio](openai-workflow-tools.md#pi-stdio-环境传递与工具时限)。

## Codex 会话事实辅助工具

这些工具可由 Pi 调用，但来源校验仍仅支持真实 Codex 链接，不接受 Pi 原生会话路径/ID。不要伪造 Codex 来源；本服务不提供 `read_thread` 或 Pi 历史读取器。缺少原文时只暂停依赖该历史的工作。问题/模板可跨宿主使用。

这三个工具均为只读，不访问 Codex 原始会话、不发起网络请求、不调用 Serena，也不保存摘要。前两个是纯输入处理，不需要 `repo_path`；第三个必须显式传入目标仓库/worktree 的绝对根路径。默认问题与模板随 Python 包发布，不依赖服务启动目录。

| 工具 | 输入 | 用途 |
|---|---|---|
| `get_codex_session_summary_guidance` | `custom_questions?`, `custom_template?` | 返回默认阅读清单和 Markdown 模板；自定义问题或模板替换对应默认内容，不强加默认章节。 |
| `order_codex_session_sources` | `sources` | 对来源去重并按创建时间倒序分组；缺时间、时间相等或同一会话元数据冲突时标明歧义，不推断优先级。 |
| `prepare_codex_session_memory` | `repo_path`, `source`, `summary`, `evidence_refs`, `topic?`, `persistence_allowed?`, `existing_memory_name?` | 校验项目、来源和安全名称，生成 Serena `write_memory` 的参数。用户禁止保存时跳过，不生成写入载荷。已有记录可保留原名。 |

`source`/`sources` 的必填字段为 `source_link`，可选字段为 `thread_id`、`created_at`、`ended_at`、`title`。这些数据由调用者从宿主会话读取结果提取。链接严格使用 `codex://threads/<小写标准UUID>`；时间使用带时区、包含秒且小数最多六位的 ISO 8601，缺少结束元数据时不推算结束时间。工具只检查调用者提供的数据，不证明这些元数据来自宿主，也不证明事实或证据引用真实。时间排序只用于已读取来源的事实优先级，不能据此宣布原会话没有相关事实或允许跳过原文查询。

排序工具返回 `priority_groups`、`missing_created_at`、`ambiguities` 和 `ready`；`ready=false` 表示需要澄清，不能把组内列表顺序当作优先级。同一会话的冲突元数据会报错。准备工具在允许保存时另要求非空 `title`、明确的 `created_at`、非空 `summary` 和 `evidence_refs`；成功返回 `status=prepared` 及 `payload={memory_name, content}`，禁止保存时返回 `status=skipped`、`payload=null`，项目路径校验失败时返回 `ok=false`、`error`、`payload=null`。

`summary` 是 Code Agent 按默认模板或用户指定结构撰写的完整 Markdown 文档。准备工具令 `payload.content` 与其精确一致，来源元数据单独放在响应的 `metadata`；其中 `memory_project_root` 只表示当前 Serena 的目标项目，不能当作原会话的 `project_scope`。Code Agent 必须逐项核对 `evidence_refs` 与原会话，确保未混入当前会话的新事实。默认 `topic` 为 `codex-sessions`，禁止绝对路径、路径穿越和 `global` 跨项目主题；主题每段最多 100 个 UTF-8 字节，已有条目的名称须为同主题下以相同 thread ID 结尾的安全名称，并计入 Serena 自动添加的 `.md` 长度。`persistence_allowed` 只是调用参数，不能替代用户指令或实际权限。

使用会话事实要求原文来源可追溯；准备摘要要求准确项目、去重及当前写入许可；保存成功以实际内容回读为准。这些是相应动作的数据条件，不规定统一调用路线。用户禁止持久化时仅只读参考；本工具不会绕过该限制。完整规约见 [`codex-session-facts.md`](codex-session-facts.md)。

## 检查与只读审计

| 工具 | 输入 | 用途 |
|---|---|---|
| `check_branch_names` | `branch_names?`, `repo_path?` | 校验一组分支名；不传 `branch_names` 时必须传 `repo_path`，检查当前分支。 |
| `check_commit_message` | `message` | 校验提交标题、中文说明和禁止的署名；纯文本操作。 |
| `check_staged_changes` | `repo_path` | 固定执行暂存区空白检查，不运行测试。 |
| `audit_repository_state` | `repo_path` | 读取 Git 根目录、分支、状态、remote 名称及 GitHub Fork/default branch；不输出 remote URL。 |
| `list_repository_worktrees` | `repo_path` | 读取 worktree 路径、HEAD 和分支。 |
| `audit_worktree_base_sync` | `repo_path`, `base_ref`, `remote?` | 本地快照审计 head/base OID、merge-base、ahead/behind 和阻塞状态；`remote=null` 默认不联网、发布状态 unknown，提供已配置 remote 名称时 live 查询同名需求分支的发布状态，不 fetch。 |
| `capture_untracked_file_manifest` | `repo_path` | 返回未忽略未跟踪普通文件的相对路径、SHA-256 和大小；不复制/保存；拒绝符号链接和特殊文件。 |
| `list_github_issue_labels` | `repo_path`, `repo?` | 读取仓库最多 100 个现有 Issue label。 |
| `audit_issue_pr_policy` | `repo_path`, `repo?`, `issue_number?`, `pr_number?`, `expected_base?`, `expected_head?` | 只读检查 Issue/PR 开放状态、PR base/head 和正文关联；至少提供 Issue 或 PR 编号。 |

## 本地 Git 操作

这些操作均要求 Skill 前置授权。切换、拉取、合并、rebase 和复制会先检查工作区状态或身份；冲突时保留现场并停止。

| 工具 | 输入 | 固定动作与边界 |
|---|---|---|
| `stage_repository_paths` | `repo_path`, `paths` | 按显式相对文件路径暂存；拒绝绝对路径、路径穿越、目录、符号链接、重复项和已有暂存内容；只允许经过 index 核验的已跟踪删除；暂存后复核路径集合完全一致。整文件操作，不支持 hunk。 |
| `commit_repository_changes` | `repo_path`, `message`, `expected_paths` | 要求暂存路径与预期集合精确一致，提交信息符合固定格式且 `git diff --cached --check` 通过；调用固定 `git commit -m`，不跳过 hooks，并回读提交 SHA、message、文件和状态。 |
| `switch_repository_branch` | `repo_path`, `branch_name` | 切换到已存在的本地分支；tracked dirt 时拒绝。 |
| `create_repository_branch` | `repo_path`, `branch_name`, `expected_head_oid?` | 从当前 HEAD 原地创建并切换新分支，支持 detached/普通分支及已有修改；以旧 OID 条件的 Git 引用事务保护，不创建其他 checkout。详细约束见下节。 |
| `pull_origin_branch_fast_forward` | `repo_path`, `branch_name` | 当前同名分支执行 `origin` 快进拉取；tracked changes 时拒绝。 |
| `fetch_upstream_branch` | `repo_path`, `branch_name` | 获取 `upstream` 的指定分支；要求 remote 已存在，不合并/推送。 |
| `fetch_repository_branch` | `repo_path`, `remote`, `branch_name` | 获取已配置 remote 的指定分支对象与 FETCH_HEAD，校验不回退后按旧 OID 条件更新明确的 remote-tracking ref；不切换 checkout、不修改本地 base 分支、不合并/推送。采用成功回读的 `fetch_ref`、`fetched_oid` 和 `fetched_at`；失败也可能已获取对象/写入 FETCH_HEAD。 |
| `merge_upstream_branch_fast_forward` | `repo_path`, `branch_name` | 将已获取的 `upstream` 同名分支快进合入当前同名分支；要求工作区干净。 |
| `rebase_repository_branch` | `repo_path`, `branch_name`, `base_branch`, `expected_head_oid?`, `expected_base_oid?`, `old_base_oid?`, `remote?` | 当前干净需求分支 rebase 到核验的本地 base 引用或完整提交 OID；live 核验 remote 上同名分支未发布，已发布或未知时拒绝。可指定旧边界仅重放后续提交；冲突保留现场，不自动恢复。 |
| `merge_repository_branch` | `repo_path`, `branch_name`, `base_ref`, `expected_head_oid`, `expected_base_oid`, `remote?` | 在准确需求 checkout 快进或普通 merge，保留已发布提交；要求显式预期 head/base OID，核对发布状态与远端 tip。冲突保留现场，不自动 rebase 或推送。 |
| `continue_repository_merge` | `repo_path`, `operation_id`, `expected_current_head_oid`, `expected_state_fingerprint` | 核对本服务管理的merge记录及最新快照，要求已解决并正确暂存，再执行一次原生continue；不自动暂存或解决冲突。 |
| `continue_repository_rebase` | 同上 | 核对受管理的简单rebase及最新快照，重新live核实记录中的remote同名分支未发布，再执行一次continue；可能停在下一冲突，不自动循环或skip。 |
| `abort_repository_merge` | 上述四项及必填 `confirm_discard_resolution_work` | 明确授权撤销并确认丢弃本次解决内容后，离线执行一次原生merge abort；核对恢复原分支/head，不清理无关文件。 |
| `abort_repository_rebase` | 同上 | 同样核对受管理rebase及丢弃范围，离线执行原生rebase abort；不以reset、stash或手工元数据改写作为后备。 |
| `create_repository_worktree` | `repo_path`, `target_worktree_path`, `branch_name`, `base_branch` | 在不存在的绝对目标路径创建新分支/worktree；要求起点存在、分支合规且未被检出。 |
| `remove_repository_worktree` | `repo_path`, `target_worktree_path`, `branch_name` | 按精确路径和分支身份移除干净 worktree；不删除本地分支或远端分支，不强制清理。 |
| `copy_untracked_files_to_worktree` | `repo_path`, `target_worktree_path`, `manifest` | 从清单按相对路径复制到同仓库 worktree；复制前复核大小、指纹和未跟踪状态，拒绝覆盖/路径穿越/symlink。失败时可能已有部分文件复制，按返回清单检查。 |
| `configure_project_hooks_path` | `repo_path` | 要求 `.githooks/pre-commit` 和 `commit-msg` 已存在，且配置未指向其他路径；设置仓库本地 `core.hooksPath`。不复制 Hook 资产。 |

### 已有 worktree 的基线同步工具

动作条件和策略见 [`worktree-base-sync.md`](worktree-base-sync.md)：同步要求准确实际 base、有效来源、当前发布状态及匹配 OID；已发布 merge、未发布 rebase，变更后的验证绑定新状态。所有这些工具均不调用 OpenAI、不读会话、不写 Memory；fetch/merge/rebase 不包含 GitHub 推送或 PR base 更新。

- `base_ref` / rebase 的 `base_branch`：明确的本地分支、完整 `refs/heads/...`、`refs/remotes/...` 或完整提交 OID；不接受任意 revision 表达式或命令。使用刚获取的 `fetch_ref` 时同时传 `fetched_oid` 作为预期 base OID。直接使用 OID固定提交时，另行核对其来源引用是否已变化。
- `remote`：已有配置的 remote 名称，不是 URL；审计默认 `null`，表示不联网而非“未发布”。rebase 的默认值为 `origin`；缺少配置、网络失败或结果未知时停止，不提供本地模式豁免。实际 live 查询仅核验该 remote 的同名分支；其他已知 PR、协作者和下游依赖仍由调用方核对。不要将 `null`、空字符串与省略混用。
- `expected_head_oid` / `expected_base_oid`：完整 40/64 位十六进制提交 OID，merge 必填；rebase 可省略或 `null` 以兼容旧调用，但依赖先前审计的同步动作必须提供刚核验的值。可选参数省略时使用调用时捕获的状态，不能据此声称比较过先前审计。写入前状态改变须重新审计。
- `old_base_oid`：rebase 可省略或 `null`；提供时为已核验的旧父分支边界完整 OID，要求属于当前 head 的祖先，用于 `--onto`。工具校验祖先关系，不判断提交的业务归属或证明父 PR 已 squash 集成。
- 审计关系状态为 `up_to_date`（head 包含 base）、`fast_forwardable`（head 落后且可快进）、`diverged`（双方各有独有提交）；`blocked` 表示状态不允许同步，`unknown` 表示所需事实无法确认。`ahead_by` / `behind_by` 相对于所给 base，不能当作相对于远端需求分支的计数。发布状态与提交图关系分别核对。
- `ok=true` 仅表示对应工具的观测或动作及回读满足条件。snapshot/fetch 时间和 OID 不是远端永不变化的保证。失败先检查 `error_code`、冲突路径和 `needs_review`；已执行但回读失败不能当作未发生写入，不盲目重试。成功也不代表项目测试通过。
- fetch 不依赖“没有 `+` 就不会回退”的假设：下载和最终 remote-tracking 引用更新分别核验。旧目标为符号引用、回退/分叉或条件更新时 OID 已改变均停止；下载阶段的对象和 FETCH_HEAD 副作用不自动回滚，也不代表最终目标引用已成功更新。
- 写工具使用共同 Git 目录下的协作锁并在动作前复核状态；这不锁定所有外部 Git 进程或普通文件编辑。默认不更新其他分支，不隐式 stash；正常 hooks 继续执行。受限continue/abort需按下节单独决定和调用，不自动恢复，不封装自动冲突解决或强推。
- 新同步工具的远端 Git 子进程禁止终端凭据提示，超时为 120 秒；超时返回安全错误而非原始远端异常。fetch 超时也可能留下下载对象或 FETCH_HEAD 变化，先回读，不自动重试整个工具。

参数与数据依赖示例（合成数据；按实际所需动作选用，不是固定队列）：

```json
{"repo_path":"/workspace/topic","remote":"origin","branch_name":"main"}
```

以上传给 `fetch_repository_branch`。采用返回的 `fetch_ref` 后审计：

```json
{"repo_path":"/workspace/topic","base_ref":"refs/remotes/origin/main","remote":"origin"}
```

已发布分支将审计得到的完整 `head_oid`、`base_oid` 分别传入 `merge_repository_branch` 的两个必填预期 OID；未发布分支将同样值传入 rebase，且将 `base_ref` 放入兼容参数 `base_branch`。不要复制示例路径或编造 OID。

### 受管理操作的 continue/abort

恢复前置条件见 [`worktree-recovery.md`](worktree-recovery.md)。服务在开始 merge/rebase 前建立当前 worktree Git 目录专属记录；冲突或结果不确定时保留。恢复前用固定 `base_oid` 作为 `base_ref` 调用审计，省略 `remote` 或传 `null`，读取 `recovery_context` 和 `current_state_fingerprint`。未完成操作使顶层同步 `status=blocked`；应单独核对恢复状态，不能要求它先变成 `up_to_date`。无记录、损坏、跨 worktree、未知复杂操作或原生状态不一致时不自动接管；任何恢复上下文本身都不提供写入授权。

- 四个工具的 `repo_path` 都是准确 checkout 绝对根目录；`operation_id` 取最新 `recovery_context.operation_id`，不是自定义名称。`expected_current_head_oid` 取同一上下文的 `current_head_oid`，为当前完整 40/64 位提交 OID；rebase 中途可能是临时 detached HEAD，不能用 `original_head_oid` 代替。
- `expected_state_fingerprint` 是重新审计得到的当前状态指纹，覆盖恢复记录、原生Git操作状态、index和相关工作目录内容；修改文件、暂存或操作状态变化后重新审计。指纹不是密码、全局锁或业务正确性证明，不能在其他checkout或其他操作上复用。
- 操作 ID 为记录生成的规范 UUID，状态指纹为 64 位小写十六进制 SHA-256；不要自行生成或缩短。恢复校验有界：记录 256 KiB、单个原生元数据 1 MiB、index 16 MiB、单个工作文件 8 MiB、工作文件合计 32 MiB、4096 路径、20000 待重放提交；超限或无法安全读取不视为通过。
- `confirm_discard_resolution_work` 是两个abort工具必填的布尔值，必须明确为 `true`。`false`、`null`、省略均不表示同意丢弃；工具参数不能替代用户对撤销和丢弃范围的实际授权。abort可能丢弃本次操作的已暂存及未暂存解决内容，不能用于只读探测。
- continue只接受已解决并暂存、无未合并index和未暂存解决内容的受支持状态；不stage、不编辑、不skip、不接收任意Git参数或编辑器命令。rebase continue仅查询记录中的remote，不允许调用时改换查询对象；发布未知、联网失败或已发布均停止。abort不联网，远端不可用不妨碍满足本地条件的撤销。
- `recovery_context.status` 为 `managed_in_progress` 时才有可核验的恢复目标；`none` 表示没有目标，`unmanaged` 表示原生操作不受本服务管理，`needs_review` 表示记录或原生状态无法安全匹配。查看 `ok`、`action_started`、`completed`、`aborted`、`still_in_progress`、`needs_review`、冲突路径及更新后的上下文。一次 rebase continue 可能停在下一冲突，必须重新审阅和决定；动作开始或创建了提交不表示最终回读通过，Git 回读通过也不代表项目测试或推送完成。失败或结果不确定先只读回读，不自动重试或补偿。
- 所有恢复调用均写当前checkout/index/ref，continue可能创建提交，abort具有丢弃解决内容的破坏性，均需明确用户授权及宿主写入审批。恢复记录的创建/保留/清理由本地代码负责，不调用OpenAI、Session或Memory。正常hooks继续执行；continue-rebase会联网，其余恢复入口离线。支持边界以实际Schema、描述和安全错误为准。

`abort_repository_merge` 的参数形状（全部为合成数据，不可代替实际审计值或用户丢弃授权）：

```json
{"repo_path":"/workspace/topic","operation_id":"00000000-0000-4000-8000-000000000072","expected_current_head_oid":"0123456789012345678901234567890123456789","expected_state_fingerprint":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","confirm_discard_resolution_work":true}
```

另一个 abort 工具使用相同参数；两个 continue 工具不接受丢弃确认参数，调用前必须完成相应的冲突解决与暂存，再重新审计。工具不提供恢复记录的自动接管、重建或跳过检查入口。

### 原地创建工作分支

先调用 `audit_repository_state` 核对准确 checkout、HEAD 状态和仓库范围；在用户已授权原地创建工作分支且适用的宿主写入审批放行后调用（Pi 见上文兼容边界） `create_repository_branch`。与切换已有分支、新建 worktree 分开选择，不把此工具当作同步默认分支或 Fork 初始化工具。

- `repo_path`：当前 checkout 的绝对 Git 根路径，必填；不接受子目录或相邻 worktree 代替目标。
- `branch_name`：必填的新本地工作分支名，须符合项目规则及 Git 引用语法，不得已存在，不新建 `main`/`master`。没有强制覆盖、任意 base 或其他 checkout 路径参数。
- `expected_head_oid`：可省略或传 `null`，表示使用本次调用捕获的当前 HEAD；提供时须是完整的 40/64 位十六进制 OID，并与当前 HEAD 一致。空字符串不是 `null`。无论是否提供，写入事务都会校验捕获的旧 OID；HEAD 改指向同 OID 的另一分支不属于 OID 冲突。该条件不保证 HEAD 符号目标身份、ABA 检测或阻止外部进程编辑普通文件。

工具保留 tracked、untracked 和 index 内容，仅通过引用事务创建新分支、更新 HEAD 与正常 reflog；原有分支保持原来的直接引用，不改为跟随新分支的符号引用。事务在更新 HEAD 前明确使用 `option no-deref`，不能仅凭原分支解析出的 OID 相同就判断原引用未变。工具不执行 checkout、stage、commit、push、同步、stash、自动提权或自动回滚。它离线执行本地校验，不调用 OpenAI、GitHub 或 Memory，并显式禁止 lazy fetch；partial clone 缺少必要对象时失败，不隐式从远端补齐。Git 必须支持全局 `--no-lazy-fetch` 选项，以及所需的 `update-ref --stdin` 事务、`option no-deref` 和 `symref-update ... oid` 语法；不支持时停止，不移除保护选项或降级到分步修改。存在有效的 `reference-transaction` Hook 时保守拒绝，以免执行任意额外副作用；不关闭或绕过 Hook。

拒绝锁定 worktree、未完成 merge/rebase 等 Git 操作、冲突 index、引用锁或权限失败等不安全状态。会将 Git 重定向到其他仓库、index、对象目录或 namespace 的环境覆盖也会拒绝。只有 `ok=true` 才可采纳为成功；`created` 的含义如下：

| `ok` / `created` | 含义与下一步 |
|---|---|
| `true` / `true` | 事务成功，且回读确认 HEAD 指向新分支、两者 OID 等于 `start_head_oid`。 |
| `false` / `false` | 在写入前拒绝；查看 `error_code` 和安全错误说明 `error`，处理前置问题。 |
| `false` / `true` | 事务成功，但后续回读未能确认最终状态；不是成功结果，不要再次创建。 |
| `false` / `null` | 写入阶段失败且无法确定最终副作用；先只读核对现场，不得断言分支没有创建。 |

`needs_review=true` 表示需要核对现场，`repo_path`、`branch_name` 和 `start_head_oid` 提供目标与基点信息。失败后保留现场，不因创建状态不明而盲目重试，也不删除分支补偿。引用事务的语法与锁语义依据 [Git update-ref 官方文档](https://git-scm.com/docs/git-update-ref)；不将引用事务描述为普通文件编辑的全局锁。

最小调用示例（合成路径）：

```json
{"repo_path":"/workspace/repo","branch_name":"agent/retain-local-work","expected_head_oid":null}
```

## GitHub 写操作

仅当用户意图已授权对应动作时调用。创建 Issue/PR 时传完整正文；工具以临时 body-file 调用 `gh`，创建后回读。推送不会强推；合并会关闭 PR。

| 工具 | 输入 | 前置条件 |
|---|---|---|
| `create_github_issue` | `repo_path`, `repo`, `title`, `body`, `labels` | label 必须是仓库已有且至少一个表达工作类型；创建后核验状态、labels 和本人 assignee。 |
| `push_issue_branch_to_origin` | `repo_path`, `repo`, `branch_name`, `issue_number` | 当前干净工作区位于对应非主分支；Issue 开放、有 label 且指派给当前账号；只推同名分支到 `origin`。 |
| `create_github_pull_request` | `repo_path`, `repo`, `title`, `body`, `base_branch`, `head_branch`, `issue_number` | Issue 开放、head 存在且正文含 `Closes/Fixes/Resolves #N`；创建后核验，默认指派本人并保持开放。 |
| `merge_github_pull_request` | `repo_path`, `repo`, `pr_number`, `merge_method` | PR 开放、可合并、required checks 全通过且无 changes-requested；`main` base 只允许 squash。不使用 admin/auto/delete-branch。成功执行合并后返回合并前 head OID `pre_merge_head_oid`，可供后续授权的本地清理工具核验。 |
| `push_fork_main_fast_forward` | `repo_path`, `repo` | 必须确认为 Fork，当前在干净 `main`，`upstream/main` 是 `main` 祖先；只快进推送 `origin/main`。 |
| `cleanup_merged_pr_local_branch` | `repo_path`, `pr_number`, `repo?`, `branch_name?`, `merged_head_oid?` | PR 已合并且工作区干净；切到实际 base 并快进同步，再删除本地 head。默认 `-d`；只有合并前 OID 精确匹配时才允许 `-D`。不删除远端或 worktree。 |

## 明确未封装的操作

当前没有首次添加 `upstream` remote、完整初始化个人维护基线与 tracking、GitHub branch protection/rulesets、复制 Hook 资产、空远端 bootstrap、跨 worktree 恢复未跟踪文件、部分 hunk 暂存、revert，或检查/升级本地 Serena uv 工具的 MCP 工具。原地创建当前 HEAD 的分支不补齐这些初始化操作。上述能力缺口按 [`cli-fallback.md`](cli-fallback.md) 自行使用相关 CLI 补足，包括既有授权内的写操作，无须仅因缺工具再次索取授权。工具的安全拒绝和执行失败不属于能力缺口；换入口不省略门禁、审批或结果回读，也不增加 MCP 参数或执行能力。

同样不封装代码编辑、项目自定义测试、任意脚本和需要产品/架构判断的冲突解决。
