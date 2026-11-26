# 安装与构建

从源码 checkout 执行 `/bin/bash ./dws --help` 可查看独立操作。按下面的目标选择命令；对应 Hook 合同包含参数、目标检查、预览及验收步骤，安装前可直接查阅所选合同。需要 `uv` 位于 PATH。

## 构建与安装发行包

`/bin/bash ./dws --uv-build` 在 `dist/` 生成 sdist 和 wheel。`/bin/bash ./dws --uv-tool-install` 安装与项目当前版本匹配的 wheel；重装加 `--force`。见 [项目工具合同](skills/dev-workflow-standards/hooks/install-tooling.md)。

## 独立安装 Skill

选择 `/bin/bash ./dws --skills-install` 或 `/bin/bash ./dws --skills-update`。默认目标为 `~/.agents/skills/dev-workflow-standards`，也可选择独立的仓库外目录。见 [Skill 合同](skills/dev-workflow-standards/hooks/install-skill.md)。

## 版本管理与更新全局 AGENTS.md

选择 `/bin/bash ./dws --agents-install` 或 `/bin/bash ./dws --agents-update`，从当前源码模板创建或更新用户的 `~/.codex/AGENTS.md`。见 [全局指令合同](skills/dev-workflow-standards/hooks/install-global-agents.md)。

## Codex 中安装

选择 `/bin/bash ./dws --mcp-install` 或 `/bin/bash ./dws --mcp-update`，安装软件包、注册服务并配置环境变量转发。只注册已安装工具或只修复转发时，有独立入口。见 [Codex MCP 合同](skills/dev-workflow-standards/hooks/install-codex-mcp.md)。

## 安装与更新原生 Codex Hooks

选择 `/bin/bash ./dws --hooks-install --global` 或 `/bin/bash ./dws --hooks-update --global`。项目级注册改用 `--project-root` 和已有项目的绝对路径。预览、合并及宿主信任步骤见 [原生 Codex Hooks 合同](skills/dev-workflow-standards/hooks/install-codex-hooks.md)。

## 给 Pi Code Agent 注册 MCP

选择 [Pi MCP 合同](skills/dev-workflow-standards/hooks/install-pi-mcp.md) 中的独立脚本命令，按需安装包并注册到用户级或项目级配置。Pi 可从同一 Skill 目录加载声明式合同。

## 从旧名称迁移

先核实存在的旧服务和软件包，再处理已获准的旧资源并按新名称注册。见 [旧名称迁移](skills/dev-workflow-standards/hooks/install-codex-mcp.md#旧名称迁移)。

## 安装排查

### 发布包缺少 Skill 资源

先核对是否使用了完整 wheel 安装的管理 CLI。见 [Skill 命令入口排查](skills/dev-workflow-standards/references/installation.md#包资源缺失与命令入口排查)。

### Codex 缺少 OpenAI 环境变量

检查服务的变量名转发、Codex 主进程是否具有非空变量以及是否已重载。见 [Codex stdio 环境排查](skills/dev-workflow-standards/references/openai-workflow-tools.md#codex-stdio-环境传递与排查)。
