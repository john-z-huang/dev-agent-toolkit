# Shell 环境与脚本

适用于 Shell 脚本的生成、执行和兼容性验证，也包含通过 Bash 在终端执行 JavaScript 和 Python 的写法。先确认脚本实际运行环境。Python 环境选择见 [`python-environment.md`](python-environment.md)。

## 本机 macOS 环境事实

本机交互 Shell 默认为 Zsh 5.9，系统自带的 `/bin/bash` 和 `/bin/sh` 版本为 `3.2.57(1)-release`。在其他 macOS、容器或远端环境中，按实际可用的 Shell 和版本判断。

## 本地新生成脚本

- 默认生成 Bash 脚本，不生成 Zsh 脚本；不要因为当前终端默认为 Zsh 就改变脚本选择。
- Bash 脚本文件第一行必须使用 `#!/bin/bash` 或 `#!/usr/bin/env bash` 声明运行环境，避免被默认 Zsh 按不兼容语法执行。
- 为本机生成的 Bash 脚本必须兼容 Bash `3.2.57(1)-release`，不使用超过该版本的特性。例如不要使用关联数组、`mapfile` 或 `readarray`。
- 按 shebang 执行可执行脚本，或显式使用适用的 Bash；不要用 `zsh script.sh` 或 `sh script.sh` 验证 Bash 脚本的运行行为。

### 直接在终端运行

Code Agent 为 macOS 本地终端生成可直接粘贴运行的 Bash 命令时，使用选定的 Bash 绝对路径，默认是 `/bin/bash`。给 `-c` 的命令字符串或 here-document 的分隔符加单引号，让 Bash 在执行时展开正文中的变量和命令替换。

**使用 `-c` 或 Bash here-document 时，只要向 Bash 正文传入一个或多个业务参数，就必须显式传入 `_` 作为 `$0`。** 把 `_` 放在 `-c` 的命令字符串之后，业务参数随后从 `$1` 开始。没有业务参数时可以省略 `_`。正文实际依赖 `$0` 时，可以用它所需的值替代 `_`。

简短且便于用单引号整体包裹的命令使用 `-c`。

```bash
/bin/bash -c 'pwd'
/bin/bash -c 'printf "%s\n" "$1"' _ 'path with spaces'
```

多行脚本或含单引号的正文可用 `-c '. /dev/stdin'` 读取 here-document，使 `_` 和后续参数分别成为正文中的 `$0` 和 `$1` 等。结束行的 `BASH` 顶格单独书写。

```bash
/bin/bash -c '. /dev/stdin' _ 'path with spaces' <<'BASH'
printf '%s\n' "$1"
BASH
```

### 在终端运行 JavaScript 和 Python

本机 macOS 的 JavaScript 和 Python 命令也通过选定的 Bash 绝对路径启动。先核对项目根目录、运行时版本和依赖环境。JavaScript 示例使用 Node.js，项目指定运行时、版本或模块类型时沿用项目配置。Python 项目使用已确认的项目解释器或项目约定的 `uv run -- python`，独立任务无其他环境要求且兼容 Python 3.14 时使用下方的 uv 托管环境。

将业务参数逐项加引号传给 Bash，再用 `"$@"` 原样传给语言解释器。向 Bash 传入参数时按 Bash 的 `$0` 规则先提供 `_`，解释器按各自的参数约定读取业务参数。代码正文使用固定内容。源码中的 `$`、反引号或多层引号容易被 Shell 展开时，优先用带单引号分隔符的 here-document 保留原文。

#### JavaScript

短代码用 `node -e`，在业务参数前加 `--`，从 `process.argv[1]` 起读取。多行代码用 `node -` 读取带引号的 here-document，此时 `process.argv[1]` 是 `-`，业务参数从 `process.argv[2]` 开始，直接放在 `-` 后。

```bash
/bin/bash -c 'exec node -e "console.log(JSON.stringify(process.argv.slice(1)))" -- "$@"' _ '-name' 'path with spaces'

/bin/bash -c 'exec node - "$@"' _ '-name' 'path with spaces' <<'JS'
const args = process.argv.slice(2);
console.log(JSON.stringify(args));
JS
```

#### Python

短代码用 `python -c`，多行代码用 `python -` 读取带引号的 here-document。两种写法都从 `sys.argv[1]` 起读取业务参数。示例中的 `--` 用于结束 `uv run` 的选项，业务参数直接放在 Python 代码字符串或 `-` 后。

```bash
/bin/bash -c 'exec uv run --no-project --managed-python --python 3.14 -- python -c "import sys; print(sys.argv[1:])" "$@"' _ '-name' 'path with spaces'

/bin/bash -c 'exec uv run --no-project --managed-python --python 3.14 -- python - "$@"' _ '-name' 'path with spaces' <<'PY'
import sys

print(sys.argv[1:])
PY
```

here-document 通过标准输入提供源码。脚本还需要从标准输入读取数据时，用内联代码或脚本文件执行。需要保存、分发或重复运行时，优先交付 `.js`、`.mjs`、`.cjs` 或 `.py` 文件，按目标项目的模块及环境约定选择。用实际目标解释器运行示例，验证参数和输出。

## 已有脚本

运行已有 Zsh 脚本时，确认所用特性不超出本机 Zsh 5.9。超过该版本时，按当前任务的修改范围处理兼容性，不擅自升级 Shell 或重写脚本。

默认生成规则不要求把已有的 `sh`、Bash 或 Zsh 脚本统一改写。先尊重已有 shebang、项目要求和目标环境；需要修复兼容性时，只修改任务涉及的部分。

## Docker 与远端云环境

在 Docker 容器或远端云环境中，默认优先选择 `sh` 作为预期运行脚本的 Shell。确认目标环境中存在 Bash 或 Zsh 等其他 Shell 后，再按任务需要选择。不要将本机的 Shell 路径或版本当作远端可用性的证据。

## 选择与验证案例

| 场景 | 处理 |
|---|---|
| 在本机 Zsh 终端直接运行 Bash 命令 | 简短命令使用 `/bin/bash -c '...'`，多行脚本可用 `/bin/bash -c '. /dev/stdin' <<'BASH'`。传入业务参数时在命令字符串后先加 `_`，正文实际依赖 `$0` 时用所需的值。默认兼容 Bash 3.2。 |
| 新建本地 Bash 脚本文件 | 生成带 Bash shebang 的 Bash 3.2 兼容脚本。 |
| 本地已有 Zsh 脚本 | 检查 Zsh 5.9 兼容性，按已有 shebang 或显式 Zsh 执行。 |
| 容器或远端尚未确认 Bash/Zsh 可用 | 优先编写可由 `sh` 执行的脚本，不使用 Bash 专属语法。 |
| 已确认目标环境存在 Bash，任务需要其特性 | 可以选择 Bash，并按目标实际版本检查兼容性。 |

语法检查使用目标 Shell 的 `-n`；它只能证明语法可解析，不能单独证明特性兼容或运行行为正确。验证本机 Bash 时核对执行的解释器确为兼容基线，不能仅凭较新 Bash 的语法检查宣称通过 Bash 3.2 验收。

## 依据

本规则迁自本机全局 `AGENTS.md` 的 Shell 章节，迁移范围与验收要求见 [Issue #64](https://github.com/john-z-huang/dev-workflow-standards/issues/64)。
