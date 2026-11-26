# OpenAI 辅助判断与内容生成

Python MCP Server 通过 OpenAI Python SDK 执行规约分支判断和内容生成。Code Agent 提交范围明确的事实、问题和格式要求，工具返回枚举判断或有来源的候选内容，Code Agent 核对后优化或采纳。API 结果不构成 Git、Memory 或其他外部操作的授权，也不证明未运行的测试通过。

## 配置与请求边界

- Decisions、Responses 和输入安全审核的每次 API 请求统一显式使用 `OPENAI_TIMEOUT_SECONDS = 180.0`（3 分钟）。`OPENAI_TIMEOUT_MAX_RETRIES` 为可选环境变量，配置非负十进制整数重试次数：未设置默认 `5`，`0` 关闭；空字符串、负数或其他非法值在任何请求前返回 `invalid_timeout_max_retries`，不静默回退。该变量不改变模型、凭据、地址或代理配置，不接受工具参数覆盖。
- 仅 SDK `APITimeoutError` 触发调用处重试，默认首次加 5 次重试，最多 6 次。每次超时后立即串行重发同一受检请求，每次新建客户端并重新读取当前凭据、端点及代理，最后关闭客户端；每个独立请求读取当前重试配置，SDK 的 `max_retries=0` 避免重试叠加。输入审核和业务请求各有预算，不在外层重新运行整条工作流。认证、权限、连接错误、HTTP 错误、拒绝和无效结果不自动重试；预算耗尽返回安全 `api_timeout`。Agent 收到该失败时不再自动叠加整工具重试，按恢复条件处理。
- 超时请求可能已经到达服务端，重试可能产生重复 API 用量。180 秒为底层请求超时配置，不能当作整工具总时限：普通生成有审核和生成两个阶段，Issue/PR 还有审核和质量审查，共四个阶段；默认每阶段最多 6 次请求。MCP 客户端的调用时限（Codex `tool_timeout_sec`，Pi `timeout`，单位秒）须覆盖所需阶段和重试预算，具体还受网络各阶段超时语义影响，不能保证固定墙钟上限。本次不自动覆盖已有客户端时限。
- 每次实际请求均从本地环境读取 `OPENAI_API_KEY` 和 `OPENAI_BASE_URL`，两者都必须非空，并显式传给 SDK。缺少任意一项即停止请求，不使用 SDK 的默认凭据或地址，不从工具参数、其他变量或配置文件补齐。
- 所有 Decisions 和 Responses 请求共用 `httpx2.AsyncClient(trust_env=True)`，每次调用新建并显式传入 SDK，结束后释放；SDK 初始化失败也关闭已创建的 HTTP 客户端。代理从服务进程的 `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY`、`NO_PROXY`（含小写形式）读取，选择及绕过规则遵循 httpx2；不接受工具参数覆盖代理。未配置代理时按库默认直连，目标匹配 `NO_PROXY` 时绕过代理；代理配置或连接失败不会回退直连。
- 代码、文档和日志不得包含真实凭据或端点值。错误只返回安全分类，不输出原始异常、请求头、响应正文或环境变量值。工具不能让调用者覆盖模型、凭据或端点。
- 业务判断及出站审核通过 `client.decisions.create` 固定使用 `gpt-6-luna`。候选生成和质量审查通过 `client.responses.parse` 固定使用 `gpt-6.2-sol`，公开网络搜索通过 `client.responses.create` 及内置 `web_search` 使用同一 Responses 模型。请求失败时禁止回退到其他模型或接口。搜索的自适应强度与引用协议见 [公开网络搜索](web-search.md)。
- Decisions 当前没有推理强度参数，判断使用 Decisions 自身机制，不发送不支持的 `reasoning` 参数；生成显式指定强度：提交信息为 `low`，计划和历史会话摘要为 `high`，其余为 `medium`，默认值为 `medium`。
- 生成请求设置 `store=False`，不附加模型可执行的工具。API 不读本地仓库、原始 Codex 会话或 Serena；证据必须由调用者显式提供。输入超出预算时拒绝，不静默截断；普通测试不联网。

接口依据：[Decisions](https://developers.openai.com/api/docs/guides/decisions)、[创建判断](https://developers.openai.com/api/reference/resources/decisions/methods/create)、[结构化输出](https://developers.openai.com/api/docs/guides/structured-outputs)、[GPT-6 Luna](https://developers.openai.com/api/docs/models/gpt-6-luna)。

### 项目数据使用与发送前审核

`check_api_input` 按 [API 输入审核](api-input-review.md) 的默认许可先本地检查，再联网审核。业务 Decisions、生成和质量审查均有自己的最终出站门禁，仅在实际发送的内容快照通过后继续。离线测试分别模拟审核与业务请求。

### Codex stdio 环境传递与排查

安装为 uv tool 后，服务仍只读取自身进程的环境变量。Codex 启动环境须持有非空的 `OPENAI_API_KEY`、`OPENAI_BASE_URL`，并在 `[mcp_servers.dev-workflow-standards-tools]` 的 `env_vars` 中转发这两个名称及所需标准代理变量。自定义重试次数时，也转发 `OPENAI_TIMEOUT_MAX_RETRIES`。源码 `dws` 会合并这些名称。终端中手动运行成功只验证了该次进程的配置。脚本入口见 [安装说明](installation.md#mcp-与源码辅助脚本)，字段语义见 [Codex MCP 官方说明](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)。

需要用源码辅助脚本修复已有注册时，在源码仓库根目录运行 `./dws --env-only`；可添加 `--dry-run` 只检查不写入，或用 `--server NAME`、`--config PATH` 指定目标。无参数执行入口仅打印使用帮助；安装或更新 MCP 须显式使用 `--mcp-install` 或 `--mcp-update`。`--env-only` 只合并变量名，保留其他配置，不读取凭据或代理值，也不发起 API 请求。它不会替调用进程加载凭据、配置代理服务、启用额外授权或修改 MCP 的请求配置规则。

更改配置后须重新加载 MCP 服务，必要时退出后重开客户端以重新创建进程。`env_vars` 不会读取 Shell 配置文件或 `.env` 文件，也不会让已运行的子进程自动获得新变量；本服务不增加凭据文件、其他变量或默认地址回退。

`missing_api_key` 和 `missing_base_url` 都是在创建 SDK 客户端、发送请求之前返回的本地配置错误。服务先检查 Key，再检查 Base URL；两项都缺失或为空时，先返回 `missing_api_key`，不代表 Base URL 已通过检查。排查仅记录进程或配置位置及变量是否存在、是否非空，不输出真实值；配置修复后再用最小必要事实验证请求。

代理配置无效或客户端初始化失败返回 `client_initialization_failed`；请求超时返回 `api_timeout`，代理/网络连接失败通常返回 `api_connection_failed`，代理返回的 HTTP 错误可表现为 `api_status_error`。这些分类不包含原始异常或代理认证信息；排查时核对代理可用性、变量是否传入，以及目标是否被 `NO_PROXY` 排除，不以错误触发直连重试。

### Pi stdio 环境传递与工具时限

Pi 原生 MCP 使用用户级 `~/.pi/agent/mcp.json` 或已信任项目的 `.pi/mcp.json`，不是 Codex TOML 配置。stdio 继承启动 Pi 的进程环境；启动时须持有非空 `OPENAI_API_KEY`、`OPENAI_BASE_URL` 和所需代理变量。无需照搬 `env_vars`，也不要写入真实配置值。本服务仍只读自身进程环境，不加载凭据文件或回退。仅检查变量存在性/非空状态。

Pi 的服务级 `timeout` 单位为秒，默认 60，不能覆盖单次最长 180 秒及多阶段重试预算；按当前调用阶段与重试配置审阅并设置足够时限，不保证固定墙钟上限，不自动修改用户配置。超时不能当作服务零请求或无副作用，不自动重跑整工具。修改服务配置后 `/reload` 或重新连接；启动环境改变时必要时退出并重启 Pi。替代原生 MCP 的扩展按其实际配置处理，不强套原生配置。

注册说明见 [安装说明](installation.md#pi-code-agent-使用范围)。

## 判断工具与硬校验

| 工具 | 输入重点 | 判断结果及使用方式 |
|---|---|---|
| `check_branch_names` | 维持原来的 `branch_names` / `repo_path` | 本地名称规则先检查；通过后才请求 Decisions。模型不能把本地失败改为通过。 |
| `check_commit_message` | 维持原来的 `message` | 本地检查类型、中文说明及禁止署名；通过后再请求 Decisions，API 异常不能返回通过。 |
| `audit_issue_pr_policy` | 维持原来的仓库、Issue/PR 编号和预期 base/head | 先通过既有只读审计，再提交精简规则事实判断；不发送整份 PR 内容，不创建或修改 GitHub 资源。 |
| `decide_codex_session_action` | `request`：来源可访问性、读取覆盖、事实是否存在、保存限制和新增事实来源 | 分别返回查询动作和持久化动作；原文不可读不能当作无事实，当前新事实不能写入历史摘要，禁止保存时不能生成保存分支。 |

原检查工具保留本地检查结果，并补充 API 判断信息。本地失败无需发送 API；API 拒绝、超时、错误、返回未知选项或缺少答案时均不能通过。判断返回固定枚举，不使用自由文本猜测分支，也不把置信度当作授权或验证证据。

路径、精确名称和格式规则、创建时间排序、Git 写操作前置条件仍由本地代码执行。`get_codex_session_summary_guidance`、`order_codex_session_sources` 和 `prepare_codex_session_memory` 继续作为不联网的确定性助手；固定 Git 写工具及 Hook 不会因为模型的肯定结果而跳过自身检查。

### 会话事实输入

`decide_codex_session_action` 的 `request` 包含 `user_request`、`has_relevant_sources`、`history_accessible`、`history_fully_read`、`relevant_facts_found`、`persistence_allowed`、`existing_summary`、`new_fact_origin`。`relevant_facts_found` 未知时传 `null`，不能把未读或无法访问写成 `false`；`new_fact_origin` 使用 `original_session`、`current_session` 或 `none`。

Code Agent 必须从真实读取结果填写这些条件。工具只判断提供的数据，不核验宿主会话或重放历史操作。完整事实边界见 [`codex-session-facts.md`](codex-session-facts.md)。

## 生成工具输入

`generate_skill_content` 接收 `request`，默认按以下字段组织内容：

| 字段 | 要求 |
|---|---|
| `kind` | `issue`、`pr`、`commit_message`、`plan`、`handoff` 或 `session_summary`。 |
| `user_request` | 当前要生成的内容、受众和约束；不要混入凭据或无关日志。 |
| `evidence` | 有界证据列表，每项包含唯一 `reference_id`、非空 `content`、`origin` 和可选 `source_thread_id`。 |
| `focus_questions` | 用户明确要求查询或总结的问题；优先于默认问题清单。 |
| `output_format` | 用户明确要求的输出结构或模板；优先于默认章节。Issue/PR 的英文模板不构成语言覆盖。 |
| `language_override` | 仅 Issue/PR 可用。省略/null 默认中文；其他语言须提供 `{language, instruction_ref}`，后者引用本次 evidence 中 `origin=user_provided` 的用户语言指令原文。本地检查引用来源，模型核对其是否确为用户的明确语言要求；其他 kind 禁止此字段。 |
| `source` | 历史会话摘要必须提供相应的 `CodexSessionSource` 元数据；其他类型可省略。 |

`origin` 为 `provided_session`、`current_observation` 或 `user_provided`。历史摘要只接收 `provided_session` 证据，且每项 `source_thread_id` 必须与 `source` 相同；禁止将当前观察或其他会话的事实混入历史摘要。普通开发文案可以使用当前观察，但必须如实区分已验证、未验证和待决定事项。

```json
{
  "request": {
    "kind": "issue",
    "user_request": "根据证据编写中文功能 Issue，不编造验证结果",
    "evidence": [
      {
        "reference_id": "E1",
        "content": "需求是提供带来源引用的会话摘要候选内容；实际保存继续使用 Serena。",
        "origin": "user_provided",
        "source_thread_id": null
      }
    ],
    "focus_questions": ["功能边界是什么？", "如何验收？"],
    "output_format": "按需求、范围、验收标准三个中文章节输出正文",
    "source": null
  }
}
```

### Issue/PR 的事实准备

调用前收集相关的最小充分材料，无需先写整篇正文，不传整个仓库、完整会话或敏感配置。通用事实包括目标、受众、背景、组件、路径/符号指针、范围与非目标、约束及关联项；标注来源，区分已核实事实、未验证反馈、推测和建议，缺失或矛盾如实说明。

- Issue：区分缺陷与功能/变更请求。缺陷提供实际行为、期望行为和影响，环境/复现只填已有证据；需求提供目标能力和有依据的动机。建议的验收条件要标为建议。
- PR：提供具体前后行为、已完成改动与原因、真实 diff 摘要或文件证据、实际验证命令及结果、未运行项、已知兼容风险和关联 Issue。计划不能当成完成，验证未知不能当成通过。

交付已有改动时，按 [Issue/PR 文案的提交证据范围](github.md#issuepr-文案的提交证据范围) 核对全部待交付提交与最终净 diff，再提供可追溯的有界摘要。

Issue/PR 标题和自然语言正文默认中文。英文材料、模板和 Agent 自拟英文请求不构成语言授权；技术标识、路径、代码、命令、错误原文与必要引用保留。真实用户要求其他语言时，将原文放入 `user_provided` 证据并设置覆盖，例如：

```json
{"request":{"kind":"issue","user_request":"为维护者起草导出功能需求","evidence":[{"reference_id":"U1","origin":"user_provided","content":"请用英文编写这份 Issue。希望导出筛选结果，减少手动复制；范围仅报表组件。"}],"language_override":{"language":"English","instruction_ref":"U1"}}}
```

PR 最小合成示例（路径、编号和验证须替换为真实事实）：

```json
{"request":{"kind":"pr","user_request":"为评审者起草中文说明","evidence":[{"reference_id":"D1","origin":"current_observation","content":"已核实 base=main@1111111、head=2222222、merge-base=1111111；完整提交列表仅2222222，已读其patch，最终净diff一致。src/report.py 的 diff 将空输入从抛错改为返回空列表，避免空报表失败；范围仅此函数。执行 python -m unittest tests.test_report：通过。未运行集成测试；关联 #12；暂无已知兼容风险。"}]}}
```


## Git commit 信息生成

提交前需要起草时使用 `generate_git_commit_message`，由工具复用既有 `generate_skill_content(kind="commit_message")` 的 Responses.parse、指令、输出Schema、出站审核及本地格式/署名校验。推理强度沿用 `low`；不添加模型参数或新客户端。用户已指定完整 message 时保留原文，只执行检查。

Agent 准备本次选定提交全部 patch/hunk 的有界摘要、准确路径、前后行为、原因、实际验证和来源，不先生成整篇 message。已暂存时核对实际 cached diff；未暂存明确拟提交范围；分多个提交时分别提供各自范围，不能只给最后一次历史 commit 或整个 PR 改动。

```json
{"request":{"user_request":"概述本次空输入修复","evidence":[{"reference_id":"D1","origin":"current_observation","content":"拟提交范围仅src/report.py空输入分支：原抛错，现返回空列表；测试未运行。"}]}}
```

以上路径和事实为合成示例。输入不含kind/source/language_override；focus_questions/output_format可选，重点/结构优先默认但不覆盖固定规则。返回candidate、used_evidence_refs、missing_facts、review_notes及完整message；正文为空时message只有标题，否则标题后空行加正文。ok=true与validation_scope=local_format_and_attribution只说明本地引用/格式/署名通过，不代表语义或Git范围已校验。adoptable=false或缺口存在不可直接采用；Agent审阅后调用check_commit_message检查最终完整文本，暂存范围变更需重新核对生成依据。生成失败不默认为通过，不自动转手写绕过。

工具仅联网生成单次提交候选，不读取 Git 或文件，也不保存或发布候选。提交仍需用户授权及分支、暂存等适用检查。

## Issue/PR 多轮修订草稿

一次性生成继续使用 `generate_skill_content`；需要连续反馈时使用以下四工具，仍是 Responses API，不引入 Agents SDK 或远端会话。

1. `start_issue_pr_draft(request={request_id,draft})`：draft沿用生成请求，只允许issue/pr，给完整目标、来源及所有待交付commit patch证据。
2. `revise_issue_pr_draft(request={draft_session_id,expected_revision,request_id,feedback,evidence_changes,output_format})`：每次只生成并审查一个新候选。feedback为表达/重点要求，不是事实、用户语言授权或绕过规则的命令。evidence_changes的add必须新ID，replace/remove必须已有且三组不重叠。默认空操作；output_format省略/null保留，非空字符串替换。语言授权引用必须持续有效。
3. `get_issue_pr_draft(draft_session_id)`：离线回读最后完成候选和当前版本，result不包含最后失败尝试；status区分idle/in_progress。
4. `close_issue_pr_draft(draft_session_id)`：离线释放状态；运行中拒绝，不取消网络请求，不发布或删除Git资源。

最小合成首轮：

```json
{"request":{"request_id":"synthetic-start-0001","draft":{"kind":"issue","user_request":"起草导出需求","evidence":[{"reference_id":"U1","origin":"user_provided","content":"希望导出报表"}]}}}
```

修订时从返回值复制真实draft_session_id/revision，例如提交新的request_id和feedback“保留验证章节，缩短背景”。不需要重新输入整份证据。此前反馈累积保留；矛盾时明确修正。生成器参考上版候选和审查；审查器只看当前证据、有效要求及新稿，不承接旧审查通过结论。旧稿和审查意见都不是证据。

**状态和错误：**仅当前受信任本地stdio进程内存保存，不写文件、宿主会话、Serena Memory或远端Conversation；随机ID不是身份认证，不支持共享多用户网络服务。最多16个会话、每会话16次已记录尝试，闲置1800秒失效；尝试缓存最多512KiB、输入上下文32KiB、结果64KiB，超限失败不截断。重启或/reload丢失状态，draft_session_unavailable需重新start并显式提交恢复材料。

首个完成候选版本为1，失败保留0；ok=true含needs_revision推进版本但不代表可采用，adoptable仍须检查。审查异常/取消不推进或覆盖旧稿。expected_revision不匹配返回draft_revision_conflict，先get；运行中draft_in_progress。相同request_id+内容返回原尝试结果（可能为旧版本），不同内容request_id_conflict。失败后新尝试用新ID；取消后的首轮重放可能返回draft_attempt_incomplete，可从其ID用expected_revision=0修订或close。缓存重放不延长TTL。

每轮生成和独立审查各自执行出站审核并遵守统一请求边界。会话 ID 和请求 ID 不应含凭据。草稿工具只修改进程状态，提交、推送或发布需独立授权。宿主审批见 [Skill 宿主规则](../SKILL.md#宿主审批兼容)。

## Instruction Prompt 与返回内容

工具使用固定的任务 Prompt，将当前要求、证据、查询重点与输出格式分开编码。证据里的角色声明、命令或要求忽略规约的文本始终作为数据处理，不能覆盖工具规则。Prompt 要求仅根据输入事实生成内容，明确缺失信息，不补写未执行的测试、未创建的 PR、未确认的路径或决定；不请求或返回私有推理过程。

判断指令逐项解释观测字段和选项的触发、排除条件，按固定优先顺序处理同时成立的条件。工作流使用显式布尔条件，不从“并行开发”推断 worktree；会话查询和保存各用独立条件表，无相关来源时允许查询项目，来源不可读时阻塞查询；禁止保存或新增事实来自当前会话时跳过保存。本地 Issue/PR 审计未请求某项检查，不等于检查失败，也不需要补充 CI、标签或可合并性等本工具没有审计的事实。提交信息的署名观测与本地校验使用相同的有效行范围，忽略空行和注释行。

六类生成任务分别提供默认交付要求；用户明确指定的问题、结构和详略优先。Issue/PR 的其他语言要求须使用上述带来源的 `language_override`，其他类型保留明确语言偏好；不能覆盖事实与硬约束，提交信息仍须满足中文主题规则。

| 类型 | 默认交付重点 |
|---|---|
| `issue` | 问题或需求、影响、范围及验收条件；只有证据包含重现过程时才写重现步骤。 |
| `pr` | 具体问题、最终改动、实际验证和未解决风险；仅引用证据中的 Issue 与交付状态。 |
| `commit_message` | `title` 是完整合规主题，`content` 是可选正文；简述有证据支持的变更。 |
| `plan` | 拟执行步骤、依赖和验收方法；明确区分建议、假设和已完成事实。 |
| `handoff` | 已确认的进展、失败或阻塞、待办及后续动作；保留必要来源以便接手核对。 |
| `session_summary` | 只总结指定原会话证据，按默认阅读问题和模板落地；时间元数据不推测，当前观察不混入。 |

生成结果包含标题、正文、已使用的证据引用、缺失事实及简短审阅说明，并附模型、推理强度和可用的用量信息。返回的引用必须属于输入证据；拒绝、未完成、解析失败或未知引用不得当作成功内容。自定义格式决定正文结构，接口的结构化封装不强迫正文使用默认章节。

`used_evidence_refs` 只列实际支撑候选内容的输入引用，不能不加区分地列出所有证据；`missing_facts` 只列完成当前请求必要但未提供或有冲突的事实，不能为填满默认章节虚构缺口；`review_notes` 用于简短的事实边界和采纳前检查，不返回中间推理或整份输入。

Issue/PR 在本地硬校验后，另用 `Responses.parse` 和 `medium` 强度作有界语义审查。审查不自动修复候选，也不在拒绝或无效结果后重新生成。`quality_review` 的 `language_compliant`、`evidence_supported`、`coverage_sufficient` 分别判断语言授权、事实支撑、关键事实覆盖与冲突，不按字数、中文比例或默认章节数量判质量。`quality_review_usage` 单列审查用量，`usage` 为生成用量。

生成与审查的缺失事实和审阅提示合并去重。`ok=true` 仅代表有效草稿与有效审查，不保证适合发布；仅所有审查项为真且合并 `missing_facts` 为空时 `adoptable=true`、`quality_status=ready_for_agent_review`。其余返回 `adoptable=false`、`quality_status=needs_revision`，须修订或补证后重新审阅。审查异常返回 `ok=false`、安全 `error_code`、`adoptable=false`，不返回可采纳候选；超出发现项上限同样失败关闭。模型审查不证明实际事实正确，通过仍需人工核对且不授予写入权限。离线 mock 仅验证流程、规则和结构，不证明真实语言质量；真实生成验证须另行授权最小脱敏数据。

Code Agent 对照证据检查候选内容后，可修改或直接采纳。生成正文不自动写文件、Serena Memory、Issue 或 PR；需要持久化时继续使用对应的专用工具，并遵守当前用户授权。历史摘要通过 [`prepare_codex_session_memory`](mcp-tools.md) 准备写入参数，实际写入仍由 Serena 完成。

## 原生异步执行

API 工具（含草稿 start/revise）的服务函数均为 `async def`，MCP 原生等待最终结果；Python 直接调用方使用 `await`。无需先选路线或调用会话动作建议工具。同步的纯本地操作仍由 MCP 工作线程执行。

审核、业务判断/生成和二次质量审查按真实数据依赖等待；不同请求可并发。出站 JSON、Schema 及生成事实在首次等待前固定；同一请求超时重试复用受检内容，每次尝试仍重读当前配置并独立创建/关闭客户端。取消传播至请求，停止后续阶段与重试；清理在最长 5 秒的取消屏蔽区等待，异常只记录安全分类，不覆盖原请求取消。配置轮换后，任务上下文内的旧配置仍参与日志脱敏，任务结束释放，不保存凭据到文件。
