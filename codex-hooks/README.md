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

Hooks 作为独立的 `dev-workflow-standards-hooks` Python 发行包发布，要求 Python 3.11+，运行时使用标准库和 Git。按 [原生 Codex Hooks 合同](../skills/dev-workflow-standards/hooks/install-codex-hooks.md) 选择预览、安装、合并或更新，以及宿主审阅与信任步骤。

已安装的 CLI 无参数时从 stdin 读取单个事件 JSON。`--version` 查看包版本，`configure --help` 查看注册选项。`configure` 无 `--install` 或 `--update` 时仅输出候选配置。配置命令使用 uv tool 的绝对入口，不依赖源码或项目虚拟环境。移动 uv tool 的 bin 目录后需重新注册。

## 协议与边界

- 输入为 stdin 单个 JSON 对象；输出为 stdout 单个事件结果。明确违反路径规则返回 `PreToolUse.permissionDecision=deny`，不会返回 `allow` 或改写参数，更不会处理 `PermissionRequest` 自动批准。
- 匹配默认注册名 `mcp__dev-workflow-standards-tools__*` 及规范化名称 `mcp__dev_workflow_standards_tools__*`，校验该服务的显式路径。缺失或 null 字段是否合法仍由对应工具 Schema 校验；不把 cwd 填入缺失字段。其他服务不套用本项目的输入约定。服务改名时需同步 matcher 和运行时前缀。
- 路径检查使用固定只读 `git rev-parse --show-toplevel`，关闭可选 index 锁，移除继承的 `GIT_*` 覆盖，支持其他目标仓库、符号链接路径和 linked worktree；并不证明目标得到用户授权。
- 失败识别仅覆盖对象的 `isError=true`、`ok=false`、非零整数 `exit_code`，以及 `structuredContent.ok=false`。不解析不稳定的日志、文本化 MCP JSON 或运行中进程；识别不到不表示通过。原工具返回仍供 Agent 判断。
- 运行时与安装器不联网、不调用 OpenAI、不读取会话/凭据、不写 Memory、不执行 Git 写入。运行时不写文件；注册器只管理显式目标的配置、清单和合并备份。`dws` 的安装阶段会通过 `uv tool` 构建/安装包，可能访问包索引；事件运行与配置注册均离线。不自动跑测试、暂存或发布。
- Hook 超时、异常或无效输出可能让调用继续；特殊工具路径也可能不触发 hooks。本组件是辅助防线，不能替代 MCP、Git hooks、宿主审批和统一 API 客户端约束。

## 验证

从仓库根目录运行。`ruff format` 写入 `codex-hooks/` 中的 Python 源码，另外三条命令分别检查格式、lint 和类型。

```bash
/bin/bash -c 'cd codex-hooks && uv run --locked -- ruff format'
/bin/bash -c 'cd codex-hooks && uv run --locked -- ruff format --check'
/bin/bash -c 'cd codex-hooks && uv run --locked -- ruff check --no-fix'
/bin/bash -c 'cd codex-hooks && uv run --locked -- ty check'
```

从仓库根目录运行离线测试：

```bash
/bin/bash -c 'uv run --locked --project mcp-server -- python -m unittest discover -s tests -p "test_codex_hooks*.py"'
```

测试使用合成事件、临时仓库和临时安装目录，包含真实 stdin/stdout、拒绝协议、根目录/子目录/linked worktree、失败分类、无凭据回显、路径含空格和引号、从其他 cwd 执行、拒绝覆盖及符号链接保护。测试不代表当前会话已重新加载或信任配置；真实宿主发现与触发需在安装后另行核对。
