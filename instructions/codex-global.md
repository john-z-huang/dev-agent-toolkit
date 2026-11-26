# 全局指令

## 自定义 Skills

- 新建或安装自定义 Skill 默认使用 `~/.agents/skills/<skill-name>`。`~/.codex/skills` 保留给 OpenAI 系统/官方 Skill 和兼容入口。
- 找不到、读不到或无法正确加载所需 Skill 时，暂停依赖它的工作，继续其余任务。禁止凭记忆补写规则。交付时报告具体原因和路径，每个会话只报告一次。

## 代码测试规范

测试覆盖关键函数和跨函数业务流程。避免防御式编程、过量测试代码和追求 100% 覆盖率。

## 运行 Shell 命令的规范

本机 macOS 的每条 Shell 命令从首次调用起都须显式使用绝对路径的 Bash，涵盖辅助读取和提供给用户直接运行的命令。Zsh 仅可作启动器。用户指定其他 Shell，或正文在容器或远端执行时，按目标环境选择解释器。

### Bash 命令写法

内联命令用 `-c`，多行正文可用带引号的 here-document。将管道、重定向和展开留在 Bash 正文。传入业务参数时，在命令字符串后用 `_` 作 `$0`，随后传入加引号的参数，正文从 `"$1"` 起引用。无参数可省略 `_`，正文依赖 `$0` 时使用实际所需值。

```bash
/bin/bash -c 'pwd'
/bin/bash -c 'printf "%s\n" "$1"' _ 'path with spaces'
```

```bash
/bin/bash -c '. /dev/stdin' _ 'path with spaces' <<'BASH'
printf '%s\n' "$1"
BASH
```

### 按用途选择 Bash 版本

- **重复执行、保存或分发**的命令和脚本须兼容 Bash 3.2，即使本次只运行一次验证。本机用系统 `/bin/bash` 实际运行验证对象。脚本用 Bash shebang 并通过 `/bin/bash script.sh` 验证。
- **临时命令**默认使用 `/bin/bash` 和 Bash 3.2 兼容写法。确需新版特性时才探测 Homebrew Bash。确认版本和特性后使用其绝对路径，环境变化后重新核实。新版不可用时采用 3.2 兼容写法，确无兼容写法则说明最低版本。

```bash
/bin/bash -c 'bash_prefix=$(brew --prefix bash) && [[ "$bash_prefix" == /* && -x "$bash_prefix/bin/bash" ]] && "$bash_prefix/bin/bash" --version && printf "%s\n" "$bash_prefix/bin/bash"'
```

### 在终端运行 JavaScript 和 Python

先核对项目根目录、运行时版本、模块类型和依赖环境。JavaScript 示例使用 Node.js，执行时遵循项目配置。Python 使用已确认的项目解释器或项目约定的 `uv run -- python`。无其他要求且兼容 Python 3.14 的独立任务可采用下例的 uv 托管环境。

业务参数逐项加引号，Bash 用 `"$@"` 原样转发。代码正文固定。需防止 `$`、反引号或多层引号被展开时，用带单引号分隔符的 here-document。若程序还需读取标准输入，用内联代码或脚本文件。

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

保存、分发或重复运行时，优先按项目约定交付 `.js`、`.mjs`、`.cjs` 或 `.py` 文件，并用目标解释器验证参数和输出。
