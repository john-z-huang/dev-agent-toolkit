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

## 使用

这是独立的源码分发组件，不随仅含 Markdown 的 Skill 快照或 MCP wheel 安装。运行时只依赖 Python 3.11+ 标准库和 Git。先按项目环境规则准备一个长期有效的 Python 解释器，再从本仓库运行，例如使用已有 MCP 项目虚拟环境：

```bash
uv run --project mcp-server -- python scripts/setup-codex-hooks.py \
  --project-root /absolute/path/to/target-project
```

默认仅输出配置预览，不写文件。确认目标后加 `--install`，会独占创建目标项目的 `.codex/hooks.json` 和 `.codex/hooks/dev_workflow.py`。`--python /absolute/path/to/python` 可指定运行 Hook 的已有解释器；默认使用安装命令实际选中的解释器。命令与脚本均使用经过 Shell 引用的绝对路径，从子目录启动也可使用。当前生成的命令面向 macOS/Linux POSIX Shell。

安装不覆盖、合并或删除已有资源，不修改 `config.toml`、全局配置、Git 配置、Skill、MCP 注册或信任状态。失败可能留下已创建的脚本，请检查实际文件后处理；不要盲重试。如果已有 hooks，请先审阅输出，手工整合事件配置和脚本。安装后不依赖源码 checkout，但解释器必须保留；更新需审阅后替换已安装快照。

新建或恢复会话后，在 Codex `/hooks` 中审阅并信任当前定义，再确认事件触发。已有内联、用户或插件 hooks 会累积运行，安装前要检查重复策略。宿主禁用 hooks、managed-only 限制或未信任时，本配置不会执行。这里的安装命令不会自动启用被禁用的功能。

## 协议与边界

- 输入为 stdin 单个 JSON 对象；输出为 stdout 单个事件结果。明确违反路径规则返回 `PreToolUse.permissionDecision=deny`，不会返回 `allow` 或改写参数，更不会处理 `PermissionRequest` 自动批准。
- 匹配默认注册名 `mcp__dev-workflow-standards-tools__*` 及规范化名称 `mcp__dev_workflow_standards_tools__*`，校验该服务的显式路径。缺失或 null 字段是否合法仍由对应工具 Schema 校验；不把 cwd 填入缺失字段。其他服务不套用本项目的输入约定。服务改名时需同步 matcher 和运行时前缀。
- 路径检查使用固定只读 `git rev-parse --show-toplevel`，关闭可选 index 锁，移除继承的 `GIT_*` 覆盖，支持其他目标仓库、符号链接路径和 linked worktree；并不证明目标得到用户授权。
- 失败识别仅覆盖对象的 `isError=true`、`ok=false`、非零整数 `exit_code`，以及 `structuredContent.ok=false`。不解析不稳定的日志、文本化 MCP JSON 或运行中进程；识别不到不表示通过。原工具返回仍供 Agent 判断。
- 不联网、不调用 OpenAI、不读取会话/凭据、不写 Memory、不执行 Git 写入。运行时不写文件；安装器只写显式目标的两个文件。不自动跑测试、安装依赖、暂存或发布。
- Hook 超时、异常或无效输出可能让调用继续；特殊工具路径也可能不触发 hooks。本组件是辅助防线，不能替代 MCP、Git hooks、宿主审批和统一 API 客户端约束。

## 验证

```bash
uv run --project mcp-server -- python -m unittest discover -s tests -p 'test_codex_hooks.py'
```

测试使用合成事件、临时仓库和临时安装目录，包含真实 stdin/stdout、拒绝协议、根目录/子目录/linked worktree、失败分类、无凭据回显、路径含空格和引号、从其他 cwd 执行、拒绝覆盖及符号链接保护。测试不代表当前会话已重新加载或信任配置；真实宿主发现与触发需在安装后另行核对。
