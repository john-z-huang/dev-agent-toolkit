# 交付边界与发行包

本文件记录哪些内容随 wheel/sdist 交付、哪些只存在于源码仓库，以及修改交付内容后必须核对的路径。

## 实际交付内容

- wheel/sdist 使用显式白名单：`mcp-server/pyproject.toml` 的 wheel `packages` 与 sdist `include`。
- Skill：`mcp-server/hatch_build.py` 的 `_skill_payload` 只打包 `skills/dev-agent-toolkit/**` 中的 Markdown 和 `scripts/github_draft.py`、`scripts/validate_github_draft.py`，并校验 Skill 内的相对链接不越出 Skill 目录。
- 全局指令：同一构建钩子读取 `instructions/codex-global.md`，在 wheel 中作为 `dev_agent_toolkit_tools/global_instructions/codex-global.md`，在 sdist 中作为 `global-instructions-source.md`。
- 原生 Codex Hooks：`codex-hooks/` 作为独立发行包发布，其 sdist 包含自己的 `README.md`（`codex-hooks/pyproject.toml`）。
- 安装目标：Skill 默认安装到 `~/.agents/skills/dev-agent-toolkit`，全局指令默认写入 `~/.codex/AGENTS.md`。

## 不交付内容

`.agents/`、根 `README.md`、`AGENTS.md`、`INSTALL.md`、`docs/`、`archive/`、`tests/`、`scripts/` 与根启动器 `dev-agent-toolkit` 都不进入 wheel/sdist。

## 禁止随意移动的路径

- `dev-agent-toolkit` 启动器的 `--agents-*` 分支固定传入 `--source instructions/codex-global.md`。
- `mcp-server/hatch_build.py` 从 `mcp-server/` 的同级目录读取 `instructions/codex-global.md`。
- 因此不要移动 `instructions/`、`skills/`、`mcp-server/`、`codex-hooks/`；移动需同步修改构建钩子、启动器和相关测试。

## 修改交付内容后的核对

1. 构建 sdist 与 wheel，解包确认两者都不含 `.agents/`，且仍包含 `skill-source/SKILL.md` 与 `global-instructions-source.md`（sdist）或 `skill_bundle/SKILL.md` 与 `global_instructions/codex-global.md`（wheel）。
2. 运行 [本地验证](verification.md) 中的离线测试；发布测试会在临时目录重建 sdist/wheel，并核对 Skill 快照、全局指令字节和安装行为。

## 单向引用规则

开发文档（本目录、根 `AGENTS.md`）可以链接交付内容；交付内容不得链接或引用 `.agents/`。Skill 构建会拒绝越出 Skill 目录的相对链接，`tests/test_skill_distribution.py` 检查发布的 Skill 与全局指令文本，`tests/test_agents_docs.py` 保证开发文档自身的相对链接和锚点可解析。
