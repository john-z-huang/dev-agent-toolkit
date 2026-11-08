"""安装或更新项目级或用户全局 Codex hooks；无操作参数时仅预览。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import sys
import tempfile
from pathlib import Path


class HookSetupError(ValueError):
    """只包含可安全展示的安装诊断。"""


def command_group(
    executable: Path, status_message: str, matcher: str | None = None
) -> dict:
    handler = {
        "type": "command",
        "command": shlex.quote(str(executable)),
        "timeout": 5,
        "statusMessage": status_message,
    }
    group = {"hooks": [handler]}
    if matcher is not None:
        group["matcher"] = matcher
    return group


def build_config(executable: Path) -> dict:
    tools = (
        r"^(Bash|exec_command|shell|shell_command|apply_patch|"
        r"mcp__(dev-workflow-standards-tools|dev_workflow_standards_tools)__.*)$"
    )
    return {
        "hooks": {
            "SessionStart": [command_group(executable, "加载会话开发约束与授权边界")],
            "UserPromptSubmit": [command_group(executable, "提示本轮交付与验证要求")],
            "PreToolUse": [
                command_group(
                    executable,
                    "核验目标仓库路径与工具调用条件",
                    r"^mcp__(dev-workflow-standards-tools|dev_workflow_standards_tools)__.*$",
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


def managed_files(directory: Path, configuration: dict) -> dict[Path, bytes]:
    if directory.is_symlink() or (directory / "hooks").is_symlink():
        raise HookSetupError("目标 .codex 或 hooks 目录不能是符号链接")
    return {
        directory / "hooks.json": (
            json.dumps(configuration, ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8"),
    }


def file_hashes(files: dict[Path, bytes]) -> dict[str, str]:
    return {path.name: hashlib.sha256(data).hexdigest() for path, data in files.items()}


def validate_target(files: dict[Path, bytes], manifest: Path, update: bool) -> dict:
    paths = [*files, manifest]
    if not update:
        paths.append(manifest.parent / "dev_workflow.py")
        if any(path.exists() or path.is_symlink() for path in paths):
            raise HookSetupError(
                "目标已有 Hooks 资源。受管安装请用 --update；仅有 hooks.json 时，"
                "可先加 --merge --dry-run 审阅合并计划。"
            )
        return {}
    if any(
        path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1
        for path in paths
    ):
        raise HookSetupError(
            "更新要求完整的受管普通文件；请检查脚本、配置和清单是否缺失或为链接"
        )
    record = json.loads(manifest.read_bytes())
    if isinstance(record, dict) and record.get("format") in (1, 2):
        legacy = manifest.parent / "dev_workflow.py"
        if legacy.is_symlink() or not legacy.is_file() or legacy.stat().st_nlink != 1:
            raise HookSetupError("旧版受管脚本缺失或不是独立普通文件，无法迁移")
        paths.append(legacy)
    observed = file_hashes(
        {path: path.read_bytes() for path in paths if path != manifest}
    )
    return validate_manifest(record, observed)


def validate_manifest(record: object, observed: dict[str, str]) -> dict:
    if not isinstance(record, dict) or record.get("files") != observed:
        raise HookSetupError("受管文件已修改或清单不匹配；不会覆盖本地修改")
    schema = record.get("format")
    expected = {"format", "files"}
    if schema == 2 or (schema == 3 and "base_configuration" in record):
        expected.add("base_configuration")
    if schema not in (1, 2, 3) or set(record) != expected:
        raise HookSetupError("受管清单格式无效")
    if "base_configuration" in record:
        validate_configuration(record["base_configuration"])
    return record


def validate_configuration(configuration: object) -> None:
    if not isinstance(configuration, dict) or not isinstance(
        configuration.get("hooks"), dict
    ):
        raise HookSetupError("已有 hooks.json 必须是包含 hooks 对象的 JSON 配置")
    for groups in configuration["hooks"].values():
        if not isinstance(groups, list) or any(
            not isinstance(group, dict) for group in groups
        ):
            raise HookSetupError("已有 Hooks 事件必须是对象数组；请手工审阅")


def merge_configuration(base: dict, configuration: dict) -> dict:
    validate_configuration(base)
    merged = {
        **base,
        "hooks": {event: list(groups) for event, groups in base["hooks"].items()},
    }
    for event, groups in configuration["hooks"].items():
        target = merged["hooks"].setdefault(event, [])
        target.extend(group for group in groups if group not in target)
    return merged


def merge_base(directory: Path, files: dict[Path, bytes], manifest: Path) -> dict:
    config = directory / "hooks.json"
    # 只允许接入已有普通配置；脚本和清单有残留时不能推断安装归属。
    if config.is_symlink() or not config.is_file() or config.stat().st_nlink != 1:
        raise HookSetupError(
            "--merge 要求已有普通 hooks.json 文件，拒绝符号链接和硬链接"
        )
    validate_target(
        {path: data for path, data in files.items() if path != config}, manifest, False
    )
    base = json.loads(config.read_bytes())
    validate_configuration(base)
    return base


def backup_configuration(path: Path) -> None:
    descriptor, name = tempfile.mkstemp(prefix="hooks.json.backup-", dir=path.parent)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(path.read_bytes())
    print(f"原配置备份：{name}", file=sys.stderr)


def replace_file(path: Path, data: bytes) -> None:
    # 单文件原子替换；多文件更新中断后由清单校验失败关闭。
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def install(
    directory: Path,
    configuration: dict,
    *,
    update: bool,
    dry_run: bool,
    merge: bool = False,
) -> dict:
    files = managed_files(directory, configuration)
    manifest = directory / "hooks/dev_workflow.manifest.json"
    previous = {} if merge else validate_target(files, manifest, update)
    base = (
        merge_base(directory, files, manifest)
        if merge
        else previous.get("base_configuration")
    )
    if base is not None:
        configuration = merge_configuration(base, configuration)
        files = managed_files(directory, configuration)
    record = {"format": 3, "files": file_hashes(files)}
    if base is not None:
        record["base_configuration"] = base
    files[manifest] = (json.dumps(record, indent=2) + "\n").encode("utf-8")
    if dry_run:
        return configuration
    if merge:
        backup_configuration(directory / "hooks.json")
    for path, data in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        if update or (merge and path.name == "hooks.json"):
            if path.read_bytes() != data:
                replace_file(path, data)
        else:
            with path.open("xb") as stream:
                stream.write(data)
    return configuration


def target_directory(args: argparse.Namespace, parser: argparse.ArgumentParser) -> Path:
    if args.project_root is not None:
        if not args.project_root.is_absolute() or not args.project_root.is_dir():
            parser.error("--project-root 必须是已存在的绝对目录")
        return args.project_root.resolve() / ".codex"
    configured = os.environ.get("CODEX_HOME")
    directory = Path(configured) if configured is not None else Path.home() / ".codex"
    if not directory.is_absolute() or (directory.exists() and not directory.is_dir()):
        parser.error("全局 Codex 目录必须是绝对目录路径")
    if configured is not None and not directory.is_dir():
        parser.error("显式 CODEX_HOME 必须是已存在的目录")
    # 保留最终目录本身，交由受管文件检查拒绝符号链接。
    return directory


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--project-root", type=Path, help="安装到指定项目的 .codex 目录")
    scope.add_argument(
        "--global",
        dest="global_scope",
        action="store_true",
        help="安装到 CODEX_HOME，未设置时使用 ~/.codex",
    )
    operation = parser.add_mutually_exclusive_group()
    operation.add_argument(
        "--install", action="store_true", help="首次安装到所选 Codex 目录"
    )
    operation.add_argument(
        "--update", action="store_true", help="更新完整且未修改的受管 Hooks"
    )
    parser.add_argument("--dry-run", action="store_true", help="校验并预览，不写文件")
    parser.add_argument(
        "--merge", action="store_true", help="首次安装时备份并保留已有 hooks.json"
    )
    return parser


def main(executable: Path, arguments: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(arguments)
    if args.merge and not args.install:
        parser.error("--merge 只能与 --install 一起使用")
    directory = target_directory(args, parser)
    configuration = build_config(executable)
    if args.install or args.update:
        try:
            configuration = install(
                directory,
                configuration,
                update=args.update,
                dry_run=args.dry_run,
                merge=args.merge,
            )
        except HookSetupError as error:
            print(f"操作未完成：{error}", file=sys.stderr)
            return 1
        except ValueError:
            print(
                "操作未完成：Hooks 配置或清单不是有效的 UTF-8 JSON。", file=sys.stderr
            )
            return 1
        except OSError:
            print(
                "操作未完成：文件读写失败（权限不足或目录/文件状态不符合要求）。"
                "请检查实际文件，勿盲目重试或覆盖。",
                file=sys.stderr,
            )
            return 1
    print(json.dumps(configuration, ensure_ascii=False, indent=2))
    return 0
