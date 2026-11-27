"""Hooks 配置的生成、结构校验和保留用户字段的合并，不执行文件操作。"""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import TypedDict, TypeGuard

HookGroup = dict[str, object]


class HookConfiguration(TypedDict):
    """事件组是受检结构；未声明的用户顶层字段在合并时原样保留。"""

    hooks: dict[str, list[HookGroup]]


class CommandHandler(TypedDict):
    """本工具生成的命令处理器，不约束保留的其他工具处理器。"""

    type: str
    command: str
    timeout: int
    statusMessage: str


class HookSetupError(ValueError):
    """只包含可安全展示的安装诊断。"""


def command_group(
    executable: Path, status_message: str, matcher: str | None = None
) -> HookGroup:
    handler: CommandHandler = {
        "type": "command",
        "command": shlex.quote(str(executable)),
        "timeout": 5,
        "statusMessage": status_message,
    }
    group: HookGroup = {"hooks": [handler]}
    if matcher is not None:
        group["matcher"] = matcher
    return group


def build_config(executable: Path) -> HookConfiguration:
    """生成离线命令注册，按互斥 matcher 提供对应场景的状态文案。"""
    tools = (
        r"^(Bash|exec_command|shell|shell_command|apply_patch|"
        r"mcp__dev_agent_toolkit__.*)$"
    )
    return {
        "hooks": {
            "SessionStart": [command_group(executable, "加载会话开发约束与授权边界")],
            "UserPromptSubmit": [command_group(executable, "提示本轮交付与验证要求")],
            "PreToolUse": [
                command_group(
                    executable,
                    "核验目标仓库路径与工具调用条件",
                    r"^mcp__dev_agent_toolkit__.*$",
                ),
                command_group(
                    executable,
                    "提示 Python/Shell 执行环境要求",
                    r"^(Bash|exec_command|shell|shell_command)$",
                ),
                command_group(
                    executable, "提示修改范围与现有内容保护", r"^apply_patch$"
                ),
            ],
            "PostToolUse": [
                command_group(executable, "识别工具失败并提示恢复要求", tools)
            ],
        }
    }


def is_configuration(value: object) -> TypeGuard[HookConfiguration]:
    """只核验本工具依赖的事件组形状，不解释其他工具的处理器协议。"""
    if not isinstance(value, dict):
        return False
    hooks = value.get("hooks")
    if not isinstance(hooks, dict):
        return False
    for event, groups in hooks.items():
        if not isinstance(event, str) or not isinstance(groups, list):
            return False
        for group in groups:
            if not isinstance(group, dict):
                return False
    return True


def validate_configuration(value: object) -> HookConfiguration:
    """验证 JSON 边界并收窄类型；不支持的结构抛出安全的安装诊断。"""
    if not is_configuration(value):
        raise HookSetupError("Hooks 配置必须包含 hooks 对象，且各事件为对象数组")
    return value


def merge_configuration(
    base: HookConfiguration, configuration: HookConfiguration
) -> HookConfiguration:
    """保留原配置字段与事件顺序，追加去重后的组，不修改输入对象。"""
    base = validate_configuration(base)
    merged: HookConfiguration = {
        **base,
        "hooks": {event: list(groups) for event, groups in base["hooks"].items()},
    }
    for event, groups in configuration["hooks"].items():
        target = merged["hooks"].setdefault(event, [])
        for group in groups:
            if group not in target:
                target.append(group)
    return merged
