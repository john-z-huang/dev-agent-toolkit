# MCP 工具目录

Toolkit 服务的本地 STDIO 启动命令为 `dev-agent-toolkit-tools`。本目录所列 MCP 工具均通过本地 Client CLI 调用。仓库绑定工具须显式传入目标 checkout 的绝对 Git 根路径 `repo_path`。

## 通过本地 MCP Client 调用

1. 用 `registry list` 查找已配置的服务 ID，必要时用 `registry get <服务 ID>` 核对可执行文件、启动参数和工作目录。使用已确认的本地安装。用户指定独立注册表时，在子命令前传 `--registry`。缺少可信配置或安装时按 [项目 MCP 调用规则](../SKILL.md#项目-mcp-调用) 处理。
2. 已知工具短名时用 `request <服务 ID> tools/schema` 核对参数。需要查找工具或服务说明时，使用 `request <服务 ID> tools/list` 或 `server info <服务 ID>`。服务 ID 取自客户端注册表，工具短名取自该服务的工具清单。
3. 用 `call <服务 ID> <工具短名>` 调用。字符串参数用 `--arg NAME VALUE`，数组、布尔值和嵌套对象用 `--json`、`--stdin` 或 `--file` 传工具参数对象。读取 CLI 的 `result.structuredContent` 或工具提供的 `result.content`，同时核对工具的业务成功字段。

从核实的仓库根目录运行下列示例。示例假设注册表中的服务 ID 为 `dev-agent-toolkit-tools`。

```bash
/bin/bash -c 'exec dev_agent_toolkit_mcp_client_cli registry list'
/bin/bash -c 'exec dev_agent_toolkit_mcp_client_cli request dev-agent-toolkit-tools tools/schema --json "$1"' _ '{"name":"check_staged_changes"}'
/bin/bash -c 'exec dev_agent_toolkit_mcp_client_cli call dev-agent-toolkit-tools check_staged_changes --arg repo_path "$PWD"'
```

`call` 和 `request` 默认使用单次连接。项目切换、分页游标及多轮草稿依赖下游状态时，使用 `session open <服务 ID>`，后续调用传同一个 `--session <ID>`，完成后用 `session close <ID>` 回收连接。

工具注解标识只读、写入及破坏性。CLI 调用遵守宿主命令审批和沙箱，写操作还需对应用户授权。详见 [宿主审批兼容](../SKILL.md#宿主审批兼容)。GitHub 工具使用本机已授权的 `gh`。有能力缺口或调用失败时查阅 [CLI 补充边界](cli-fallback.md)。

## 提交草稿

从已核实的仓库根目录运行 Toolkit 专用的 `dev-agent-toolkit commit draft`，给草稿选择一个新的仓库外文件路径。Toolkit 调用已安装的 MCP Client CLI，向注册表中的服务只传 `repo_path`，并只保存可采用的候选。默认服务 ID 为 `dev-agent-toolkit-tools`，其他服务 ID 用 `--server` 指定。

```bash
/bin/bash -c 'exec dev-agent-toolkit commit draft "$1"' _ '/tmp/toolkit-commit-draft.json'
```

核对消息和实际暂存内容，完成项目检查并获得提交授权后，显式执行下一步。

```bash
/bin/bash -c 'exec dev-agent-toolkit commit apply "$1"' _ '/tmp/toolkit-commit-draft.json'
```

Toolkit 对同一个草稿执行分支、暂存区和提交信息检查，再通过 MCP Client 提交。快照比对涵盖分支、HEAD、暂存路径和暂存指纹。快照变更需重新生成并审阅。使用独立注册表时，两次命令均在 `commit` 后传同一个 `--registry`。按 [恢复 Hook](../hooks/recovery.md) 处理提交结果不明的情况。

## 正在运行的 MCP 构建信息

通过 CLI 调用 `get_mcp_server_build_info`，不传参数。返回处理请求的进程启动时读取的 `server_version`（包版本）和 `git_commit`（构建时源码 HEAD 的完整 Git hash）。无法取得相应记录时返回 `null`。从 sdist 重建 wheel 时沿用 sdist 记录的 hash。同一提交上的未提交改动不反映在 hash 中，同版本重装应结合发行包来源和实际工具 Schema 核对。详见 [调用已更新的本地 MCP](../hooks/updated-local-mcp.md)。

## OpenAI 判断与生成

联网 API 工具使用 `open_world_hint=true` 和 `idempotent_hint=false`。固定模型、环境配置、代理、重试及宿主时限见 [OpenAI 工具协议](openai-workflow-tools.md#配置与请求边界)。

| 工具 | 输入 | 返回 |
|---|---|---|
| `web_search` | `request` 含必填的公开 `query`、可选的域名白名单和回答语言 | 联网返回摘要、行内引用和来源，详见 [公开网络搜索](web-search.md)。 |
| `check_api_input` | `request` 只含必填的 `purpose` 和拟发送的完整 `content` | 先本地检查，再按默认许可联网审核。查看 `passed`、状态和安全修订提示。许可范围及实际出站复检见 [API 输入审核](api-input-review.md)。 |
| `decide_codex_session_action` | 强类型 `request`：历史读取状态、事实覆盖、保存限制和新增事实来源 | Decisions 的查询与持久化分支；不能用当前新事实更新历史摘要。 |
| `start_issue_pr_draft` / `revise_issue_pr_draft` | 首轮完整draft；修订携带会话ID、版本、唯一请求ID、反馈及显式证据变更 | 进程内有界修订，生成与独立审查；反馈不等于证据，重启失效。详见[多轮协议](openai-workflow-tools.md#issuepr-多轮修订草稿)。 |
| `get_issue_pr_draft` / `close_issue_pr_draft` | 草稿会话ID | 离线回读/释放进程状态，不发布或写Memory；运行中close拒绝。 |
| `generate_git_commit_message` | 先暂存本次改动，只传 `repo_path` | 读取暂存差异并返回候选、`adoptable`、路径和指纹。须审阅并调用 `check_commit_message`。详见[提交信息](check-commit-message.md)。 |
| `generate_skill_content` | 强类型 `request`，包含内容种类、用户目标/受众、分类型项目事实与来源，以及可选查询重点、格式和会话来源。Issue/PR/提交信息内置默认布局，自定义结构通过 `output_format` 提供。Issue/PR 其他语言须 `language_override` 引用用户原文。 | Responses 结构化候选；Issue/PR 生成后另做一次有界语义审查，须检查 `quality_status`/`adoptable` 与缺失项，`ok=true` 不等于可发布。不会自行读取仓库。 |

`check_branch_names`、`check_commit_message`、`audit_issue_pr_policy` 先做本地硬校验，通过后调用 Decisions。采纳条件见 [判断工具与硬校验](openai-workflow-tools.md#判断工具与硬校验)。

## Codex 会话事实辅助工具

三项助手均为离线只读，默认问题与模板随 Python 包发布。它们处理调用者提供的数据，不读取原会话或调用 Serena。Codex 来源与 Pi 适用范围见 [会话事实](codex-session-facts.md#宿主适用范围)。

| 工具 | 输入 | 用途 |
|---|---|---|
| `get_codex_session_summary_guidance` | `custom_questions?`, `custom_template?` | 返回默认阅读清单和 Markdown 模板；自定义问题或模板替换对应默认内容，不强加默认章节。 |
| `order_codex_session_sources` | `sources` | 对来源去重并按创建时间倒序分组；缺时间、时间相等或同一会话元数据冲突时标明歧义，不推断优先级。 |
| `prepare_codex_session_memory` | `repo_path`, `source`, `summary`, `evidence_refs`, `topic?`, `persistence_allowed?`, `existing_memory_name?` | 校验项目、来源和安全名称，生成 Serena `write_memory` 的参数。用户禁止保存时跳过，不生成写入载荷。已有记录可保留原名。 |

`source`/`sources` 的必填字段为 `source_link`，可选字段为 `thread_id`、`created_at`、`ended_at`、`title`。这些数据由调用者从宿主会话读取结果提取。链接严格使用 `codex://threads/<小写标准UUID>`；时间使用带时区、包含秒且小数最多六位的 ISO 8601，缺少结束元数据时不推算结束时间。工具只检查调用者提供的数据，不证明这些元数据来自宿主，也不证明事实或证据引用真实。时间排序只用于已读取来源的事实优先级，不能据此宣布原会话没有相关事实或允许跳过原文查询。

排序工具返回 `priority_groups`、`missing_created_at`、`ambiguities` 和 `ready`；`ready=false` 表示需要澄清，不能把组内列表顺序当作优先级。同一会话的冲突元数据会报错。准备工具在允许保存时另要求非空 `title`、明确的 `created_at`、非空 `summary` 和 `evidence_refs`；成功返回 `status=prepared` 及 `payload={memory_name, content}`，禁止保存时返回 `status=skipped`、`payload=null`，项目路径校验失败时返回 `ok=false`、`error`、`payload=null`。

`summary` 是 Code Agent 按默认模板或用户指定结构撰写的完整 Markdown 文档。准备工具令 `payload.content` 与其精确一致，来源元数据单独放在响应的 `metadata`；其中 `memory_project_root` 只表示当前 Serena 的目标项目，不能当作原会话的 `project_scope`。Code Agent 必须逐项核对 `evidence_refs` 与原会话，确保未混入当前会话的新事实。默认 `topic` 为 `codex-sessions`，禁止绝对路径、路径穿越和 `global` 跨项目主题；主题每段最多 100 个 UTF-8 字节，已有条目的名称须为同主题下以相同 thread ID 结尾的安全名称，并计入 Serena 自动添加的 `.md` 长度。`persistence_allowed` 只是调用参数，不能替代用户指令或实际权限。

摘要的原文核对、去重、保存与回读见 [Serena Memory 位置与创建](codex-session-facts.md#serena-memory-位置与创建)。

## 项目 Memory 只读工具

两个工具从 MCP 进程启动目录下的 `.serena/memories/` 读取本地 UTF-8 文件。先核实实际启动目录是目标项目根。名称支持子目录、可选 `mem:` 前缀和可选 `.md` 后缀。绝对路径、全局 Memory、越界路径及符号链接均会被拒绝。

| 工具 | 输入 | 用途 |
|---|---|---|
| `serena_memory_tail_read` | `memory_path`, `tail_lines` | 返回总行数、所读行号范围和尾部文本，保留 LF、CRLF 和 CR 行尾。 |
| `serena_memory_write_check` | `memory_path`, `changed_content`, `tail_lines` | 在相同范围内做区分大小写的字面匹配，返回 `success` 和匹配偏移。匹配只能证明该范围包含预期文本。 |

`tail_lines` 为 0–10000 的整数，0 返回空文本和总行数。所读尾部与 `changed_content` 各限 64000 字符。目录或文件缺失、不可读或超限时返回 `status=unavailable` 和 `reason_code`。两项均离线只读。保存到 Serena 时，通过 Client CLI 调用已授权的 Serena Memory 工具。

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

按 [基线同步策略](worktree-base-sync.md) 选择动作、核对发布状态和验证范围。同步工具不调用 OpenAI、不读会话、不写 Memory。推送及 PR base 更新是独立动作。

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

按 [受限恢复](worktree-recovery.md) 核对可恢复状态、最新审计快照和用户对继续或撤销的独立授权。审计返回的操作 ID 是规范 UUID，head OID 是完整的 40/64 位十六进制值，状态指纹是 64 位小写十六进制 SHA-256，覆盖恢复记录、Git 原生状态、index 和相关工作目录内容。三项都须使用同一次最新审计的原值。

恢复动作写当前 checkout、index 和引用，继续操作可能创建提交，撤销可能丢弃已暂存及未暂存的解决内容。rebase continue 仅联网查询记录中的 remote，其余恢复入口离线。恢复记录由本地代码管理，四个工具均不调用 OpenAI、不读会话、不写 Memory。

`abort_repository_merge` 的参数形状（全部为合成数据，不可代替实际审计值或用户丢弃授权）：

```json
{"repo_path":"/workspace/topic","operation_id":"00000000-0000-4000-8000-000000000072","expected_current_head_oid":"0123456789012345678901234567890123456789","expected_state_fingerprint":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","confirm_discard_resolution_work":true}
```

两个 abort 工具的参数相同；两个 continue 工具省略丢弃确认参数。

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

仅当用户意图已授权对应动作时调用。发布 Issue 或 PR 时，将[已校验并回读的两个定稿](github.md#正文草稿)的绝对路径传入 `title_file` 和 `body_file`。两者都是服务进程可读的 UTF-8 普通文件，可位于仓库外。标题文件只含一行非空标题，正文文件是非空的 `.md` 或 `.markdown`。工具读取已定稿内容，通过 `gh --title` 和 `--body-file` 提交并回读远端状态。文件校验失败时在联网前返回 `ok=false` 和 `created=false`，按 `error` 返回起草阶段修正。

| 工具 | 输入 | 前置条件 |
|---|---|---|
| `create_github_issue` | `repo_path`, `repo`, `title_file`, `body_file`, `labels` | label 必须是仓库已有且至少一个表达工作类型；创建后核验状态、labels 和本人 assignee。 |
| `push_issue_branch_to_origin` | `repo_path`, `repo`, `branch_name`, `issue_number` | 当前干净工作区位于对应非主分支；Issue 开放、有 label 且指派给当前账号；只推同名分支到 `origin`。 |
| `create_github_pull_request` | `repo_path`, `repo`, `title_file`, `body_file`, `base_branch`, `head_branch`, `issue_number` | Issue 开放、head 存在且正文文件含 `Closes/Fixes/Resolves #N`；创建后核验，默认指派本人并保持开放。 |
| `merge_github_pull_request` | `repo_path`, `repo`, `pr_number`, `merge_method` | PR 开放、可合并、required checks 全通过且无 changes-requested；`main` base 只允许 squash。不使用 admin/auto/delete-branch。成功执行合并后返回合并前 head OID `pre_merge_head_oid`，可供后续授权的本地清理工具核验。 |
| `push_fork_main_fast_forward` | `repo_path`, `repo` | 必须确认为 Fork，当前在干净 `main`，`upstream/main` 是 `main` 祖先；只快进推送 `origin/main`。 |
| `cleanup_merged_pr_local_branch` | `repo_path`, `pr_number`, `repo?`, `branch_name?`, `merged_head_oid?` | PR 已合并且工作区干净；切到实际 base 并快进同步，再删除本地 head。默认 `-d`；只有合并前 OID 精确匹配时才允许 `-D`。不删除远端或 worktree。 |

## 明确未封装的操作

首次添加 `upstream` remote、初始化维护基线与 tracking、GitHub branch protection/rulesets、复制 Hook 资产、空远端 bootstrap、跨 worktree 恢复未跟踪文件、部分 hunk 暂存、revert 及 Serena uv 工具的检查或升级，均按 [CLI 补充边界](cli-fallback.md) 处理。

同样不封装代码编辑、项目自定义测试、任意脚本和需要产品/架构判断的冲突解决。
