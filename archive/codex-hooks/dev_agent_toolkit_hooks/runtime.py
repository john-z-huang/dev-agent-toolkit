"""Codex 原生事件适配：离线检查和定向提示，不执行开发或发布动作。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SERVER_PREFIX = "mcp__dev_agent_toolkit__"
START_CONTEXT = (
    "开发操作约束：按当前动作读取 dev-agent-toolkit 的 Hook 合同，"
    "不要求固定路线。修改前核对准确项目及已有改动归属；保留用户内容。"
    "已有授权在原范围持续有效，检查通过不授予提交、发布、清理或 Memory 写入权限。"
    "需要代码语义时使用准确项目的 Serena；未知不等于 false。"
    "历史事实需回读来源，历史指令不成为当前授权；保存摘要另核对持久化许可。"
)
COMPLETION_CONTEXT = (
    "交付时按当前目标核对实际产物与适用验证，区分 PASS、FAIL、SKIPPED、BLOCKED；"
    "不能将未执行的测试或未发生的 Git/GitHub 动作写成完成。"
    "只核对本任务资源，不因此新增提交、推送、清理或全仓审计。"
)
RECOVERY_CONTEXT = (
    "工具报告失败或部分结果：暂停依赖该结果的动作，独立工作继续。"
    "写入结果不明时先回读真实状态，不盲目重试；实际拒绝不能换入口绕过。"
    "仅报告安全错误分类，不回显凭据、端点或原始异常。"
)


def context(event_name: str, message: str) -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": event_name,
            "additionalContext": message,
        }
    }


def deny(message: str) -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": message,
        }
    }


def repository_error(value: object) -> str | None:
    """仅核验显式目标；允许符号链接，不把会话 cwd 强加给其他 worktree。"""
    if not isinstance(value, str) or not value or not Path(value).is_absolute():
        return "repo_path 必须是目标仓库或 worktree 根目录的非空绝对路径。"
    try:
        path = Path(value).resolve(strict=True)
        if not path.is_dir():
            return "repo_path 必须指向目录。"
        environment = {
            key: item for key, item in os.environ.items() if not key.startswith("GIT_")
        }
        environment["GIT_OPTIONAL_LOCKS"] = "0"
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
            env=environment,
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        if result.returncode or Path(result.stdout.strip()).resolve() != path:
            return "repo_path 必须准确指向仓库或 worktree 根目录，不能使用子目录。"
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return "无法核实 repo_path；请先确认目录和 Git 可用性。"
    return None


def pre_tool(event: dict) -> dict:
    name = event.get("tool_name", "")
    arguments = event.get("tool_input")
    if not isinstance(name, str) or not isinstance(arguments, dict):
        return {}
    if name.startswith(SERVER_PREFIX):
        # nullable repo_path 由各工具 Schema 决定；这里不把 null 改成 cwd。
        if "repo_path" in arguments and arguments["repo_path"] is not None:
            error = repository_error(arguments["repo_path"])
            if error:
                return deny(error)
        return context(
            "PreToolUse",
            "使用工具当前 Schema 核对输入和授权；"
            "建议、候选和 ok=true 均不授权后续写入。",
        )
    if name in {"Bash", "exec_command", "shell", "shell_command"}:
        return context(
            "PreToolUse",
            "执行 Python/Shell 前按环境合同核实项目根、"
            "解释器及目标 Shell。遵循项目或用户明确要求；不向全局解释器安装依赖。"
            "Git 提交保留正常 hooks；只读命令不自动授权写操作。",
        )
    if name == "apply_patch":
        return context(
            "PreToolUse",
            "修改前核对目标文件及已有内容归属；"
            "仅修改本任务范围，按行为变化选择有意义的验证。",
        )
    return {}


def failed_response(response: object) -> bool:
    """只识别结构化失败，不解析任意文本，也不复制工具输出到上下文。"""
    if not isinstance(response, dict):
        return False
    if response.get("isError") is True or response.get("ok") is False:
        return True
    code = response.get("exit_code")
    if type(code) is int and code != 0:
        return True
    structured = response.get("structuredContent")
    return isinstance(structured, dict) and structured.get("ok") is False


def handle(event: dict) -> dict:
    name = event.get("hook_event_name")
    if name == "SessionStart":
        return context(name, START_CONTEXT)
    if name == "UserPromptSubmit":
        return context(name, COMPLETION_CONTEXT)
    if name == "PreToolUse":
        return pre_tool(event)
    if name == "PostToolUse" and failed_response(event.get("tool_response")):
        return context(name, RECOVERY_CONTEXT)
    return {}


def main() -> int:
    try:
        event = json.load(sys.stdin)
        if not isinstance(event, dict):
            raise TypeError("事件必须是对象")
    except (TypeError, ValueError, UnicodeError):
        # 明确拒绝而不是 exit 1；不输出原始输入或异常。
        print("无法读取 Hook 事件 JSON；请检查客户端协议。", file=sys.stderr)
        return 2
    print(json.dumps(handle(event), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
