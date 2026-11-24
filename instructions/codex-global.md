# 全局指令

## 自定义 Skills

### 自定义 Skill 的保存和读取目录地址

新建或安装的自定义 Skill 默认必须放在 `~/.agents/skills/<skill-name>`。`~/.codex/skills` 保留给 OpenAI 提供的系统/官方 Skill 及兼容入口，不要把新的自定义 Skill 放到该目录下。

### 自定义 Skill 无法加载时的处理方法

如果无法找到、读取或正确加载本文件要求的 Skill，不要凭记忆重建规则；停止依赖该 Skill 的工作，在不中断会话的情况下尽可能的完成指令中要求的任务，并在对话结束时报告具体阻塞原因和无法加载的路径。相关 Skill 无法加载的报告在一个会话中只提醒一次，不要在每轮对话都提醒。

## 代码测试规范

禁止过度编写测试代码，避免防御式编程，和花费大量的Token在编写测试代码，而非功能代码。
测试用例的预期目标是覆盖和验证功能代码中关键的函数方法、跨函数调用的操作流程等等对业务有重大影响的点，不必追求100%的测试覆盖率。

## 运行 Shell 命令的规范

**每条在本机 macOS 执行的 Shell 命令都必须显式调用 Bash。** 这条规则从首次 Shell 工具调用起生效，包括读取 Skill、查看文件、检查环境等辅助命令，也适用于提供给用户直接运行的命令。Zsh 只可作为外层启动器，完整的命令正文必须交给 Bash。

**生成命令前先按用途选择解释器。** 只要命令或脚本要反复执行、保存或分发，就按「重复执行或分发」处理，即使这次只运行一次来验证。

### Bash命令写法

内联命令用选定的 Bash 绝对路径配合 `-c`，多行命令也可用带引号的 here-document。将管道、重定向和展开留在 Bash 正文中。业务参数通过位置参数传入，并用 `"$1"` 等引用。用户明确指定其他 Shell，或正文明确在容器或远端执行时，按对应目标环境选择解释器。

**使用 `-c` 或 Bash here-document 时，只要向 Bash 正文传入一个或多个业务参数，就必须显式传入 `_` 作为 `$0`。** 把 `_` 放在 `-c` 的命令字符串之后，业务参数随后从 `$1` 开始。没有业务参数时可以省略 `_`。正文实际依赖 `$0` 时，可以用它所需的值替代 `_`。

```bash
/bin/bash -c 'pwd'
/bin/bash -c 'printf "%s\n" "$1"' _ 'path with spaces'
```

多行正文可用 `-c '. /dev/stdin'` 读取 here-document，以相同方式传入 `$0` 和业务参数。

```bash
/bin/bash -c '. /dev/stdin' _ 'path with spaces' <<'BASH'
printf '%s\n' "$1"
BASH
```

### 高版本bash环境

**按需探测新版 Bash。** 本机临时命令默认使用系统 `/bin/bash` 和 Bash 3.2 兼容写法，包括读取 Skill、查看文件等辅助命令。只有 Code Agent 判断当前命令需要 Bash 3.2 不支持的语法或特性时，才运行下面的只读检查，查找 Homebrew 安装的新版 Bash。可复用当前环境中已核实的路径和版本。

```bash
/bin/bash -c 'prefix=$(brew --prefix bash) && [[ "$prefix" == /* && -x "$prefix/bin/bash" ]] && echo "Homebrew Bash 版本" && "$prefix/bin/bash" --version && echo "Homebrew Bash 可执行文件路径" && printf "%s\n" "$prefix/bin/bash"'
```

- **确认新版 Bash 可执行且支持所需特性**后，用它生成并运行当前临时命令。命令须以已核实的 Bash 绝对路径开头，例如用 `绝对路径 -c '…'` 指定解释器。环境变化后重新核实。
- **探测失败、版本不高于 3.2 或不满足所需特性**时，使用 `/bin/bash` 和 Bash 3.2 兼容写法。如果没有兼容写法，说明所需的最低版本。

下面用 `pwd` 演示已核实的 Bash 绝对路径调用格式。

```bash
/opt/homebrew/opt/bash/bin/bash -c 'pwd'
```

### 重复执行或分发

**重复执行、保存或分发的命令和脚本必须兼容 Bash 3.2。本机验证必须用系统 `/bin/bash` 实际运行验证对象。** 即使当前会话已探测到 Homebrew Bash，或刚用它执行过临时命令，验证可复用命令时也必须显式使用 `/bin/bash -c` 或相应的 here-document 写法，并按上文规则传入业务参数，验证脚本文件时用 `/bin/bash script.sh`。脚本文件用 Bash shebang 声明解释器，保持可移植性。

读取文件等临时辅助命令按实际所需特性选择解释器。可复用的验证对象仍须用 `/bin/bash` 执行。

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
