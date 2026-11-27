# 安装与更新原生 Codex Hooks

## 进入条件

需要在 Codex 用户全局或显式项目目录安装、更新、合并或预览原生 Hooks。声明式合同随 Skill 快照部署，安装它们使用 [Skill 合同](install-skill.md)。

## 执行条件

核对源码 checkout、uv tool 目录和目标范围。必须选择 `--global` 或 `--project-root` 之一。全局默认 `~/.codex`，显式 `CODEX_HOME` 须为已有绝对目录；项目使用已有绝对项目目录，配置写入其 `.codex` 下。全局和项目 Hooks 可以累积触发，分别管理各自目标。

```bash
/bin/bash ./dev-agent-toolkit --hooks-install --global --dry-run
/bin/bash ./dev-agent-toolkit --hooks-install --global
/bin/bash ./dev-agent-toolkit --hooks-update --global
/bin/bash ./dev-agent-toolkit --hooks-install --project-root /absolute/path/to/target-project
/bin/bash ./dev-agent-toolkit --hooks-update --project-root /absolute/path/to/target-project
```

从仓库根目录选择对应命令。正式操作会安装或刷新独立的 `dev-agent-toolkit-hooks` uv tool（包括同版本），再注册所选范围。源码入口的 `--dry-run` 只显示计划。需要独立安装或刷新 Hooks CLI 时，在源码根目录执行 `/bin/bash -c 'exec uv tool install --managed-python --reinstall-package dev-agent-toolkit-hooks ./codex-hooks'`。若包已安装，使用其 `configure` 子命令对目标做只读校验。以下为全局首次合并预览，换目标或操作时相应调整范围及 `--install`／`--update`。预览会输出候选配置，报告中只保留必要状态和经过审阅的差异。

```bash
/bin/bash -c 'tool_bin=$(uv tool dir --bin) && "$tool_bin/dev-agent-toolkit-hooks" configure --global --install --merge --dry-run'
```

首次安装遇到其他工具的普通 `hooks.json` 时，可在核对现有内容、获准合并后使用 `/bin/bash ./dev-agent-toolkit --hooks-install --global --merge`（项目级也可用 `--merge`）。正式合并先把原始字节备份到目标目录的 `hooks.json.backup-*`，保留其字段、事件和处理器。已有 Dev Agent Toolkit 受管清单时使用更新入口。更新拒绝覆盖未知、本地修改、缺失或链接资源。更新期间避免其他写入者，失败时先核对实际版本、配置、清单与备份。

目标存在旧版 `hooks/dev_workflow.manifest.json` 或 `hooks/dev_workflow.py` 时，注册器拒绝首次安装及合并预览。若仅剩 `hooks.json`，合并还会拒绝旧安装器生成的直接绝对路径 `dev-workflow-standards-hooks` 命令。遇到这些诊断时，先单独审阅并处理旧版注册，再预览新安装。

### 受管配置与外部改动对账

默认更新会拒绝清单校验不符。若已核对改动属于其他工具的 Hooks，且本工具的原受管事件组保持完整，获准后才对同一范围使用 `--reconcile`。先用上面的独立 uv tool 命令安装带该选项的 CLI，再精确预览并执行更新。

```bash
/bin/bash -c 'tool_bin=$(uv tool dir --bin) && "$tool_bin/dev-agent-toolkit-hooks" configure --global --update --reconcile --dry-run'
/bin/bash ./dev-agent-toolkit --hooks-update --global --reconcile
```

对账要求格式 3 的受管清单。用相同的已安装入口、相同的受管组定义及清单中的原配置重建原指纹；原配置中的其他组与受管组不能重叠。当前配置的受管组须完整，按原顺序保留在各自事件末尾。正式操作先备份实际 `hooks.json`，保留当前其他 Hooks 配置及顶层字段，已移除的外部组继续保持移除。无法确认受管组或原指纹时，保留现场并审阅差异。

## 离开条件

核对实际工具版本、目标 `hooks.json` 和 `hooks/dev_agent_toolkit.manifest.json`。事件命令应指向 `uv tool dir --bin` 中的 CLI 绝对路径。配置写入本身只完成注册。若当前任务包含启用和验收，在支持 Hooks 的 Codex 会话用 `/hooks` 审阅并按宿主授权信任定义，核对事件真实触发。宿主不支持、禁用或未信任时，如实记录对应阶段。事件行为见 [原生适配](../references/codex-hooks.md)。

## 重新进入条件

目标范围、安装路径、受管配置、清单、备份、宿主或信任状态发生变化时，重新核对对应阶段。
