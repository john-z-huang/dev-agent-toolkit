# 安装与更新 dev-agent-toolkit Skill

## 进入条件

需要首次部署或更新可被 Code Agent 加载的 Skill 快照，或排查已安装快照。源码变化和 uv tool 更新各自独立，已安装快照需显式更新。

## 执行条件

默认目标是 `~/.agents/skills/dev-agent-toolkit`。首次安装要求目录尚不存在。用 `--target` 指定独立的仓库外目录，并在预览、正式操作和回读中沿用同一目标。目标路径不得含 `..` 或符号链接。

从核实的源码根目录选择对应命令。正式操作会重新构建并刷新共享 uv tool（包括同版本），再管理 Skill；构建与安装可能联网。追加 `--dry-run` 可用已安装的管理 CLI 只读预览，该预览基于当前安装的包资源。

```bash
/bin/bash ./dev-agent-toolkit --skills-install
/bin/bash ./dev-agent-toolkit --skills-update
```

只有完整 wheel 时，先按 [项目工具](install-tooling.md) 安装对应包，再从 uv 的实际 bin 目录运行管理 CLI。`install`、`update` 可加 `--dry-run`。

```bash
/bin/bash -c 'tool_bin=$(uv tool dir --bin) && "$tool_bin/dev-agent-toolkit" skills install'
/bin/bash -c 'tool_bin=$(uv tool dir --bin) && "$tool_bin/dev-agent-toolkit" skills update'
/bin/bash -c 'tool_bin=$(uv tool dir --bin) && "$tool_bin/dev-agent-toolkit" skills show'
```

更新只接受本工具管理且完整的快照。检测到用户修改、缺失或额外资源、链接或特殊文件时保留现场。发布使用 macOS/Linux 的原子目录操作，其他环境不支持时停止。开发环境的可编辑包可能缺少包内 Skill 资源。按情况查阅 [安装入口排查](../references/installation.md#包资源缺失与命令入口排查) 或 [锁竞争与中断恢复](../references/installation.md#安装与更新中断处理)。

## 离开条件

用 `skills show` 回读目标及包版本、已安装版本和状态，确认与预期一致。同版本内容一致时更新可返回 `unchanged`。让宿主按其支持方式重新加载 Skill；Pi 可在已有会话用 `/reload`。需要验收可发现性时核对实际 Skill 入口。

## 重新进入条件

目标目录、快照内容、来源 wheel、checkout 或宿主变化时重新核对对应项。
