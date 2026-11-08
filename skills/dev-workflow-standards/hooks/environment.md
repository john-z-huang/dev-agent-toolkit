# Python 与 Shell 环境

## 进入条件

准备选择 Python 解释器/依赖环境或执行 Python 脚本、模块、一次性命令时适用 Python 条件；准备生成、执行或验证 Shell 脚本时适用 Shell 条件。无相关动作时不加载环境资料，也不增加 Git 工作。

## 执行条件

Python 使用 [环境参考](../references/python-environment.md) 中用户/项目优先规则；正确区分项目根、uv workspace、独立项目及无项目场景，在相应环境执行，不套用无项目默认版本覆盖项目约束。

Shell 使用 [Shell 参考](../references/shell-environment.md) 中实际目标运行时与 shebang；既有脚本保持其环境约定。本机 Shell 不能证明容器或远端具备相同能力。

## 离开条件

成功：环境满足声明约束，执行/验证结果来自实际目标环境。暂停：根目录、版本、依赖归属或目标 Shell 无法确认；不自行改约束或以其他环境结果冒充。

## 重新进入条件

解释器、依赖、项目根、目标平台或运行命令的环境要求变化。
