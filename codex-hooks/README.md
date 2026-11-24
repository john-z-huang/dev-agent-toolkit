# 原生 Codex Hooks

依据参考会话 `codex://threads/01a1b9b9-0838-7660-8157-32074cbacf46`，将指令合同中可观察、可确定的部分转换成运行时回调。协议依据：[官方 Hooks 文档](https://learn.chatgpt.com/docs/hooks)（2026-11-08 核对）。参考会话是设计背景，其历史授权不沿用。

## 转化范围

| 原合同 | 原生事件与实现 | 保留给 Agent 或执行层的部分 |
|---|---|---|
| 项目修改 | `SessionStart` 注入边界；`PreToolUse` 对 apply_patch 提示范围核对 | 内容归属、用户目标、hunk 审阅 |
| 代码理解 | `SessionStart` 提示准确 Serena 项目与语义证据 | 查询选择、跨模块影响判断 |
| Python/Shell 环境 | Shell 的 `PreToolUse` 提示按真实项目和目标环境选择 | 用户例外、workspace 归属、版本与依赖约束；不自动改写命令 |
| Worktree、Git、GitHub | 本服务 MCP `PreToolUse` 对非 null 的显式 `repo_path` 硬校验绝对路径及 Git 根目录 | 授权、远端事实、暂存内容及 OID；原 Git hooks 和 MCP 硬校验继续执行 |
| 会话事实 | `SessionStart` 保留事实与授权边界 | 原会话读取、来源核对、Memory 授权；不解析 transcript |
| 外部 API | 保留原合同和统一客户端边界 | 不从工具名猜测实际 API payload；不增加调用、重复审核或读取凭据 |
| 恢复 | `PostToolUse` 识别结构化失败后注入回读与禁止盲重试提示 | 判断实际副作用、修复和恢复授权 |
| 完成交付 | `UserPromptSubmit` 在每回合开始注入证据清单 | 任务验收与真实测试；不以脆弱的最终消息文本匹配阻止结束 |

`Stop` 无稳定的任务验收状态，不能可靠判断是否完成，因此不注册强制阻塞检查；避免循环继续、分析任务被要求运行测试或顺带提交。恢复提示不会替换原工具结果，也不能撤销副作用。所有提示都是静态规则，事件中的用户文本、命令和工具正文不会被提升为 developer 指令。

`statusMessage` 按触发场景设置：会话开始显示加载约束与授权边界，用户提交显示交付与验证要求，工具结束显示失败识别与恢复提示。`PreToolUse` 对 MCP、Python/Shell 和 `apply_patch` 分别匹配，显示仓库路径、执行环境和修改范围提示；同一个工具只匹配其中一组。

## 安装、注册与更新

Hooks 作为独立的 `dev-workflow-standards-hooks` Python 发行包发布，与 MCP Server 分开安装；Python 3.11+，运行时无第三方依赖，仅使用标准库和 Git。以下命令在源码仓库根目录执行：

```bash
# 不执行安装或注册，仅显示计划；此预览不核验目标配置冲突
./dws --hooks-install --global --dry-run
# 安装独立 uv tool，再注册到全局 Codex 配置
./dws --hooks-install --global
# 已有其他 Hooks 配置时，显式备份并合并
./dws --hooks-install --global --merge
# 强制重装本地包以刷新同版本源码，再更新受管注册
./dws --hooks-update --global
# 项目级注册：用 --project-root 替代 --global
./dws --hooks-install --project-root /absolute/path/to/project
```

`dws` 调用带 PEP 723 声明的安装脚本，使用安装器的 Python 执行 `uv tool install --reinstall-package dev-workflow-standards-hooks ./codex-hooks`，更新另加 `--force`。即使包版本相同，也会从本地源码重新构建。安装脚本随后定位并核验已安装 CLI，再用 `configure` 注册配置。注册失败时会保留已安装的包。Hooks 使用独立的 uv tool 环境。

也可分别执行安装和注册：

```bash
uv tool install ./codex-hooks
# 精确预览最终配置，读取并核验已有资源，但不写入
"$(uv tool dir --bin)/dev-workflow-standards-hooks" configure --global --install --merge --dry-run
# 审阅后去掉 --dry-run 正式写入；无其他配置时不加 --merge
"$(uv tool dir --bin)/dev-workflow-standards-hooks" configure --global --install --merge
```

命令无参数时从 stdin 读取单个事件 JSON 并返回事件结果；`--version` 显示包版本，`configure --help` 显示注册选项。`configure` 无 `--install` 或 `--update` 时仅输出候选配置；`configure --dry-run` 执行相应只读校验。它不安装或更新包；包管理由 `uv tool` 完成。

注册必须在 `--global` 与 `--project-root` 中二选一。用户全局目录默认 `~/.codex`，显式 `CODEX_HOME` 必须为已有绝对目录；项目级目录为 `<project>/.codex`。配置中的 `command` 是通过 `uv tool dir --bin` 定位的 `dev-workflow-standards-hooks` 可执行文件绝对路径，按 POSIX Shell 引用；不包含源码脚本或项目 Python 路径。安装后源码 checkout 与开发虚拟环境可独立变化，运行环境由 uv tool 管理。移动 uv tool 的 bin 目录后需重新注册。

注册只写 `hooks.json` 和 `hooks/dev_workflow.manifest.json`，不再复制运行脚本。首次安装拒绝已有资源；已有其他工具的普通 `hooks.json` 可显式 `--merge`，原事件、匹配器、处理器与其他顶层字段全部保留，相同组不重复追加。正式合并先独占创建 `hooks.json.backup-*` 保存原始字节，并在 stderr 报告备份路径。更新依据清单保护本地修改，保留合并时的原 Hooks；手工编辑配置会阻止自动更新。未知旧文件、无效 JSON、链接或不支持的结构会被拒绝。

旧版复制脚本的受管安装可通过 `--hooks-update` 迁移：先核验原配置、脚本和清单，随后把注册改为新命令；原脚本保留但不再调用，不自动删除用户文件。没有有效受管清单的旧安装仍需手工审阅。新清单格式为 3；校验和只检测完整性，不是来源签名或授权凭证。

更新期间停止其他写入者。文件分别原子替换，多文件不保证整体原子性；失败时检查实际配置、清单和备份后恢复，不盲重试。安装不修改 `config.toml`、Git 配置、Skill、MCP 注册或宿主信任。

新建或恢复会话后，通过 Codex `/hooks` 审阅并信任当前定义，再确认事件触发。全局、项目、内联与插件 Hooks 会累积运行，不会相互覆盖；同一套规则通常只需选择一个范围，安装器不自动清理另一范围。宿主禁用、managed-only 限制或未信任时不会执行；注册不自动启用功能或授予信任。

## 协议与边界

- 输入为 stdin 单个 JSON 对象；输出为 stdout 单个事件结果。明确违反路径规则返回 `PreToolUse.permissionDecision=deny`，不会返回 `allow` 或改写参数，更不会处理 `PermissionRequest` 自动批准。
- 匹配默认注册名 `mcp__dev-workflow-standards-tools__*` 及规范化名称 `mcp__dev_workflow_standards_tools__*`，校验该服务的显式路径。缺失或 null 字段是否合法仍由对应工具 Schema 校验；不把 cwd 填入缺失字段。其他服务不套用本项目的输入约定。服务改名时需同步 matcher 和运行时前缀。
- 路径检查使用固定只读 `git rev-parse --show-toplevel`，关闭可选 index 锁，移除继承的 `GIT_*` 覆盖，支持其他目标仓库、符号链接路径和 linked worktree；并不证明目标得到用户授权。
- 失败识别仅覆盖对象的 `isError=true`、`ok=false`、非零整数 `exit_code`，以及 `structuredContent.ok=false`。不解析不稳定的日志、文本化 MCP JSON 或运行中进程；识别不到不表示通过。原工具返回仍供 Agent 判断。
- 运行时与安装器不联网、不调用 OpenAI、不读取会话/凭据、不写 Memory、不执行 Git 写入。运行时不写文件；注册器只管理显式目标的配置、清单和合并备份。`dws` 的安装阶段会通过 `uv tool` 构建/安装包，可能访问包索引；事件运行与配置注册均离线。不自动跑测试、暂存或发布。
- Hook 超时、异常或无效输出可能让调用继续；特殊工具路径也可能不触发 hooks。本组件是辅助防线，不能替代 MCP、Git hooks、宿主审批和统一 API 客户端约束。

## 验证

```bash
uv run --project mcp-server -- python -m unittest discover -s tests -p 'test_codex_hooks*.py'
```

测试使用合成事件、临时仓库和临时安装目录，包含真实 stdin/stdout、拒绝协议、根目录/子目录/linked worktree、失败分类、无凭据回显、路径含空格和引号、从其他 cwd 执行、拒绝覆盖及符号链接保护。测试不代表当前会话已重新加载或信任配置；真实宿主发现与触发需在安装后另行核对。
