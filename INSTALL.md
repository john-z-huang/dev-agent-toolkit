# 安装与构建

## 构建与安装发行包

确保 `uv` 位于 `PATH`，然后在仓库根目录构建发行包。`uv build` 默认先构建 sdist，再从它构建 wheel。

```bash
./dws --uv-build
```

安装 `dist/` 中与 `mcp-server/pyproject.toml` 当前版本匹配的 wheel。缺少该产物时，先运行上面的构建命令。

```bash
./dws --uv-tool-install
```

## 独立安装 Skill

仓库可以位于任意开发目录。Skill 的唯一指令源在 [`skills/dev-workflow-standards/`](skills/dev-workflow-standards/)，构建时封装进发布包，安装后为普通文件快照，不引用开发仓库。

先[安装完整发行包](#构建与安装发行包)，再执行以下命令。

```bash
"$(uv tool dir --bin)/dev-workflow-standards" skills install --dry-run
"$(uv tool dir --bin)/dev-workflow-standards" skills install
"$(uv tool dir --bin)/dev-workflow-standards" skills show
```

Skill 的安装、更新和查看均使用上述显式入口，定位到 `uv tool` 安装的完整发行包，避免裸命令被 `PATH` 中的其他同名入口、别名或命令缓存影响。路径外的双引号用于保留目录中的空格。

默认目标为 `~/.agents/skills/dev-workflow-standards-skill`；`--target` 可指定仓库外的独立目标目录。旧项目路径 `~/.agents/skills/dev-workflow-standards` 及会覆盖它的目标受到保护，即使显式指定或已有受管清单也不能作为安装/更新目标；指向同一位置的链接不能绕过保护。首次安装仍拒绝所有已有目标，不会自动迁移、覆盖或删除旧项目。`~/.codex/skills` 不作为默认自定义安装位置，显式选择兼容路径时也执行同样的保护检查。

源码或文档变更后，在仓库根目录重新构建并安装 wheel，再显式更新已安装指令；安装软件包本身不会更新 Skill 快照：

```bash
./dws --uv-build
./dws --uv-tool-install --force
"$(uv tool dir --bin)/dev-workflow-standards" skills update --dry-run
"$(uv tool dir --bin)/dev-workflow-standards" skills update
```

显式目标安装的，查看和更新也要传同一 `--target`。更新只接受本工具管理且未修改的完整安装；用户修改、额外内容、链接或特殊文件都会阻止覆盖。macOS/Linux 通过原子目录发布保全原安装，不支持的文件系统/平台不降级执行。预览不写文件，独立 Skill 安装离线且不注册 MCP、不读取 OpenAI 凭据、不安装 Hook。旧版共存、中断残留和人工迁移边界见 [完整安装说明](skills/dev-workflow-standards/references/installation.md)。

`dev-workflow-standards` 是独立管理入口；原 `dev-workflow-standards-tools` 仍直接启动 stdio MCP。需要 MCP 功能时，按 [Codex](#codex-中安装) 或 [Pi Code Agent](#给-pi-code-agent-注册-mcp) 的说明注册服务。

## 版本管理与更新全局 AGENTS.md

全局指令的唯一源文件是 [`instructions/codex-global.md`](instructions/codex-global.md)，与仓库根目录的项目 `AGENTS.md` 分开维护。模板可使用 `{{HOME}}` 引用当前用户的绝对主目录。全局指令可以独立于 Skill 安装和更新。

从仓库源文件预览并更新时，先按上文构建并安装包含本次修改的完整 wheel，再在仓库根目录执行：

```bash
"$(uv tool dir --bin)/dev-workflow-standards" agents show --source ./instructions/codex-global.md
"$(uv tool dir --bin)/dev-workflow-standards" agents update --source ./instructions/codex-global.md --dry-run
"$(uv tool dir --bin)/dev-workflow-standards" agents update --source ./instructions/codex-global.md --adopt
```

目标固定为当前用户的 `~/.codex/AGENTS.md`。首次接管已有文件须显式传入 `--adopt`；内容相同时只建立受管记录，不重写目标或创建备份，后续正常更新不需要该参数。不传 `--source` 时使用已安装发布包内的指令源，脱离开发仓库也能运行。`show` 返回状态和内容指纹，`--dry-run` 返回差异、冲突和预计备份名；两者均不创建目录、备份、锁文件或受管记录。管理命令会校验模板中实际使用的占位符和本地绝对链接。

每次实际更新或覆盖已有目标前，默认将原文件逐字节备份到 `~/.codex/AGENTS_BAK_<秒级时间戳>.md`，其中时间戳为 Unix 秒数。备份失败或同一秒的备份名称已存在时停止，不覆盖旧备份、不增加后缀。目标不存在或内容相同时不创建备份。受管文件有本地修改时默认拒绝更新，审阅差异后可显式使用 `--replace-local`，仍须先备份。备份不会自动清理；需要恢复时先保留当前内容，再人工选择对应备份恢复。

更新使用同目录临时文件原子替换目标，通过 `~/.codex/.AGENTS.md.global-agents.lock` 合作进程锁避免两个 CLI 同时更新，并以 `~/.codex/.AGENTS.md.dev-workflow-standards.json` 记录受管指纹。锁文件会保留以维持锁身份，不应在更新进程运行时删除。锁不阻止外部编辑器写入；更新期间应暂停其他写入者。目标与受管记录不能作为一个原子事务提交，发生中断或记录写入失败时应核对目标、受管记录和备份，不将失败视为成功。工具拒绝符号链接、硬链接和特殊文件，不修改其他 Codex 配置。

安装软件包、更新 Skill 和更新全局指令是三个显式动作。更新全局指令不会注册 MCP 或启用 Hook，也不宣称当前运行会话已加载新规则；后续会话应使用更新后的指令。

## Codex 中安装

本仓库的 [安装更新入口](dws) 支持独立构建、uv tool 安装，以及 MCP、Skill、全局 `AGENTS.md` 和 Hooks 管理。在仓库根目录无参数执行时，仅打印使用帮助并返回 `0`，不安装软件、不注册 MCP，也不写入配置或指令文件：

```bash
./dws
# 等价的显式帮助命令
./dws --help
```

`--uv-build` 把 `mcp-server/` 的发行产物写到仓库的 `dist/`。`--uv-tool-install` 默认安装当前版本的 wheel，重装时加 `--force`。需要指定其他 wheel 或传递更多 uv 选项时，使用 `--uv-tool-install [uv 选项] <wheel 路径>`。显式指定的相对路径以调用目录为准。这两个操作独立于 MCP 注册和指令更新，使用各自的 `--help` 查看 uv 选项。

安装 MCP Server、注册服务并配置环境变量转发：

```bash
./dws --mcp-install
```

脚本从自身位置定位 `mcp-server/`，不依赖调用时的工作目录。它默认处理 `dev-workflow-standards-tools`，将 `OPENAI_API_KEY`、`OPENAI_BASE_URL` 及 `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY`、`NO_PROXY` 的大写、小写名称合并到该服务的 `env_vars`。只有变量名会写入配置，脚本不读取或打印配置值，不发起 OpenAI 请求。

入口参考 Homebrew 的 Gradle/Maven 命令脚本：Bash 根据显式操作参数选择入口，通过 `exec` 启动对应程序并保留退出状态。MCP 操作调用项目内的 `scripts/setup-codex-mcp.py` 实现；Skill 和全局指令操作通过 `uv tool dir --bin` 定位已安装的完整发行包入口，额外选项原样转发。支持本机 Bash 3.2；从其他工作目录调用时使用该入口的绝对路径。需要 `uv` 位于 `PATH`，MCP 和 Hooks 安装脚本的 Python 版本与依赖由各自 PEP 723 声明管理；Hooks 作为独立 uv tool 安装。根目录入口与对应源码组件必须保持仓库中的相对路径，不单独复制入口或通过异目录符号链接调用。原 Python 命令仍兼容。

安装和更新按资源使用独立参数；操作参数必须放在首位，每次只选择一种资源：

| 安装参数 | 更新参数 | 范围 |
| --- | --- | --- |
| `--mcp-install` | `--mcp-update` | 安装或更新软件包，注册 MCP 并配置变量转发；不更新 Skill 或全局指令。 |
| `--skills-install` | `--skills-update` | 从已安装完整发行包复制或更新 Skill；不安装软件包、不注册 MCP。 |
| `--agents-install` | `--agents-update` | 创建或更新全局 `AGENTS.md`；不安装软件包、不注册 MCP。 |
| `--hooks-install` | `--hooks-update` | 从源码安装或更新项目级或用户全局 Codex Hooks；不修改宿主信任。 |

```bash
./dws --skills-install
./dws --skills-update --dry-run
./dws --agents-install --dry-run
./dws --agents-update --dry-run
```

Skill 选项包括 `--target`、`--dry-run`；全局指令选项包括 `--source`、`--dry-run`、`--adopt`、`--replace-local`。`--agents-install` 和 `--agents-update` 均复用管理 CLI 的 `agents update`：目标不存在时创建，已有未知文件仍需显式 `--adopt`，不会绕过备份或本地修改保护。资源操作使用已安装包内的内容；需要最新源码时，先独立更新完整发行包。各操作后加 `--help` 查看选项；原 MCP 参数 `--install`、`--install --force`、`--env-only` 仍兼容。

更新已有安装：

```bash
./dws --mcp-update
```

可先预览安装和配置计划；`--mcp-install --dry-run` 不运行安装或注册命令，也不读写配置：

```bash
./dws --mcp-install --dry-run
```

如果已经[安装 uv tool](#构建与安装发行包)，可显式传入 `--server dev-workflow-standards-tools` 完成注册和转发配置；如果服务也已经注册，只需修复转发声明：

```bash
# 仅注册已有安装并补齐转发配置
./dws --server dev-workflow-standards-tools
# 仅修复已注册服务的转发声明
./dws --env-only
```

`--env-only` 不安装软件、不调用 Codex CLI，也不会创建缺失的服务条目；其 `--dry-run` 会读取并验证配置，但不写入。重复运行时只追加缺失的名称；已经完整配置时，文件内容和修改时间保持不变。已有转发变量名、服务启动参数、审批设置及其他配置会保留。

常用选项：

| 选项 | 行为 |
| --- | --- |
| `--mcp-install` | 安装本仓库的 uv tool，然后注册服务并补齐 `env_vars`。 |
| `--mcp-update` | 更新已有 uv tool 安装，再完成注册和转发配置。 |
| `--env-only` | 仅修复已有服务的转发声明。 |
| `--server NAME` | 指定服务注册名；默认是 `dev-workflow-standards-tools`。 |
| `--config PATH` | 选择配置文件；注册模式要求文件名为 `config.toml`，并让 Codex CLI 使用同一目录；仅修复模式可指定其他文件名。 |
| `--executable PATH` | 注册已有安装时显式指定可执行文件绝对路径。 |
| `--replace` | 明确允许替换冲突的注册；已有匹配注册直接复用。 |
| `--dry-run` | 预览，不执行写入。 |

配置文件默认是 `$CODEX_HOME/config.toml`，未设置 `CODEX_HOME` 时使用 `~/.codex/config.toml`。写入前验证 TOML 和目标服务，通过同目录临时文件替换，并检测读取后发生的文件变化。无效配置、符号链接或特殊文件、所需变量的远端来源冲突，以及会导致无关排版被重新整理的文档，都会被拒绝；已经完整的仅修复操作保持无改动。发现并发修改时应先核对当前文件，避免其他客户端同时写入。

替换 stdio 注册时会保留原附加设置和转发变量，只更新入口、参数及预期启用状态；HTTP 转为 stdio 时保留通用工具策略和超时设置，不复制旧传输或认证字段。安装、注册、转发配置是不同阶段，后续失败不代表前面的操作已回滚；脚本会给出安全的阶段提示，不输出捕获的子进程内容或配置值。

审批策略仍由用户选择；脚本不覆盖已有策略。如需对未标记为只读的工具启用 Codex 写入确认，可在对应服务段落中设置：

```toml
default_tools_approval_mode = "writes"
```

`env_vars` 允许 Codex 将自身环境中的变量转发给 MCP 子进程。调用工具的终端能读取变量，不代表 Codex 启动的 MCP 进程也能读取；Codex 主进程本身也必须持有这两个非空变量。该设置不会从 Shell 配置文件或 `.env` 文件加载变量。配置含义见 [Codex MCP 官方说明](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)。

`writes` 会要求 Codex 确认未标记为只读的工具。Skill 的用户授权规则仍然适用；MCP 注解和 Codex 确认都不能替代任务语境中的授权。Codex 桌面端、CLI 和 IDE 共享该配置。修改配置后，重新加载 MCP 服务；若客户端未提供重载入口，退出后重新打开客户端，确保重新创建服务进程。已有 MCP 进程不会自动获得新配置或环境变量。

安装为普通本机 uv tool 后，工具从本机安装位置运行，不依赖仓库 worktree 路径。注册已有时，可用 `--uv-build` 和 `--uv-tool-install --force` 更新软件包，再按需要分别运行 `--skills-update`、`--agents-update`。同时需要管理 MCP 注册和变量转发时，使用 `./dws --mcp-update`。

## 安装与更新原生 Codex Hooks

使用 `./dws --hooks-install` 或 `--hooks-update`，选择 `--global` 或显式 `--project-root`；独立于 Skill/MCP 安装，不覆盖未知或本地修改的 hooks，不自动授予信任或后续操作权限。

```bash
./dws --hooks-install --project-root /absolute/path/to/target-project --dry-run
./dws --hooks-update --project-root /absolute/path/to/target-project --dry-run
./dws --hooks-install --global --dry-run
./dws --hooks-update --global --dry-run
./dws --hooks-install --global --merge --dry-run  # 已有其他 Hooks 配置时显式合并
```

Hooks 操作先通过 `uv tool` 安装或重装独立的 `dev-workflow-standards-hooks` 包，再使用已安装入口的 `configure` 子命令注册到 `hooks.json`。配置中的命令为该 CLI 的绝对路径，不依赖源码或项目 `.venv`。必须二选一：`--project-root` 指定已有绝对项目目录，或 `--global` 选择用户全局目录（默认 `~/.codex`；显式 `CODEX_HOME` 必须是已有绝对目录）。Hooks 操作的 `--dry-run` 只显示安装和注册计划，不执行安装、目标校验或写入；需精确预览合并配置时，在包安装后使用 `"$(uv tool dir --bin)/dev-workflow-standards-hooks" configure --global --install --merge --dry-run`。更新拒绝本地修改，并可迁移校验通过的旧版受管脚本注册；旧脚本保留但不再调用。详见 [Hooks 安装与更新](codex-hooks/README.md#安装注册与更新)。

## 给 Pi Code Agent 注册 MCP

Skill 与 MCP 元数据均区分宿主能力：Pi 不要求不存在的 Codex writes approval，仍须用户授权及实际权限检查；codemode 模式先发现工具和读取完整服务指令。环境继承与 `timeout`（秒）按 Pi 配置，不能照搬 Codex 字段。Codex Hooks、全局指令更新器和会话来源协议仍为专属能力；不伪造 Pi 会话为 Codex 来源。详见 [Skill 兼容规则](skills/dev-workflow-standards/SKILL.md#宿主审批兼容) 和 [Pi 环境与时限](skills/dev-workflow-standards/references/openai-workflow-tools.md#pi-stdio-环境传递与工具时限)。

使用支持原生 `pi mcp add` 的 pi（本机参考版本 1.5.0），通过独立脚本注册 `uv tool` 安装的 stdio 服务：

```bash
# 默认只注册已安装的本仓库服务
uv run scripts/setup-pi-mcp.py

# 从当前仓库安装并注册；更新时增加 --force
uv run scripts/setup-pi-mcp.py --install
uv run scripts/setup-pi-mcp.py --install --force

# 无命令执行、无配置读写的预览
uv run scripts/setup-pi-mcp.py --install --dry-run

# 注册到调用时所在项目（而非脚本所在仓库）
uv run scripts/setup-pi-mcp.py --local --exposure deferred

# 注册其他已经通过 uv tool 安装、无需启动参数的 stdio MCP
uv run scripts/setup-pi-mcp.py --server example --command example-mcp
```

脚本通过 `uv tool dir --bin` 定位可执行文件，将绝对入口路径交给 `pi mcp add`，不会使用 PATH 中的同名 MCP 命令。`--install` 仅安装本仓库 `mcp-server/`，从其他目录调用时用脚本绝对路径；`--force` 必须与 `--install` 同用。默认 exposure 为 `codemode`，还支持 `deferred`、`direct`、`hidden`。

需要 `uv`、`pi` 位于 PATH。默认写用户级 `~/.pi/agent/mcp.json`；`--local` 写当前目录 `.pi/mcp.json`，项目配置仅在 pi 信任该项目后加载。**`pi mcp add` 会替换同名服务条目，包括其自定义环境、超时和工具暴露等设置**；其他服务由 pi 自身保留。需要保留同名自定义配置时，请先手动备份或使用不同 `--server` 名称。

stdio 服务继承 pi 进程的环境；脚本不读取、打印或持久化凭据，也不加载 `.env`。调用 OpenAI 的工具仍要求启动 pi 时持有非空 `OPENAI_API_KEY`、`OPENAI_BASE_URL`；可选代理变量同样通过进程环境继承，不写可能因缺失而插值失败的引用。安装可能联网，注册本身不启动 MCP、不调用 OpenAI、不修改 Codex/Skill/Hooks。

脚本成功只表示注册命令成功，不代表服务连接或工具测试通过。按需运行 `pi mcp list`（会连接所有已启用服务）验证状态，并在已有 pi 会话执行 `/reload`。安装和注册不是事务；后续失败不回滚已安装的 uv tool，错误输出不会回显子进程原文。若使用替代原生 MCP 的扩展，需先确认其配置方式，本脚本不配置这类扩展。

## 从旧名称迁移

如果旧版本已安装并注册了 `dev-workflow-standards-mcp`，先移除旧 Codex 注册和 uv tool，再按 [Codex 中安装](#codex-中安装)的步骤安装并注册新名称。只对本机确实存在的旧条目执行移除命令：

```bash
codex mcp remove dev-workflow-standards-mcp
uv tool uninstall dev-workflow-standards-mcp
```

此迁移说明只描述命令；不会自动修改本机 Codex 配置或安装。

## 安装排查

### 发布包缺少 Skill 资源

项目 `uv run` 使用可编辑开发环境时会导入源码包，Skill 资源定位可能落在没有封装资源的源码目录。Skill 管理命令应使用 `"$(uv tool dir --bin)/dev-workflow-standards"` 明确选择从完整 wheel 安装的工具。若出现“发布包缺少 Skill 资源”，先按 [命令入口排查](skills/dev-workflow-standards/references/installation.md#包资源缺失与命令入口排查) 核对实际入口；资源缺失时安装器会拒绝执行，不从源码目录回退读取。

### Codex 缺少 OpenAI 环境变量

若手动运行成功，但 Codex 调用返回 `missing_api_key`，先检查[Codex 的 `env_vars` 转发配置](#codex-中安装)、Codex 主进程的变量存在性，以及服务是否已重新加载。uv tool 安装提供独立的执行环境，不会替 MCP 客户端补齐凭据。`missing_api_key` 表示服务进程中的 Key 缺失或为空，请求尚未发送；Key 检查先于 Base URL，因此两项都缺失时也只返回 `missing_api_key`。Key 存在而 Base URL 缺失时返回 `missing_base_url`。排查时只检查存在性和非空状态，不输出配置值；不要通过给服务增加凭据文件回退来绕过环境要求。
