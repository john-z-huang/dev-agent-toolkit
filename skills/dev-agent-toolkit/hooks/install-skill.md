# 安装与更新 dev-agent-toolkit Skill

## 进入条件

需要首次部署或更新可被 Code Agent 加载的 Skill 快照，或排查已安装快照。已安装快照需显式更新。

## 执行条件

默认目标是 `~/.agents/skills/dev-agent-toolkit`。首次安装要求目录尚不存在。用 `--target` 指定独立的仓库外目录，并在预览、正式操作和回读中沿用同一目标。目标路径不得含 `..` 或符号链接。

从核实的源码根目录选择对应命令。启动器用 `uv` 查找现有的 Python 3.11 或更新版本，由 Python 直接读取和校验 checkout 中的 Skill。安装、更新和 `--dry-run` 使用同一份源码。预览不会创建目标、锁或文件。

```bash
/bin/bash ./dev-agent-toolkit --skills-install
/bin/bash ./dev-agent-toolkit --skills-update
/bin/bash ./dev-agent-toolkit --skills-show
```

更新只接受本工具管理且完整的快照。检测到用户修改、缺失或额外资源、链接或特殊文件时保留现场。发布使用 macOS/Linux 的原子目录操作。按情况查阅 [安装入口排查](../references/installation.md#包资源缺失与命令入口排查) 或 [锁竞争与中断恢复](../references/installation.md#安装与更新中断处理)。

## 离开条件

用 `--skills-show` 回读目标、来源版本、已安装版本和状态。同版本内容一致时更新可返回 `unchanged`。按宿主支持的方式重新加载 Skill。需要验收可发现性时核对实际 Skill 入口。

## 重新进入条件

目标目录、快照内容、checkout 或宿主变化时重新核对对应项。
