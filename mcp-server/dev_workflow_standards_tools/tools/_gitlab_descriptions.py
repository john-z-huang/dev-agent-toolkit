"""GitLab 工具的客户端可见合同与参数说明。"""

GITLAB_INSTRUCTIONS = """
Git 托管平台必须依据当前任务、已核实 remote 和项目事实选择，不能按域名中是否含 github/gitlab 猜测自托管平台。
GitHub 使用 gh 与原有 *_github_* / Issue-PR 工具；GitLab 使用 glab 与 GitLab / Issue-MR 工具。
GitLab repo 必填 host/group[/subgroup]/project（例 gitlab.example.com/team/sub/project），不含协议、凭据、.git 后缀；
host 不含端口（glab --hostname 不接受端口）；自定义 API 地址/端口使用预先核实的 glab api_host 配置。
显式 --hostname 绑定主机，完整项目路径 URL 编码后进入 API endpoint，不沿用 GitHub owner/repo 校验或猜默认主机。
Issue 的 #N 与 MR 的 !N 均为项目内 iid，不是全局 id；GitLab state=opened/merged、target_branch/source_branch 对应 PR 的 open/merged、base/head。
本地 Git、worktree、提交、授权、快进和非强推条件跨平台不变；纯 Git 动作不要求 gh/GitHub 登录。
GitLab 提供仓库审计、标签、Issue 创建、Issue 关联推送、MR 创建/合并、Issue-MR 审计、Fork main 推送与合并后本地清理。
GitLab 工具通过固定 glab api 联网，不接收任意命令/endpoint，不调用 OpenAI、不读取会话、不写 Memory或配置；
不收集/回显 GITLAB_TOKEN、OAUTH_TOKEN 或 CLI 原始错误。只读不是离线；写入仍须明确用户授权及实际宿主审批。
audit_issue_mr_policy 是确定性审计，不返回或冒充 GitHub audit_issue_pr_policy 的 OpenAI Decisions；passed 仅覆盖明确请求的本地规则与远端字段。
GitLab MR 正文生成可复用 generate_skill_content 的 kind=pr，事实中显式声明 GitLab/MR、实际 source/target 和 #Issue 关闭关联；输出须复核 GitLab 术语。
用户明确要求推送时，既有策略涵盖补齐缺失 Issue 和创建关联开放 MR，不涵盖合并、关闭或清理。
合并必须单独授权；pipeline、审批、冲突与保护必须满足，不以 GitHub required checks API 代替 GitLab 状态。
created=null 或 merged=null 且 write_attempted=true 表示写入结果不明；先回读实际资源，禁止自动重试。
GitLab 跨项目 Fork MR 的创建与本地清理未被这些封装覆盖；先核实 source/target 项目及分支拓扑，按能力缺口规则补足，不能绕过失败。
""".strip()

COMMON = (
    " repo_path 必须为目标 Git 仓库/worktree 绝对根目录；repo 必填 host/group[/subgroup]/project，"
    "支持自托管域名及多级 group，host 不含端口，不接受 URL、凭据或 .git 后缀；自定义 API 端口使用已核实的 glab api_host 配置。"
    "通过本机 glab api 显式主机和 HTTP 方法联网，使用 glab 已配置身份；不调用 OpenAI，"
    "不读会话、不写 Memory/配置，不回显凭据/remote URL/原始 CLI 错误。"
    "无任意命令或 endpoint 参数；读取失败、未知或格式错误均失败关闭。"
)
WRITE = (
    " 仅在用户明确授权当前动作、目标和范围，且适用宿主审批放行后调用（Codex writes approval；Pi 遵守实际权限机制）。"
    "工具成功不授权后续动作。写入不明先回读，禁止自动重试、换入口绕过或重复创建。"
)

TOOL_DESCRIPTIONS = {
    "audit_gitlab_repository_state": (
        "只读核对本地分支、状态、remote 名称及显式 GitLab 项目的默认分支/Fork parent。"
        "与 audit_repository_state 的区别是使用 glab 而非 gh。ok 只表示本地 status/remote 读取成功；"
        "gitlab/gitlab_error 独立，gitlab=null 或 gitlab_error 非空不能算远端核验通过。"
        "不写文件/仓库；不证明当前账号、origin 或 upstream 的对应关系。" + COMMON
    ),
    "list_gitlab_issue_labels": (
        "创建 Issue 前只读列出现存标签，含继承 group labels；最多前 100 项，不自动分页。"
        "ok=true 后读取 labels[].name/description/color 和 limit；不能猜测未返回的标签。"
        "不写文件/仓库，不创建标签。" + COMMON
    ),
    "create_gitlab_issue": (
        "创建并回读 GitLab Issue；调用前准备完整标题/Markdown 正文、至少一个已核实工作类型标签。"
        "本地只校验标签存在，不判断其工作类型语义。指派当前 glab 用户；正文经 JSON 标准输入传递，避免 shell 插值。"
        "只写远端 Issue，不写本地文件/仓库。ok=true 表示回读 opened/labels/当前账号 assignee 均通过；"
        "created=true,ok=false 表示已创建但回读不符；created=null,write_attempted=true 表示结果不明。"
        '示例：{"repo_path":"/workspace/project","repo":"gitlab.example.com/team/sub/project",'
        '"title":"完善合成示例","body":"目标与验收说明","labels":["feature"]}。'
        + COMMON
        + WRITE
    ),
    "push_gitlab_issue_branch_to_origin": (
        "在开放、带 label、指派给当前 glab 用户的 GitLab Issue 约束下推送当前非 main/master 分支。"
        "调用前核实提交范围、适用检查、工作类型标签和授权；本地要求工作区干净、当前同名分支，"
        "并核实 origin 的 fetch 与全部 push URL 对应显式项目。固定 git push origin <branch>，不强推。"
        "会更新远端 Git 分支；不创建 Issue/MR、不合并。ok 只表示推送命令结果，之后回读远端 OID。"
        + COMMON
        + WRITE
    ),
    "create_gitlab_merge_request": (
        "为已验证且已推送的本项目 source/head 与 target/base 创建开放 MR，保持接口术语 base_branch/head_branch。"
        "先核实完整提交范围、开放 Issue、准确同项目分支、正文 Closes/Fixes/Resolves #N 和授权；"
        "跨项目 Fork MR 不适用。默认指派当前 glab 用户，JSON 标准输入提交 Markdown，不自动删除 source。"
        "只写远端 MR，不推送或写本地仓库。ok=true 表示回读 opened/base/head/assignee/关闭关联均通过；"
        "created=true,ok=false 或 created=null,write_attempted=true 必须回读，不能重复创建。"
        + COMMON
        + WRITE
    ),
    "merge_gitlab_merge_request": (
        "单独获合并授权后即时合并 GitLab MR；与 gh 合并接口不同，必须遵循项目现有 merge_method/squash_option。"
        "要求 opened、draft=false、has_conflicts=false、detailed_merge_status=mergeable（含服务端审批/讨论/保护），"
        "head_pipeline.status=success 且 pipeline.sha 精确匹配 MR sha；无 pipeline/合并结果 pipeline SHA 不同均停止，不能推断 CI 通过。"
        "main target 只 squash；merge 仅适用项目 merge；rebase 仅适用已配置 rebase_merge/ff，不执行 rebase 或修改配置。"
        "固定 PUT merge 并绑定 sha、auto_merge=false、不删除 source；服务端保护继续执行，不管理员绕过。"
        "只修改远端 MR/目标分支，不写本地仓库。ok=true/merged=true 需回读 merged 和 merged_at；"
        "返回 pre_merge_head_oid 供获授权后的清理使用；merged=null 表示写入不明。"
        + COMMON
        + WRITE
    ),
    "audit_issue_mr_policy": (
        "只读确定性审计 GitLab Issue/MR，区别于会调用 OpenAI Decisions 的 audit_issue_pr_policy。"
        "至少提供一个正数 Issue 或 MR iid；只查已请求对象 opened，提供 expected_base/head 时才比较 target/source，"
        "同时给两种编号才检查正文关闭 Issue 关联。不查 CI、labels、assignee、审核或可合并性。"
        "expected_base/head 需要 mr_number；null 表示未请求而非失败。passed=true 仅覆盖这些明确规则，errors 非空为失败。"
        "不写文件/仓库或外部资源。" + COMMON
    ),
    "push_gitlab_fork_main_fast_forward": (
        "仅在已核实真实 GitLab Fork、默认分支和当前分支均为 main、工作区干净、origin 匹配显式项目时同步镜像。"
        "调用前核实 upstream 对应真实 parent 且同步基线正确；工具要求 origin/upstream 已存在及 upstream/main 是 main 祖先。"
        "固定 git push origin main，不 fetch、不 rebase、不强推，不代替需求分支推送。只写远端 Git 分支；ok 后回读 OID。"
        + COMMON
        + WRITE
    ),
    "cleanup_merged_mr_local_branch": (
        "仅在单独授权同步 base 和删除本地 head 后使用；MR 已合并不自动授权。"
        "要求干净工作区、origin 匹配、MR merged/merged_at、source/target 均属于显式项目，禁止 main/master head。"
        "跨项目 Fork MR 不适用。branch_name=null 使用实际 source；显式值必须相同。"
        "切换实际 target、git pull --ff-only origin <target>、普通删除本地 source；"
        "普通删除失败时仅在 merged_head_oid（合并前记录）精确匹配本地 source OID 后允许 -D。"
        "会写本地分支/工作区并联网 pull，不删远端分支/worktree、不合并 MR。"
        "completed/actions/error 表示实际部分进度；失败先回读，保留现场。"
        + COMMON
        + WRITE
    ),
}

REPO_PARAMETERS = {
    "repo_path": "必填，目标仓库/worktree 绝对根目录，不接受子目录或相邻 checkout。",
    "repo": "必填，host/group[/subgroup]/project；支持自托管主机及嵌套 group，host 不含端口，不含协议、凭据、.git 后缀；自定义 API 端口使用已核实的 glab api_host 配置。",
}
ISSUE_NUMBER = "项目内正数 Issue iid（#N），不是全局 id。"
MR_NUMBER = "项目内正数 MR iid（!N），不是全局 id。"
PARAMETER_DESCRIPTIONS = {
    "audit_gitlab_repository_state": dict(REPO_PARAMETERS),
    "list_gitlab_issue_labels": dict(REPO_PARAMETERS),
    "create_gitlab_issue": {
        **REPO_PARAMETERS,
        "title": "非空标题；默认遵循用户语言要求。",
        "body": "非空完整 Markdown 正文，通过 JSON 标准输入传递，不当作 shell 代码。",
        "labels": "至少一个现存工作类型标签名，须出现在前 100 个项目/继承标签中；非空且不含逗号。",
    },
    "push_gitlab_issue_branch_to_origin": {
        **REPO_PARAMETERS,
        "branch_name": "当前检出且工作区干净的有效非 main/master 分支名，只同名非强推到 origin。",
        "issue_number": ISSUE_NUMBER,
    },
    "create_gitlab_merge_request": {
        **REPO_PARAMETERS,
        "title": "非空完整 MR 标题。",
        "body": "非空 Markdown，必须含指定 Issue 的 Closes/Fixes/Resolves #N。",
        "base_branch": "准确 target 分支，不默认 main；须与 head 不同且为有效分支。",
        "head_branch": "准确 source 分支，本地已存在且调用前已推送到同一项目；跨项目 Fork MR 不适用。",
        "issue_number": ISSUE_NUMBER,
    },
    "merge_gitlab_merge_request": {
        **REPO_PARAMETERS,
        "mr_number": MR_NUMBER,
        "merge_method": "必填 squash/merge/rebase；main 只 squash，其余须与项目现有合并配置相容，不自动更改配置。",
    },
    "audit_issue_mr_policy": {
        **REPO_PARAMETERS,
        "issue_number": ISSUE_NUMBER
        + " 默认 null，不检查 Issue；与 mr_number 至少提供一个。",
        "mr_number": MR_NUMBER
        + " 默认 null，不检查 MR；与 issue_number 至少提供一个。",
        "expected_base": "可选期望 target 分支，默认 null 不比较；非 null 时须给 mr_number。",
        "expected_head": "可选期望 source 分支，默认 null 不比较；非 null 时须给 mr_number。",
    },
    "push_gitlab_fork_main_fast_forward": dict(REPO_PARAMETERS),
    "cleanup_merged_mr_local_branch": {
        **REPO_PARAMETERS,
        "mr_number": MR_NUMBER,
        "branch_name": "默认 null 使用 MR source；显式值须与 source 相同，禁止 main/master。",
        "merged_head_oid": "默认 null 只普通删除；40/64 位十六进制合并前 head SHA，须由合并前证据记录且精确匹配本地分支才允许 -D。",
    },
}
