# Python、JavaScript 与 Shell 环境

## 进入条件

选择 Python 环境、调整依赖或运行 Python 时查阅 Python 条件。编写、执行或验证 Shell 脚本及终端命令块时查阅 Shell 条件。

## 执行条件

按 [Python 环境参考](../references/python-environment.md) 核对项目根及解释器。项目或用户指定的环境优先。

安装、添加、升级或修复 Modal 依赖，且本地环境需通过网络代理访问 Modal 平台时，同时遵循 [Modal 代理依赖规则](../references/python-environment.md#modal-代理依赖)。不将此规则套用于无关 Python 包或仅远端运行的环境。

按 [Shell 参考](../references/shell-environment.md) 选择目标环境、解释器及传参方式。本机 macOS 命令显式使用 Bash 绝对路径。容器和远端以实际 Shell 能力为准，交付脚本时核对 shebang。终端运行 JavaScript 或 Python 时还须核对项目运行时，并遵循 [内联和多行脚本规则](../references/shell-environment.md#在终端运行-javascript-和-python)。

## 离开条件

成功：环境满足声明约束，执行/验证结果来自实际目标环境。暂停：根目录、版本、依赖归属或目标 Shell 无法确认；不自行改约束或以其他环境结果冒充。

## 重新进入条件

解释器、依赖、项目根、目标平台或运行命令的环境要求变化。
