# 独立 Skill 安装与更新

Skill 指令从发布包复制为普通文件快照。开发仓库可以放在任意目录，不需要放入 Skill 扫描目录，也不使用指向源码的符号链接。安装软件包与更新已安装 Skill 是两个独立动作。

## 源码仓库的安装更新入口

在源码仓库根目录使用 `dws`。需要 `uv` 位于 `PATH`，本机 Bash 3.2 可执行；从其他工作目录调用时使用脚本的绝对路径。

```bash
# 无参数只打印帮助并返回 0，不执行安装、注册或文件写入
./dws
./dws --help
# 查看某项操作的选项
./dws --skills-install --help
```

操作参数放在首位，每次选择一项；其余参数传给对应管理程序：

| 独立操作 | 执行范围 |
| --- | --- |
| `--uv-build` | 调用 `uv build` 构建仓库的 `mcp-server/`，输出到仓库的 `dist/`。 |
| `--uv-tool-install [--force]` | 调用 `uv tool install` 安装 `dist/` 中与项目当前版本匹配的 wheel；重装时加 `--force`。 |

这两项独立于 MCP 注册和指令更新。使用各自的 `--help` 查看 uv 选项。需要指定其他 wheel 或传递更多 uv 选项时，使用 `--uv-tool-install [uv 选项] <wheel 路径>`，相对路径以调用目录为准。

| 资源 | 安装参数 | 更新参数 | 执行范围 |
| --- | --- | --- | --- |
| MCP Server | `--mcp-install` | `--mcp-update` | 安装或更新软件包、注册服务并配置环境变量转发。 |
| Skill | `--skills-install` | `--skills-update` | 仅管理 Skill 快照，不安装软件包或注册 MCP。 |
| 全局 `AGENTS.md` | `--agents-install` | `--agents-update` | 仅管理全局指令，不安装软件包或注册 MCP。 |
| 原生 Codex Hooks | `--hooks-install` | `--hooks-update` | 从源码管理项目级或用户全局 Hooks，不修改宿主信任。 |

```bash
./dws --mcp-update --dry-run
./dws --skills-update --dry-run
./dws --agents-update --dry-run
./dws --hooks-install --project-root /absolute/path/to/target-project --dry-run
./dws --hooks-update --project-root /absolute/path/to/target-project --dry-run
./dws --hooks-install --global --dry-run
./dws --hooks-update --global --dry-run
./dws --hooks-install --global --merge --dry-run
```

Hooks 操作通过 `uv tool` 安装或重装独立的 `dev-workflow-standards-hooks` 包，再调用已安装 CLI 的 `configure` 子命令注册命令绝对路径。运行时不依赖源码或 MCP 项目环境。`--project-root` 指定已有绝对项目目录，与 `--global` 互斥且必须二选一。全局目标默认 `~/.codex`，显式 `CODEX_HOME` 必须是已有绝对目录。`dws --dry-run` 只显示安装/注册计划，不核验配置冲突；精确只读预览应使用已安装 CLI 的 `configure ... --dry-run`。更新要求受管配置无本地修改，旧版受管脚本安装校验后迁移为命令注册，保留原脚本；未知旧资源不自动接管。全局和项目级 Hooks 会累积触发，不自动迁移或清理另一范围。详见 [原生 Hooks](codex-hooks.md)。

若目标仅有其他工具的 `hooks.json`，安装时可显式加 `--merge`，先预览合并结果，再去掉 `--dry-run` 执行；正式合并先备份原字节到目标目录的 `hooks.json.backup-*`，保留原事件和字段。后续更新保留原 Hooks，但手工修改配置仍会阻止更新。已有本工具脚本或清单时拒绝合并，不覆盖未知旧安装。

Skill 和全局指令操作通过 `uv tool dir --bin` 定位已安装完整发行包的 `dev-workflow-standards` 入口，不从源码开发环境读取资源。先按下文构建并安装完整 wheel，再选择所需的资源操作；更新软件包不会自动刷新指令快照。不在源码仓库中时，仍可使用下文的完整发行包 CLI 命令。

Skill 支持 `--target` 和 `--dry-run`。全局指令支持 `--source`、`--dry-run`、`--adopt` 和 `--replace-local`；`--agents-install` 与 `--agents-update` 均转交 `agents update`，目标不存在时创建，已有未知文件仍需显式接管，备份与本地修改保护保持有效。预览后去掉 `--dry-run` 才执行对应写入，预览成功不表示已安装或更新。

## 安装发布包

以下命令在仓库根目录执行。先构建完整 wheel，再安装 `dist/` 中与 `mcp-server/pyproject.toml` 当前版本匹配的产物。

```bash
./dws --uv-build
./dws --uv-tool-install
"$(uv tool dir --bin)/dev-workflow-standards" skills install --dry-run
"$(uv tool dir --bin)/dev-workflow-standards" skills install
"$(uv tool dir --bin)/dev-workflow-standards" skills show
```

安装、更新和查看 Skill 时均通过 `uv tool dir --bin` 定位工具入口，明确使用从完整 wheel 安装的版本，避免依赖 Shell 对裸命令的解析。保留完整路径外的双引号，以支持包含空格的目录。

默认目标为 `~/.agents/skills/dev-workflow-standards-skill`。`--target` 可指定仓库外的独立目标目录；支持显式选择兼容目录，但不默认写入 `~/.codex/skills`，也不覆盖任何已有目标。路径不得含 `..`、符号链接祖先或位于 Git checkout 内。父目录可由正式安装创建；预览和查看不创建目录或锁文件。目录后缀不改变 `SKILL.md` 中的技能名称，源码指令目录也保持不变。

命令离线读取包资源，不读取 OpenAI 凭据、不调用 OpenAI、不注册 MCP、不修改 Codex 配置，也不复制或启用 Hook。安装器写入资源、受管清单及同目标的持久锁文件。macOS/Linux 使用原子目录发布；其他平台或不支持原子操作的文件系统拒绝写入，不退回非原子覆盖。

## 显式更新

源码或文档变更后，在仓库根目录重新构建并更新工具。先按实际构建产物更新 wheel，再显式更新已安装 Skill；软件包安装不会自动更新 Skill 快照：

```bash
./dws --uv-build
./dws --uv-tool-install --force
"$(uv tool dir --bin)/dev-workflow-standards" skills update --dry-run
"$(uv tool dir --bin)/dev-workflow-standards" skills update
"$(uv tool dir --bin)/dev-workflow-standards" skills show
```

使用显式目标安装的，更新和查看时继续传入同一 `--target`。查看输出包含包版本及已安装版本。重复 `install` 会拒绝已有目标；重复 `update` 在内容相同时返回 `unchanged`。源码文档变化不会影响已安装快照；相同包版本也会比较内容校验和。

更新要求原清单归属正确，且全部文件与清单一致。用户修改、缺失文件、额外文件或目录、硬链接、符号链接和特殊文件均会阻止更新。未知旧目录没有受管清单，不会被自动接管。完整性清单用于检测损坏和修改，不是来源签名或授权凭证；安装包来源仍需用户核验。

## 包资源缺失与命令入口排查

“发布包缺少 Skill 资源；请从完整 wheel 安装工具”表示当前导入的 Python 包无法读取 `skill_bundle/manifest.json` 或清单中的资源文件。该检查先于目标 Skill 目录检查，不能仅凭此错误认定已安装的 Skill 文档损坏。

先通过 uv 工具的明确入口执行只读预览；原安装使用了显式 `--target` 时，继续传入同一目标：

```bash
"$(uv tool dir --bin)/dev-workflow-standards" skills update --dry-run
```

若该预览成功而裸命令失败，应在执行管理命令的 Bash 终端中检查同名命令的解析。即使没有激活虚拟环境，也可能因 `PATH` 顺序、别名、函数或命令缓存选中另一份安装。以下 Bash 命令分别查看命令类型、全部可执行文件路径及 uv 工具目录：

```bash
type -t dev-workflow-standards
type -a -p dev-workflow-standards
uv tool dir --bin
```

项目的可编辑安装会导入源码包；即使 `site-packages` 中存在构建生成的资源副本，资源查找仍可能指向不含 `skill_bundle` 的源码目录，从而出现相同报错。Skill 管理应使用上面的完整发行包入口，开发环境中的 `uv run` 不用于执行这些安装管理操作。

若明确的 uv 工具入口也失败，再检查该工具的安装来源和包内资源，按已核验的完整 wheel 重新安装。不要通过删除目标 Skill、手动复制资源或改动受管清单来跳过检查。

## 现有 Skill 和中断处理

已有 `~/.agents/skills/dev-workflow-standards` 是受保护的旧项目路径，不会被自动迁移、覆盖或删除。即使显式传入该路径、它的子路径或会覆盖它的父目录，或目录中已有受管清单，也会拒绝操作；解析到同一旧项目位置的目标同样受保护。使用新的默认目录 `~/.agents/skills/dev-workflow-standards-skill` 安装独立快照。避免同时让 Codex 加载两份同名 Skill；现有绝对路径引用不会自动调整。人工迁移和全局指令变更需另行确认。

安装/更新使用同目标的合作进程锁，竞争时失败而非排队覆盖。原子交换前后正式目录均为完整快照；强制终止可能留下 `.名称.skill-stage-*` 副本。先用 `"$(uv tool dir --bin)/dev-workflow-standards" skills show` 检查正式安装并人工核对副本，再决定如何处理；工具不自动清理未知残留。锁文件保留以维持同一锁身份，不应在安装进程运行时删除。

合作进程锁不能阻止外部编辑器或恶意进程写文件；更新期间应停止其他写入者。发布前核对快照，交换后检测到旧目录变化会撤回并保留现场。此机制不承诺断电持久化或对恶意并发写入者的沙箱隔离。

## Pi Code Agent 使用范围

默认 Skill 目录 `~/.agents/skills/dev-workflow-standards-skill` 可被 Pi 发现；更新已安装快照后用 `/reload` 重新加载。Skill 更新不等于 MCP 更新或重连。

MCP 可通过源码的 `scripts/setup-pi-mcp.py` 注册已安装的 uv tool（可选 `--install` 安装）；此脚本不包含在 Skill Markdown 快照中。详见 [Pi 安装说明](https://github.com/john-z-huang/dev-workflow-standards/blob/main/INSTALL.md#给-pi-code-agent-注册-mcp)。Pi 原生配置为用户级 `~/.pi/agent/mcp.json` 或已信任项目的 `.pi/mcp.json`；stdio 继承启动环境，调用时限字段为 `timeout`（秒），不照搬 Codex `env_vars` 或 `tool_timeout_sec`。注册会写配置，需要对应授权；替换同名服务前保留自定义设置。连接状态、实际工具发现及只读调用才是验证证据，注册成功不等于可用。

`agents update` / `--agents-*` 仍只管理 Codex 全局 `~/.codex/AGENTS.md`，`--hooks-*` 仍只管理原生 Codex Hooks；它们不是 Pi 全局指令或扩展安装入口，也不是 Pi 使用 Skill/MCP 的前置条件。不自动迁移或修改 Pi 全局配置。审批与工具发现见 [Skill 入口](../SKILL.md#宿主审批兼容)。

## 全局 AGENTS.md 的独立更新

仓库的 `instructions/codex-global.md` 维护全局指令源，根目录 `AGENTS.md` 继续维护本项目规则。全局源作为独立资源随完整 wheel 发布，不属于 Skill 快照；更新包和 Skill 都不会自动覆盖 `~/.codex/AGENTS.md`。

安装管理 CLI 后，可通过项目入口预览当前 checkout 中的模板：

```bash
./dws --agents-update --dry-run
```

核对差异后显式执行同一命令并去掉 `--dry-run`。首次接管已有文件须加 `--adopt`；受管文件被本地修改时，另用 `--replace-local` 表明已审阅并决定替换。项目入口可用 `--source` 指定其他模板。直接运行已安装的 `dev-workflow-standards agents` 命令时，省略 `--source` 会读取包内全局指令源。模板可以省略 `{{HOME}}` 和 Skill 入口链接。管理命令会把模板中的 `{{HOME}}` 替换为当前用户主目录，并校验模板中实际引用的本地绝对链接。

每次实际改变已有全局文件前，默认先把原字节备份到 `~/.codex/AGENTS_BAK_<Unix秒时间戳>.md`。备份失败或同秒名称冲突即停止，不覆盖已有备份；目标不存在、内容不变及只读预览不产生备份。备份由用户自行保留和选择恢复，不自动删除。目标文件、受管记录和锁仅服务于本次全局文件更新，不注册 MCP、不修改其他配置。更新期间停止外部编辑，发生中断时先核对实际目标、记录和备份再恢复；不要仅凭退出前的文字认定成功。

详细命令和边界见 [仓库全局指令说明](https://github.com/john-z-huang/dev-workflow-standards/blob/main/INSTALL.md#版本管理与更新全局-agentsmd)。

## MCP 与源码辅助脚本

原 `dev-workflow-standards-tools` 命令仍直接启动 stdio MCP。Skill 管理入口是另一个命令，不向该入口加入隐式安装动作。MCP 注册、环境变量名称转发及审批继续遵循原规则。

源码入口的操作参数见本文前面的“源码仓库的安装更新入口”，注册、转发和审批选项见 [Codex 安装说明](https://github.com/john-z-huang/dev-workflow-standards/blob/main/INSTALL.md#codex-中安装)。仅注册已有 MCP 安装可运行 `./dws --server dev-workflow-standards-tools`；仅修复已注册服务的转发声明使用 `--env-only`。无参数不再执行注册，只打印帮助。原 Python 入口及 `--install`、`--install --force` 等 MCP 参数仍兼容。

根目录入口通过 `exec` 调用 `scripts/setup-codex-mcp.py` 执行 MCP 操作，两者必须保持仓库中的相对路径。入口不依赖调用者的工作目录，原样转发参数与退出状态。这两个脚本属于源码开发资产，不包含在 Skill 快照中。完整仓库结构和 Hook/历史兼容脚本见 [项目仓库](https://github.com/john-z-huang/dev-workflow-standards)。独立 Skill 不依赖这些脚本才能加载；固定操作优先按 [MCP 工具目录](mcp-tools.md) 调用已注册服务，未提供工具或功能未覆盖时按 [CLI 补充规约](cli-fallback.md) 在任务授权内完成。
