# 原生 Codex Hooks（已归档）

本目录保存历史运行时、注册脚本、专用测试和安装说明。该组件已退出维护。旧的根启动器参数 `--hooks-install` 和 `--hooks-update` 已撤下，归档目录不进入当前 MCP 发行包或 Skill 快照。以前安装的 uv tool 和本机 Codex 配置需要单独管理。仓库仍忽略旧安装器生成的本机配置文件，避免包含绝对路径的文件被提交。

适配将 [Skill 声明式合同](../../skills/dev-agent-toolkit/hooks/index.md) 中可观察、可确定的部分接入 Codex 生命周期。Pi 通过 Skill 使用声明式合同，并按宿主的实际权限机制执行。设计背景见参考会话 `codex://threads/01a1b9b9-0838-7660-8157-32074cbacf46`。事件协议在 2026-11-08 按当时的 [官方 Hooks 文档](https://learn.chatgpt.com/docs/hooks) 核对。

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

## 历史发行包与命令行

原生 Hooks 曾作为独立的 `dev-agent-toolkit-hooks` Python 包发布。要求 Python 3.11+，运行时使用标准库和 Git；独立 sdist 包含本说明。

已安装的 CLI 无参数时从 stdin 读取单个事件 JSON。`--version` 查看包版本，`configure --help` 查看注册选项。`configure` 无 `--install` 或 `--update` 时仅输出候选配置。配置命令使用 uv tool 的绝对入口，不依赖源码或项目虚拟环境。移动 uv tool 的 bin 目录后需重新注册。

## 协议与边界

- 输入为 stdin 单个 JSON 对象；输出为 stdout 单个事件结果。明确违反路径规则返回 `PreToolUse.permissionDecision=deny`，不会返回 `allow` 或改写参数，更不会处理 `PermissionRequest` 自动批准。
- 按默认服务注册名 `dev_agent_toolkit` 匹配 Codex 工具前缀 `mcp__dev_agent_toolkit__`，校验该服务的显式路径。缺失或 null 字段是否合法仍由对应工具 Schema 校验；不把 cwd 填入缺失字段。其他服务不套用本项目的输入约定。服务改名时需同步 matcher 和运行时前缀。
- 路径检查使用固定只读 `git rev-parse --show-toplevel`，关闭可选 index 锁，移除继承的 `GIT_*` 覆盖，支持其他目标仓库、符号链接路径和 linked worktree；并不证明目标得到用户授权。
- 失败识别仅覆盖对象的 `isError=true`、`ok=false`、非零整数 `exit_code`，以及 `structuredContent.ok=false`。不解析不稳定的日志、文本化 MCP JSON 或运行中进程；识别不到不表示通过。原工具返回仍供 Agent 判断。
- 事件运行和配置注册均离线，不调用 OpenAI、不读取会话或凭据、不写 Memory、不执行 Git 写入。运行时不写文件；注册器只管理显式目标的配置、清单和合并备份。归档安装脚本通过 `uv tool` 构建或安装包，可能访问包索引。
- Hook 超时、异常或无效输出可能让调用继续；特殊工具路径也可能不触发 hooks。本组件是辅助防线，不能替代 MCP、Git hooks、宿主审批和统一 API 客户端约束。

## 历史安装、注册与更新流程

以下流程保留供历史复现。路径已调整为归档目录，命令从仓库根目录运行。

### 进入条件

需要在 Codex 用户全局或显式项目目录安装、更新、合并或预览原生 Hooks。声明式合同随 Skill 快照部署，安装它们使用 [Skill 合同](../../skills/dev-agent-toolkit/hooks/install-skill.md)。

### 执行条件

核对源码 checkout、uv tool 目录和目标范围。必须选择 `--global` 或 `--project-root` 之一。全局默认 `~/.codex`，显式 `CODEX_HOME` 须为已有绝对目录；项目使用已有绝对项目目录，配置写入其 `.codex` 下。全局和项目 Hooks 可以累积触发，分别管理各自目标。

```bash
/bin/bash -c 'exec uv run --managed-python -- archive/codex-hooks/scripts/setup-codex-hooks.py --install --global --dry-run'
/bin/bash -c 'exec uv run --managed-python -- archive/codex-hooks/scripts/setup-codex-hooks.py --install --global'
/bin/bash -c 'exec uv run --managed-python -- archive/codex-hooks/scripts/setup-codex-hooks.py --update --global'
/bin/bash -c 'exec uv run --managed-python -- archive/codex-hooks/scripts/setup-codex-hooks.py --install --project-root /absolute/path/to/target-project'
/bin/bash -c 'exec uv run --managed-python -- archive/codex-hooks/scripts/setup-codex-hooks.py --update --project-root /absolute/path/to/target-project'
```

从仓库根目录选择对应命令。正式操作会安装或刷新独立的 `dev-agent-toolkit-hooks` uv tool（包括同版本），再注册所选范围。源码入口的 `--dry-run` 只显示计划。需要独立安装或刷新 Hooks CLI 时，在源码根目录执行 `/bin/bash -c 'exec uv tool install --managed-python --reinstall-package dev-agent-toolkit-hooks ./archive/codex-hooks'`。若包已安装，使用其 `configure` 子命令对目标做只读校验。以下为全局首次合并预览，换目标或操作时相应调整范围及 `--install`／`--update`。预览会输出候选配置，报告中只保留必要状态和经过审阅的差异。

```bash
/bin/bash -c 'tool_bin=$(uv tool dir --bin) && "$tool_bin/dev-agent-toolkit-hooks" configure --global --install --merge --dry-run'
```

首次安装遇到其他工具的普通 `hooks.json` 时，可在核对现有内容、获准合并后使用 `/bin/bash -c 'exec uv run --managed-python -- archive/codex-hooks/scripts/setup-codex-hooks.py --install --global --merge'`（项目级也可用 `--merge`）。正式合并先把原始字节备份到目标目录的 `hooks.json.backup-*`，保留其字段、事件和处理器。已有 Dev Agent Toolkit 受管清单时使用更新入口。更新拒绝覆盖未知、本地修改、缺失或链接资源。更新期间避免其他写入者，失败时先核对实际版本、配置、清单与备份。

目标存在旧版 `hooks/dev_workflow.manifest.json` 或 `hooks/dev_workflow.py` 时，注册器拒绝首次安装及合并预览。若仅剩 `hooks.json`，合并还会拒绝旧安装器生成的直接绝对路径 `dev-workflow-standards-hooks` 命令。遇到这些诊断时，先单独审阅并处理旧版注册，再预览新安装。

#### 受管配置与外部改动对账

默认更新会拒绝清单校验不符。若已核对改动属于其他工具的 Hooks，且本工具的原受管事件组保持完整，获准后才对同一范围使用 `--reconcile`。先用上面的独立 uv tool 命令安装带该选项的 CLI，再精确预览并执行更新。

```bash
/bin/bash -c 'tool_bin=$(uv tool dir --bin) && "$tool_bin/dev-agent-toolkit-hooks" configure --global --update --reconcile --dry-run'
/bin/bash -c 'exec uv run --managed-python -- archive/codex-hooks/scripts/setup-codex-hooks.py --update --global --reconcile'
```

对账要求格式 3 的受管清单。用相同的已安装入口、相同的受管组定义及清单中的原配置重建原指纹；原配置中的其他组与受管组不能重叠。当前配置的受管组须完整，按原顺序保留在各自事件末尾。正式操作先备份实际 `hooks.json`，保留当前其他 Hooks 配置及顶层字段，已移除的外部组继续保持移除。无法确认受管组或原指纹时，保留现场并审阅差异。

### 离开条件

核对实际工具版本、目标 `hooks.json` 和 `hooks/dev_agent_toolkit.manifest.json`。事件命令应指向 `uv tool dir --bin` 中的 CLI 绝对路径。配置写入本身只完成注册。若当前任务包含启用和验收，在支持 Hooks 的 Codex 会话用 `/hooks` 审阅并按宿主授权信任定义，核对事件真实触发。宿主不支持、禁用或未信任时，如实记录对应阶段。事件行为见 [转化范围](#转化范围)。

### 重新进入条件

目标范围、安装路径、受管配置、清单、备份、宿主或信任状态发生变化时，重新核对对应阶段。

## 验证

从仓库根目录运行。`ruff format` 写入 `archive/codex-hooks/` 中的 Python 源码，另外三条命令分别检查格式、lint 和类型。

```bash
/bin/bash -c 'cd archive/codex-hooks && uv run --locked -- ruff format'
/bin/bash -c 'cd archive/codex-hooks && uv run --locked -- ruff format --check'
/bin/bash -c 'cd archive/codex-hooks && uv run --locked -- ruff check --no-fix'
/bin/bash -c 'cd archive/codex-hooks && uv run --locked -- ty check dev_agent_toolkit_hooks'
```

从仓库根目录运行专用离线测试。测试沿用 MCP 项目的开发环境，以使用其中的 Hatchling 构建依赖。

```bash
/bin/bash -c 'uv run --locked --project mcp-server -- python -m unittest discover -s archive/codex-hooks/tests -v'
```

测试使用合成事件、临时仓库和临时安装目录，包含真实 stdin/stdout、拒绝协议、根目录/子目录/linked worktree、失败分类、无凭据回显、路径含空格和引号、从其他 cwd 执行、拒绝覆盖及符号链接保护。测试不代表当前会话已重新加载或信任配置；真实宿主发现与触发需在安装后另行核对。
