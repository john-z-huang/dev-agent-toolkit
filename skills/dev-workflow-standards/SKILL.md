---
name: dev-workflow-standards
description: >-
  开发操作的声明式指令 Hooks：适用于代码理解、项目修改、Python/Shell 执行、需代理的本地 Modal 依赖管理及 Git/GitHub/GitLab 工作。
  按当前动作和资源状态提供进入、执行、离开与重新核验条件，由 Agent 自行规划顺序和选择工具。
---

# 开发操作约束

本 Skill 提供动作条件，不规定任务路线、步骤队列或统一状态机。Agent 根据用户目标自行拆解、排序和组合操作；按当前动作读取 [Hook 索引](hooks/index.md) 中相关合同及所需参考资料，无须通读或逐个调用全部 Hook。独立脚本、只读分析不因此增加 Git/GitHub 动作。

Hook 是指令合同，由 Agent 根据实际事实判断适用性，不是宿主回调或新的 MCP 工具。进入表示需要核对约束，授权属于执行条件；工具成功或 Hook 离开均不授权其他动作。多 Hook 可同时适用，约束累积；保留真实数据依赖，不设置全局优先路线。未知、未检查和无法访问不等于 false；不适用不等于验证通过。

另提供可选的 [原生 Codex Hooks 适配](references/codex-hooks.md)，将少量确定性条件和定向提示注册到宿主事件。该组件独立安装、审阅和信任；不改变本 Skill 的合同语义，也不代替完整校验或用户授权。

## 宿主审批兼容

本节同样适用于本项目 MCP 服务指令、工具描述及参考资料中的 `Codex writes approval` 要求；它是 Codex 宿主的写操作审批机制，不是本项目的 MCP Tool 或通用 Hook。

- **Codex**：遵守实际配置的写操作审批要求，不得绕过。
- **Pi Code Agent**：确认当前宿主未提供该 Codex 专属机制时，该宿主条件不适用；不要求查找、调用、安装或模拟不存在的工具/Hook，不因这一缺失单独阻塞已获授权的操作，也不得声称已获 Codex 审批。可选原生 Codex Hooks 适配无须在 Pi 中安装，声明式 Hook 合同仍适用。
- **共同要求**：写操作前核对用户对当前动作、目标及范围的明确授权，并遵守宿主实际存在的权限、审批机制、安全限制及工具前置校验。没有审批界面不等于获得用户授权；既有授权在原范围内有效，无须因换工具重复询问，缺失或不清时先询问用户。内容修改授权不自动扩展到提交、推送、合并、删除、历史重写、配置或 Memory 写入。
- **失败关闭**：未知审批状态不等于已确认缺少机制；实际拒绝、权限错误或校验失败必须停止受影响操作并报告，不得改用 CLI、其他工具或 Codex App Server 绕过。只读检查通过、工具可用或调用成功均不替代授权。

## Pi 工具发现与能力边界

- Pi 默认可能通过 codemode 间接暴露 MCP 工具：先用 `searchTools` / `describeTool` 核对实际名称和 Schema，用 `describeNamespace` 读取完整服务指令；未直接声明不等于未提供，hidden 不可绕过。MCP 名称前缀由宿主注册名决定，不硬编码其他宿主的工具全名。
- Skill 默认安装目录 `~/.agents/skills/` 可被 Pi 发现；原生 Codex Hooks 和全局 `~/.codex/AGENTS.md` 不会自动转换为 Pi 扩展或全局指令，加载本 Skill 不依赖它们。不为兼容而自动改全局配置。
- 历史读取按实际宿主能力判断，不假定存在 `read_thread`。本项目会话来源模型仅接受真实 Codex 来源，不支持把 Pi 原生会话 ID/路径伪装为 `codex://threads/…`。缺少历史读取能力时报告缺口，只暂停依赖历史的工作；普通开发、模板查询及其他不依赖来源的工具仍可使用。详见 [会话事实](references/codex-session-facts.md)。
- MCP 进程环境与调用时限按宿主配置：Pi stdio 继承启动 Pi 的环境，配置使用 `timeout`（秒），而不是 Codex 的 `env_vars` / `tool_timeout_sec`。配置变化后重新加载，环境变化必要时重启 Pi；不输出配置值。见 [环境传递](references/openai-workflow-tools.md#pi-stdio-环境传递与工具时限)。

## 共用边界

- 托管操作先核实 GitHub 或 GitLab 平台及准确目标；GitLab 使用 `glab` 和对应 Issue/MR 工具，详见 [GitLab 兼容规则](references/gitlab.md)。GitHub 仓库迁移到 GitLab 的范围、验收和无强推流程见 [GitHub→GitLab 迁移](references/github-to-gitlab-migration.md)。通用 Git、worktree、提交、授权及非强推约束跨平台一致；纯 Git 动作不依赖 GitHub 登录，自托管平台不能仅凭域名猜测。

- 用户意图和宿主权限共同约束当前动作；既有授权在原范围持续有效，不因换工具重复询问，也不扩大到提交、推送、合并、删除、历史重写、配置或 Memory 写入。
- 准确识别仓库/worktree 和资源；repo-bound 工具显式传绝对 `repo_path`。保留用户现有内容，结果依据真实回读，不编造测试、文件、提交或远端状态。
- 优先使用覆盖需求的 MCP/已授权 Connector；能力缺口按 [CLI 补充边界](references/cli-fallback.md) 处理。实际失败、拒绝或写入不明适用 [恢复 Hook](hooks/recovery.md)，不能换入口绕过。
- 语义判断和开发文案生成可按 [OpenAI 工具协议](references/openai-workflow-tools.md) 提交最小结构化事实，由专用工具承担分析/生成，再核对结果；不要求先自行完成同一份内容。会话动作工具仅为按需建议，不替 Agent 调度。
- `check_api_input` 默认允许向既定配置服务联网审核，无需前置审核、自我审核或逐次人工授权；审核通过后允许当前任务所需相同内容外发。业务工具自动审核实际出站内容，不重复公开预检。用户禁止外发及更高优先级限制仍生效；通过不授权发布或其他写入。详细条件见 [外部 API Hook](hooks/external-api.md)。
- 不输出或记录凭据，不添加 Agent 署名/生成声明。资源、内容、授权或相关证据变化时，只重新核验受影响条件，不重跑整条任务。

本目录为独立安装快照；源码修改不更新已安装 Skill 或全局指令，也不重新加载 MCP。安装、显式更新和旧目录保护见 [安装说明](references/installation.md)。安装 Skill 不注册 MCP、不复制 Git Hook、不迁移旧项目。
