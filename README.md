# dev-workflow-standards

此项目将开发规范拆为两层：Skill 文档以声明式 Hooks 描述动作的进入、执行、离开和重查条件，由 Agent 自行规划顺序；本地 MCP 服务执行固定 Git/GitHub 操作，并提供只读的 Codex 会话事实辅助工具。当前维护的本地 MCP 服务为 Python 实现，由 `uv` 管理，并通过 `uv tool` 安装到本机供 Codex 使用。

领域规则判断与开发文案生成通过 OpenAI Python SDK 完成：判断使用 Decisions API，生成使用 Responses API。所有请求固定为 `gpt-6-luna`，强制在调用时读取 `OPENAI_API_KEY` 和 `OPENAI_BASE_URL`；缺少任意配置即拒绝请求，不使用默认凭据、默认地址或其他模型。Decisions 使用接口自身机制，生成按任务复杂度显式指定推理强度，默认 `medium`。

`check_api_input` 默认允许向配置的审核服务发起外部 API 调用，无需前置审核、自我审核或逐次人工授权；它自身的本地敏感输入检测和配置检查仍先运行。当前任务所需项目内容通过完整输入审核后，允许向既定配置服务外发，无需重复确认。该规则同样适用于使用此入口的其他 MCP Server，不扩大 Git、Memory 或外部发布权限；用户明确禁止外发及更高优先级限制仍生效。完整协议及失败处理见 [API 输入审核](skills/dev-workflow-standards/references/api-input-review.md)。

统一客户端为每次调用显式注入 `httpx2.AsyncClient(trust_env=True)`，读取服务进程的 `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY`、`NO_PROXY`（支持小写形式）。配置适用代理且目标未命中 `NO_PROXY` 时，请求通过代理；未配置代理时按库默认直连。代理配置或连接失败会返回安全错误，不回退直连。代理地址和认证信息不应写入仓库或日志。

## 独立安装 Skill

仓库可以位于任意开发目录。Skill 的唯一指令源在 [`skills/dev-workflow-standards/`](skills/dev-workflow-standards/)，构建时封装进发布包，安装后为普通文件快照，不引用开发仓库。

以下构建、安装和更新命令均在本仓库根目录执行。先构建 wheel 和 sdist（默认先构建 sdist，再从它构建 wheel）：

```text
uv build ./mcp-server --out-dir ./dist
```

从 `./dist/` 安装构建产物；以下示例对应当前版本 `0.2.0`，版本变更时使用该目录中实际生成的 wheel 文件名。本项目不假定已有公开包索引。

```bash
uv tool install ./dist/dev_workflow_standards_tools-0.2.0-py3-none-any.whl
"$(uv tool dir --bin)/dev-workflow-standards" skills install --dry-run
"$(uv tool dir --bin)/dev-workflow-standards" skills install
"$(uv tool dir --bin)/dev-workflow-standards" skills show
```

Skill 的安装、更新和查看均使用上述显式入口，定位到 `uv tool` 安装的完整发行包，避免裸命令被 `PATH` 中的其他同名入口、别名或命令缓存影响。路径外的双引号用于保留目录中的空格。

默认目标为 `~/.agents/skills/dev-workflow-standards-skill`；`--target` 可指定仓库外的独立目标目录。旧项目路径 `~/.agents/skills/dev-workflow-standards` 及会覆盖它的目标受到保护，即使显式指定或已有受管清单也不能作为安装/更新目标；指向同一位置的链接不能绕过保护。首次安装仍拒绝所有已有目标，不会自动迁移、覆盖或删除旧项目。`~/.codex/skills` 不作为默认自定义安装位置，显式选择兼容路径时也执行同样的保护检查。

源码或文档变更后，在仓库根目录重新构建并安装 wheel，再显式更新已安装指令；安装软件包本身不会更新 Skill 快照：

```bash
uv build ./mcp-server --out-dir ./dist
uv tool install --force ./dist/dev_workflow_standards_tools-0.2.0-py3-none-any.whl
"$(uv tool dir --bin)/dev-workflow-standards" skills update --dry-run
"$(uv tool dir --bin)/dev-workflow-standards" skills update
```

显式目标安装的，查看和更新也要传同一 `--target`。更新只接受本工具管理且未修改的完整安装；用户修改、额外内容、链接或特殊文件都会阻止覆盖。macOS/Linux 通过原子目录发布保全原安装，不支持的文件系统/平台不降级执行。预览不写文件，独立 Skill 安装离线且不注册 MCP、不读取 OpenAI 凭据、不安装 Hook。旧版共存、中断残留和人工迁移边界见 [完整安装说明](skills/dev-workflow-standards/references/installation.md)。

`dev-workflow-standards` 是独立管理入口；原 `dev-workflow-standards-tools` 仍直接启动 stdio MCP。安装 Skill 后，需要 MCP 功能的仍须按下一节注册服务。

## 版本管理与更新全局 AGENTS.md

全局指令的唯一源文件是 [`instructions/codex-global.md`](instructions/codex-global.md)，与仓库根目录的项目 `AGENTS.md` 分开维护。源文件中的 `{{HOME}}` 在更新时替换为当前用户的绝对主目录；不写入维护者的个人用户名。当前基线保留既有全局规则，仅修正为当前已安装 Skill 的入口和文档路径。规则变更应单独审阅。

从仓库源文件预览并更新时，先按上文构建并安装包含本次修改的完整 wheel，再在仓库根目录执行：

```bash
"$(uv tool dir --bin)/dev-workflow-standards" agents show --source ./instructions/codex-global.md
"$(uv tool dir --bin)/dev-workflow-standards" agents update --source ./instructions/codex-global.md --dry-run
"$(uv tool dir --bin)/dev-workflow-standards" agents update --source ./instructions/codex-global.md --adopt
```

目标固定为当前用户的 `~/.codex/AGENTS.md`。首次接管已有文件须显式传入 `--adopt`；内容相同时只建立受管记录，不重写目标或创建备份，后续正常更新不需要该参数。不传 `--source` 时使用已安装发布包内的指令源，脱离开发仓库也能运行。`show` 返回状态和内容指纹，`--dry-run` 返回差异、冲突和预计备份名；两者均不创建目录、备份、锁文件或受管记录。正式更新前检查模板占位符及所引用的 Skill/文档；缺少依赖则停止，不自动安装或迁移 Skill。

每次实际更新或覆盖已有目标前，默认将原文件逐字节备份到 `~/.codex/AGENTS_BAK_<秒级时间戳>.md`，其中时间戳为 Unix 秒数。备份失败或同一秒的备份名称已存在时停止，不覆盖旧备份、不增加后缀。目标不存在或内容相同时不创建备份。受管文件有本地修改时默认拒绝更新，审阅差异后可显式使用 `--replace-local`，仍须先备份。备份不会自动清理；需要恢复时先保留当前内容，再人工选择对应备份恢复。

更新使用同目录临时文件原子替换目标，通过 `~/.codex/.AGENTS.md.global-agents.lock` 合作进程锁避免两个 CLI 同时更新，并以 `~/.codex/.AGENTS.md.dev-workflow-standards.json` 记录受管指纹。锁文件会保留以维持锁身份，不应在更新进程运行时删除。锁不阻止外部编辑器写入；更新期间应暂停其他写入者。目标与受管记录不能作为一个原子事务提交，发生中断或记录写入失败时应核对目标、受管记录和备份，不将失败视为成功。工具拒绝符号链接、硬链接和特殊文件，不修改其他 Codex 配置。

安装软件包、更新 Skill 和更新全局指令是三个显式动作。更新全局指令不会注册 MCP 或启用 Hook，也不宣称当前运行会话已加载新规则；后续会话应使用更新后的指令。

## Codex 中安装

本仓库的 [Codex 安装更新入口](dws) 按参数分别管理 MCP Server、Skill 和全局 `AGENTS.md`。在仓库根目录无参数执行时，仅打印使用帮助并返回 `0`，不安装软件、不注册 MCP，也不写入配置或指令文件：

```bash
./dws
# 等价的显式帮助命令
./dws --help
```

安装 MCP Server、注册服务并配置环境变量转发：

```bash
./dws --mcp-install
```

脚本从自身位置定位 `mcp-server/`，不依赖调用时的工作目录。它默认处理 `dev-workflow-standards-tools`，将 `OPENAI_API_KEY`、`OPENAI_BASE_URL` 及上述四个代理变量的大写、小写名称合并到该服务的 `env_vars`。只有变量名会写入配置，脚本不读取或打印配置值，不发起 OpenAI 请求。

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
./dws --hooks-install --project-root /absolute/path/to/target-project --dry-run
./dws --hooks-update --project-root /absolute/path/to/target-project --dry-run
./dws --hooks-install --global --dry-run
./dws --hooks-update --global --dry-run
./dws --hooks-install --global --merge --dry-run  # 已有其他 Hooks 配置时显式合并
```

Hooks 操作先通过 `uv tool` 安装或重装独立的 `dev-workflow-standards-hooks` 包，再使用已安装入口的 `configure` 子命令注册到 `hooks.json`。配置中的命令为该 CLI 的绝对路径，不依赖源码或项目 `.venv`。必须二选一：`--project-root` 指定已有绝对项目目录，或 `--global` 选择用户全局目录（默认 `~/.codex`；显式 `CODEX_HOME` 必须是已有绝对目录）。`dws --dry-run` 只显示安装和注册计划，不执行安装、目标校验或写入；需精确预览合并配置时，在包安装后使用 `"$(uv tool dir --bin)/dev-workflow-standards-hooks" configure --global --install --merge --dry-run`。更新拒绝本地修改，并可迁移校验通过的旧版受管脚本注册；旧脚本保留但不再调用。详见 [Hooks 安装与更新](codex-hooks/README.md#安装注册与更新)。

Skill 选项包括 `--target`、`--dry-run`；全局指令选项包括 `--source`、`--dry-run`、`--adopt`、`--replace-local`。`--agents-install` 和 `--agents-update` 均复用管理 CLI 的 `agents update`：目标不存在时创建，已有未知文件仍需显式 `--adopt`，不会绕过备份或本地修改保护。资源操作使用已安装包内的内容；需要最新源码时，先独立更新完整发行包。各操作后加 `--help` 查看选项；原 MCP 参数 `--install`、`--install --force`、`--env-only` 仍兼容。

更新已有安装：

```bash
./dws --mcp-update
```

可先预览安装和配置计划；`--mcp-install --dry-run` 不运行安装或注册命令，也不读写配置：

```bash
./dws --mcp-install --dry-run
```

如果已经通过 `uv tool install ./mcp-server` 安装，可显式传入 `--server dev-workflow-standards-tools` 完成注册和转发配置；如果服务也已经注册，只需修复转发声明：

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

安装为普通本机 uv tool 后，工具从本机安装位置运行，不依赖仓库 worktree 路径。更新本地源码后，可运行 `./dws --mcp-update` 更新软件包和 MCP 注册，再按需要分别运行 `--skills-update`、`--agents-update` 更新已安装指令。单独运行 `uv tool install` 不会自动配置 Codex；需要安装并注册 MCP 时，使用上述脚本的 MCP 操作参数。

### 给 pi code agent 注册 MCP

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

### 从旧名称迁移

如果旧版本已安装并注册了 `dev-workflow-standards-mcp`，先移除旧 Codex 注册和 uv tool，再按上面的步骤安装并注册新名称。只对本机确实存在的旧条目执行移除命令：

```bash
codex mcp remove dev-workflow-standards-mcp
uv tool uninstall dev-workflow-standards-mcp
```

此迁移说明只描述命令；不会自动修改本机 Codex 配置或安装。

## 使用

可选的 [原生 Codex Hooks](codex-hooks/README.md) 将部分指令合同转换为实际宿主回调：会话与交付提示、MCP 目标仓库路径硬校验，以及结构化失败后的恢复提示。使用 `./dws --hooks-install` 或 `--hooks-update`，选择 `--global` 或显式 `--project-root`；独立于 Skill/MCP 安装，不覆盖未知或本地修改的 hooks，不自动授予信任或后续操作权限。

使用 [`SKILL.md`](skills/dev-workflow-standards/SKILL.md) 时按 [`Hook 索引`](skills/dev-workflow-standards/hooks/index.md) 读取当前动作适用的合同，由 Agent 判断操作组合；按 [`references/mcp-tools.md`](skills/dev-workflow-standards/references/mcp-tools.md) 调用对应工具。所有仓库操作都要传入本次目标项目的绝对 `repo_path`；服务器不会把启动时的目录当作目标仓库。

Python 执行和依赖环境任务按需读取 [`references/python-environment.md`](skills/dev-workflow-standards/references/python-environment.md)，Shell 脚本开发和验证按需读取 [`references/shell-environment.md`](skills/dev-workflow-standards/references/shell-environment.md)。独立脚本无需先进入 Git 工作流；非开发任务不增加环境规则加载步骤。

Git/GitHub 写操作必须满足对应动作的用户授权和执行层审批；已有授权在原范围内持续有效。操作优先使用能够满足需求的 MCP 工具或已授权 Connector；无对应工具、工具未暴露或功能/参数未覆盖时，Code Agent 可按 [`MCP 优先与 CLI 补充`](skills/dev-workflow-standards/references/cli-fallback.md) 自行选择相关 CLI、组合必要命令，完成查询或已授权写入，无须仅因工具缺口再问授权。动作条件、必要检查、沙箱和审批继续生效；工具/服务实际发生连接、权限、认证、网络、状态或校验失败时保留现场，不换入口绕过。服务本身仍只接受固定领域参数，不提供任意 shell、git、gh 或项目测试命令。

已在当前 checkout 开始工作、需要从当前 HEAD 原地建立工作分支时，使用 `create_repository_branch`。它支持 detached HEAD 和普通分支，保留已暂存、未暂存及未跟踪内容；只新增本地分支并改变 HEAD，不创建其他 checkout。它与切换已有分支的 `switch_repository_branch`、创建新目录的 `create_repository_worktree` 分别适用不同场景。参数、OID 并发条件、Hook 限制和失败后的回读要求见 [`MCP 工具目录`](skills/dev-workflow-standards/references/mcp-tools.md#原地创建工作分支)。

已有需求 worktree 落后实际 PR base 时，按 [`基线同步`](skills/dev-workflow-standards/references/worktree-base-sync.md) 使用 `fetch_repository_branch`、`audit_worktree_base_sync` 和对应同步工具。已发布分支 merge，未发布分支 rebase；固定并复核 head/base OID，保留冲突现场并重新验证。获取远端基线不切换其他 checkout；普通非强制推送规则继续生效。

本服务发起的 merge/rebase 冲突可按 [`受限恢复`](skills/dev-workflow-standards/references/worktree-recovery.md) 显式继续或撤销。四个专用工具要求匹配当前 worktree 的管理记录、操作 ID 与最新状态快照；不自动解决或暂存冲突，也不调用 skip，abort 还要求确认丢弃本次冲突解决内容。手工、复杂或状态不明的操作不自动接管。

只读按 [`只读查询规约`](skills/dev-workflow-standards/references/read-only-queries.md) 核对完整子命令、参数、配置和副作用：`status` 避免可选 index 写回，差异展示禁用外部 diff/textconv，`fetch` 仍属本地写入；REST 查询显式 GET，GraphQL 审阅 query/mutation；凭据、文件输出和复合步骤不自动豁免。这是 Agent 操作规范，不是新增命令解析器。用户全局 AGENTS 或已安装 Skill 仍有限制时继续遵守并报告；本仓库修改不自动更新全局规则或重载已安装服务。

### MCP 客户端可见的使用说明

服务初始化指令说明工具分组、选择依据、通用前置条件和真实数据依赖；工具发现返回的描述说明各工具的用途、边界、执行条件、结果含义及失败后的处理。参数 Schema 同时提供顶层参数和嵌套字段的说明，复杂输入附有合成示例。Code Agent 应先依据这些元数据选择工具，再按参数要求提供事实，无需先自行完成工具承担的判断或内容生成。

维护服务或工具时，必须同步更新客户端可见的说明，不能只改本文件。尤其要区分只读与离线、本地校验与 API 建议、候选内容与已执行操作，以及操作失败与部分副作用。初始化和工具发现检查应验证说明、输入约束和工具注解与实现一致；说明不得改变已有参数类型、默认值或校验规则。

### Codex 会话事实辅助工具

- `get_codex_session_summary_guidance`：获取默认阅读问题与完整摘要模板；可传自定义问题或模板，以用户明确要求为准。
- `order_codex_session_sources`：按 thread ID 去重，按明确的会话创建时间排序；元数据冲突、缺失或时间相同时提示需要澄清。
- `prepare_codex_session_memory`：校验来源、项目路径与 Memory 名称，生成 Serena 写入参数；不读取原会话、不写入文件或 Memory。

原会话通过宿主的 `read_thread` 工具读取，实际保存仍通过 Serena 的项目激活、Memory 读取、写入与回读完成。这些辅助工具只能校验结构，不能证明摘要忠实于原文，也不能授予持久化权限。工具签名见 [`references/mcp-tools.md`](skills/dev-workflow-standards/references/mcp-tools.md)，事实来源和更新边界见 [`references/codex-session-facts.md`](skills/dev-workflow-standards/references/codex-session-facts.md)。

### API 判断与生成工具

- `check_api_input`：通用外发内容预检，请求仅包含 `purpose` 和 `content` 两个必填非空字符串；先在本地检测凭据、登录令牌、不透明载荷及输入限制，再调用 Decisions 审核。不检查文件或目录路径；自动出站审核采用同一规则。其他 MCP Server 可按相同协议使用，无需指定目标工具或仓库。
- `decide_codex_session_action`：判断查询历史、查询项目、澄清/阻塞，以及摘要创建、更新或跳过的分支。
- `generate_skill_content`：根据证据、查询重点和用户格式生成 Issue、PR、提交信息、计划、交接或历史会话摘要候选内容。

MCP 的分支名、提交信息和 Issue/PR 策略检查在本地硬校验通过后调用 Decisions；API 失败不能返回通过。原始本地校验服务、Hook、Git 写工具的前置检查及不联网的会话辅助工具保持确定性执行。API 工具不执行生成内容里的命令，不自动创建 Issue/PR 或保存 Memory。

MCP 进程必须能继承上述两个 OpenAI 环境变量；需要代理时还须继承对应代理变量，配置后重新加载服务。不要把真实值写入仓库。API 只接收调用者显式提交的必要事实，不自动发送整个仓库或会话。输入字段、Prompt 边界、返回结果与推理强度配置见 [`references/openai-workflow-tools.md`](skills/dev-workflow-standards/references/openai-workflow-tools.md)。

项目事实可在用户已经授权的任务、数据及目的地范围内用于这些 API 工具，不必对同一范围逐次重复授权。公开预检只审核给定内容；本服务仍在实际业务出站前强制检查最终请求，覆盖初次生成和后续质量审查，内容变化后重新检查。审核通过不扩大权限，也不保证宿主审批结果。输入协议、失败处理及其他服务的接入责任见 [`API 输入审核`](skills/dev-workflow-standards/references/api-input-review.md)。

若手动运行成功，但 Codex 调用返回 `missing_api_key`，先检查上面的 `env_vars` 转发配置、Codex 主进程的变量存在性，以及服务是否已重新加载。uv tool 安装提供独立的执行环境，不会替 MCP 客户端补齐凭据。`missing_api_key` 表示服务进程中的 Key 缺失或为空，请求尚未发送；Key 检查先于 Base URL，因此两项都缺失时也只返回 `missing_api_key`。Key 存在而 Base URL 缺失时返回 `missing_base_url`。排查时只检查存在性和非空状态，不输出配置值；不要通过给服务增加凭据文件回退来绕过环境要求。

## 项目结构

- `skills/dev-workflow-standards/SKILL.md`：唯一 Skill 入口、共用边界及按需条件索引。
- `skills/dev-workflow-standards/hooks/`：独立动作的进入、执行、离开及重新核验条件。
- `skills/dev-workflow-standards/references/`：按需加载的决策细节、独立安装说明和 MCP 工具映射。
- `mcp-server/`：Python/uv MCP v2 stdio 服务和固定操作工具。
- `instructions/codex-global.md`：版本化的全局指令源；通过独立 CLI 显式同步到用户目录。
- `archive/mcp-server-ts/`：已归档且不再支持的历史 TypeScript MCP 实现；其历史说明见该目录的 [`README.md`](archive/mcp-server-ts/README.md)。
- `scripts/`：Codex 安装配置脚本，以及供标准 Git Hook 集成使用的可移植校验资产；`.githooks/`：Hook 入口。

当前 MCP 服务实现与调用约束见 [`mcp-server/pyproject.toml`](mcp-server/pyproject.toml) 和 [`references/mcp-tools.md`](skills/dev-workflow-standards/references/mcp-tools.md)。

## 本地验证

在 `mcp-server/` 使用项目环境运行离线测试：

```text
uv sync --managed-python
uv run --managed-python -- python -m unittest discover -s ../tests -v
```

构建测试会在临时目录生成并解包 sdist、重建 wheel、安装到隔离环境后运行 CLI，不会写入现有用户 Skill 目录。

项目 `uv run` 使用可编辑开发环境时会导入源码包，Skill 资源定位可能落在没有封装资源的源码目录。Skill 管理命令应使用 `"$(uv tool dir --bin)/dev-workflow-standards"` 明确选择从完整 wheel 安装的工具。若出现“发布包缺少 Skill 资源”，先按 [命令入口排查](skills/dev-workflow-standards/references/installation.md#包资源缺失与命令入口排查) 核对实际入口；资源缺失时安装器会拒绝执行，不从源码目录回退读取。

所有 OpenAI、Decisions 及输入审核 API 请求统一使用 `OPENAI_TIMEOUT_SECONDS=180.0` 秒。可选环境变量 `OPENAI_TIMEOUT_MAX_RETRIES` 配置超时后的重试次数，默认 `5`（首次加 5 次重试，最多 6 次），`0` 关闭；空值、负数或非整数在请求前失败。仅超时重试，其他错误不重试；SDK 内部重试关闭。dws 的 `env_vars` 同步该变量名，已有 MCP 进程须重新加载才能接收新配置；多阶段工具的外层时限需覆盖其请求与重试预算，见 [详细规则](skills/dev-workflow-standards/references/openai-workflow-tools.md#配置与请求边界)。

### OpenAI 官方 API 冒烟测试

`tests/openai_official_smoke.py` 使用统一的 httpx2 OpenAI 客户端发起一次最小 Responses 请求，固定 `gpt-6-luna`、`medium` 推理强度和 512 token 输出上限。只有显式传入 `--live` 才联网并产生实际 API 用量；不传参数输出 `skipped`，退出码为 2。常规离线测试只测试该入口的行为，不调用真实 API。

先在终端中配置并导出所需的 API 和代理环境变量，再从 `mcp-server/` 目录通过 Bash 运行；Bash 子进程继承当前终端已导出的配置：

```bash
bash -c 'uv run --frozen -- python ../tests/openai_official_smoke.py --live'
```

测试按原拼写读取 `OPENAI_API_KEY_OFFICAL` 和 `OPENAI_BASE_URL_OFFICAL`，任一缺失或为空就停止，不能回退到其他配置。入口只在调用期间将它们映射为统一客户端要求的 `OPENAI_API_KEY` 和 `OPENAI_BASE_URL`，之后恢复原环境；生产客户端的配置规则保持不变。代理继续读取当前进程的标准代理变量，遵循 `NO_PROXY`。

输出仅含安全 JSON 状态、固定请求模型、成功时的 token 计数或失败分类，不输出真实配置、响应正文或原始异常。请求仅在超时时按统一配置重试，不切换模型；只有完整、未拒绝、模型匹配且结构正确的响应才返回 `success` 和退出码 0，失败退出码为 1。

### Codex App Server 集成测试

测试驱动位于 `tests/codex_app_server_smoke.py`，通过 `tests/codex_app_server_client.py` 的标准库 JSON-RPC 客户端启动 `codex app-server --stdio`，完成 `initialize` / `initialized` 握手、`thread/start`、工具发现与调用；协议依据 [Codex App Server 官方文档](https://learn.chatgpt.com/docs/app-server)。项目已移除 Codex Python SDK、其捆绑 CLI 和 `codex-test` 依赖组，运行时、发布包和 Skill 均不包含该测试驱动。

需预先独立安装支持上述接口的 Codex CLI，确保 `codex` 在 PATH 中；客户端按实际绝对路径启动，不下载、不安装或自动切换 CLI。普通离线测试使用合成子进程核验通信协议，不启动真实 Codex 或发起模型请求。测试期间不读取原用户的 Codex 配置、登录文件，不修改现有 Skill 安装。

先构建 wheel，再从 `mcp-server/` 执行：

```bash
uv run --locked -- python ../tests/codex_app_server_smoke.py --wheel ../dist/dev_workflow_standards_tools-0.2.0-py3-none-any.whl
```

默认仅做 App Server 初始化、临时 MCP 注册、工具发现和直接只读工具调用，不发起模型请求。wheel 被安装到临时目录，并核对加载来源。临时 Codex 状态目录和只读测试工作区与用户配置隔离。只暴露 `get_codex_session_summary_guidance` 和 `check_api_input`；前者使用合成问题/模板，后者验证合成敏感输入在本地被拒绝，普通模式不向 MCP 转发 API 配置。

核验已更新的 `uv tool` 时，先通过其他所有适用测试，在既有授权内更新安装，再核对其实际可执行路径和版本：

```bash
uv run --locked -- python ../tests/codex_app_server_smoke.py \
  --installed-executable /absolute/path/to/dev-workflow-standards-tools
```

该模式直接运行指定安装入口，检查入口所属 Python 环境、包版本和模块位置，不再次安装 wheel，也不以源码启动替代安装验证。wheel 模式与此模式互斥。测试另记录 App Server 的实际 CLI 路径和版本；旧进程不能替代新进程验证。

需要真实模型端到端检查时显式添加 `--live`。所有模型测试固定 `gpt-6-luna` / `medium`，不接受其他模型或推理强度覆盖，不重试或回退。两种模式都在启动前读取当前进程非空的 `OPENAI_API_KEY`、`OPENAI_BASE_URL`，显式配置测试 provider；不使用默认地址或其他登录凭据。真实值不写入仓库或配置文件，不输出原始进程、RPC 或 HTTP 错误。

`--live` 向 MCP 子进程按名称转发两项 API 环境变量、标准代理变量（含大小写）及 `SSL_CERT_FILE`，对最小合成开发事实执行 `check_api_input` 语义审核，再通过 `turn/start` 检查模型实际调用指定的只读工具，产生相应用量。检查绑定当前 thread/turn，保留早于响应到达的通知，核对实际 `item/completed`、工具参数/返回值与 `turn/completed` 状态；文字声称通过不被采纳，失败/中断、连接退出、无效消息或审批请求均不会默认为通过，也不会自动批准权限。

总时限为 120 秒，结束或失败后有界关闭进程。输出仅含安全状态、固定模型/强度、实际 CLI 和 MCP 安装来源，以及实际工具调用计数；不输出凭据、端点或原始异常。该测试不模拟桌面宿主对真实私有项目数据的全部审批规则，也不授予全局配置、Memory 或 Git/GitHub 写入权限。

## Git commit 信息生成

需要起草提交信息时调用 `generate_git_commit_message`，提交本次选定 patch/hunk 的事实与来源，复用现有内容生成链路返回完整 `message`。经审阅并用 `check_commit_message` 检查后，才在独立授权及其他检查满足时提交。工具不读取 Git、不执行提交；用户已有完整提交信息时保留原文。详见 [提交信息生成与检查](skills/dev-workflow-standards/references/check-commit-message.md)。

## Issue/PR 多轮修订

新增 `start_issue_pr_draft`、`revise_issue_pr_draft`、`get_issue_pr_draft`、`close_issue_pr_draft`：由外层 Agent 每轮反馈，MCP 保存受限进程内上下文，仍使用 Responses API 和独立质量审查，不引入 Agents SDK。重启或 `/reload` 会丢失草稿；不写文件或 Memory，不自动发布。协议、容量、错误和最小示例见 [多轮草稿](skills/dev-workflow-standards/references/openai-workflow-tools.md#issuepr-多轮修订草稿)。

## 异步与指令迁移（#95 / #96）

OpenAI 工具通过 `AsyncOpenAI` 和 `httpx2.AsyncClient` 原生异步等待；MCP 名称、参数 Schema、注解和返回结构保持兼容，仍一次调用完成后返回。同步本地工具继续由 MCP 工作线程执行；异步服务中的阻塞 Git/gh 查询仅局部交给线程。审核、生成及质量审查保持数据依赖，不自动并行；取消停止后续阶段与重试，通过有界屏蔽清理释放客户端。

请求数据与 JSON Schema 在首次等待前固定，同一请求超时重试复用已审核内容；每次实际请求和重试仍重新读取当前两项环境配置。每次尝试独立创建/关闭客户端，不共享全局连接池；配置轮换后，任务内日志仍脱敏进行中请求的旧配置。审核自身只豁免递归语义审核，不豁免本地检测。

本次移除公开 `decide_skill_workflow` 及固定路由输入/返回字段；调用方直接按当前动作条件选择工具，没有替代路由 API。Python 直接调用联网服务的方法现在需要 `await`，独立脚本可在顶层使用 `asyncio.run`，不能在 MCP 请求内嵌套事件循环。已检查本仓库及可访问的 token-io-decoupling、Serena 源码，未发现这两个外部项目的直接调用；这不证明其他用户没有集成。发布/更新前，下游应迁移同步 Python 调用和已移除的路由接口，旧工作流路径需更新为 Hook 路径。

源码改动不自动安装发布包、更新已安装 Skill/全局 AGENTS 或重新加载 MCP；这些是独立动作。现有 `.githooks` 继续承担本地提交校验，与指令 Hooks 分开。
