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
from typing import NotRequired, TypedDict

from . import configuration
from .configuration import (
    HookConfiguration,
    HookSetupError,
    build_config,
    merge_configuration,
    validate_configuration,
)

# 保留既有构造函数的导入路径，配置实现统一在纯配置模块维护。
command_group = configuration.command_group


class HookManifest(TypedDict):
    """受管文件指纹及可选的合并前配置；仅用于完整性检查。"""

    format: int
    files: dict[str, str]
    base_configuration: NotRequired[HookConfiguration]


def managed_files(
    directory: Path, configuration: HookConfiguration
) -> dict[Path, bytes]:
    """生成待写字节并拒绝目标目录链接；本函数不创建或覆盖文件。"""
    if directory.is_symlink() or (directory / "hooks").is_symlink():
        raise HookSetupError("目标 .codex 或 hooks 目录不能是符号链接")
    return {
        directory / "hooks.json": (
            json.dumps(configuration, ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8"),
    }


def file_hashes(files: dict[Path, bytes]) -> dict[str, str]:
    return {path.name: hashlib.sha256(data).hexdigest() for path, data in files.items()}


def validate_install_target(paths: list[Path], manifest: Path) -> None:
    """首次注册拒绝已有受管资源或待写配置。"""
    for name in ("dev_workflow.manifest.json", "dev_workflow.py"):
        legacy = manifest.parent / name
        if legacy.is_symlink() or legacy.exists():
            raise HookSetupError(
                f"目标已有旧版 Hooks 资源（{name}）；请先审阅并处理旧版注册"
            )
    if any(path.exists() or path.is_symlink() for path in [*paths, manifest]):
        raise HookSetupError(
            "目标已有 Hooks 资源。受管安装请用 dev-agent-toolkit --hooks-update 或 configure --update；"
            "仅有 hooks.json 时，可用 configure --install --merge --dry-run 审阅合并计划。"
        )


def read_update_file(path: Path) -> bytes:
    """读取已存在的独立普通文件，保留原始字节供指纹校验与备份。"""
    if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1:
        raise HookSetupError(
            "更新要求完整的受管普通文件；请检查配置或清单是否缺失或为链接"
        )
    return path.read_bytes()


def read_update_snapshot(
    config: Path, manifest: Path
) -> tuple[dict[Path, bytes], object]:
    """更新前读取当前配置和清单。"""
    snapshot = {config: read_update_file(config), manifest: read_update_file(manifest)}
    record = json.loads(snapshot[manifest])
    return snapshot, record


def validate_manifest(record: object, observed: dict[str, str]) -> HookManifest:
    """核对受管指纹及版本结构，将外部 JSON 转为明确的清单类型。"""
    if not isinstance(record, dict) or record.get("files") != observed:
        raise HookSetupError(
            "受管文件已修改或清单不匹配；不会覆盖本地修改。"
            "格式 3 的安装若只改了其他 Hooks，可用 configure --update --reconcile --dry-run 审阅。"
        )
    schema = record.get("format")
    expected = {"format", "files"}
    if "base_configuration" in record:
        expected.add("base_configuration")
    if type(schema) is not int or schema != 3 or set(record) != expected:
        raise HookSetupError("受管清单格式无效")
    validated: HookManifest = {"format": schema, "files": observed}
    if "base_configuration" in record:
        validated["base_configuration"] = validate_configuration(
            record["base_configuration"]
        )
    return validated


def unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """恢复时拒绝会被普通 JSON 解码静默丢弃的重复字段。"""
    result = dict(pairs)
    if len(result) != len(pairs):
        raise HookSetupError("Hooks 配置包含重复 JSON 字段，无法恢复")
    return result


def reconcile_base(
    config: Path,
    original: bytes,
    record: object,
    managed: HookConfiguration,
) -> HookConfiguration:
    """证明原配置归属，再从当前配置中完整扣除受管组。"""
    if not isinstance(record, dict) or record.get("format") != 3:
        raise HookSetupError("--reconcile 要求格式 3 的受管清单")
    previous = managed
    if "base_configuration" in record:
        old_base = validate_configuration(record["base_configuration"])
        if any(
            group in old_base["hooks"].get(event, [])
            for event, groups in managed["hooks"].items()
            for group in groups
        ):
            raise HookSetupError("清单的原配置与受管组重叠；无法区分各组归属")
        previous = merge_configuration(old_base, managed)
    expected = file_hashes(managed_files(config.parent, previous))
    if record.get("files") != expected:
        raise HookSetupError(
            "无法重建清单记录的原始 Hooks 指纹；请核对原工具版本和配置"
        )
    validate_manifest(record, expected)

    current = validate_configuration(
        json.loads(original, object_pairs_hook=unique_json_object)
    )
    hooks = dict(current["hooks"])
    for event, groups in managed["hooks"].items():
        observed = hooks.get(event, [])
        start = len(observed) - len(groups)
        if start < 0 or json.dumps(observed[start:], sort_keys=True) != json.dumps(
            groups, sort_keys=True
        ):
            raise HookSetupError("当前受管 Hooks 组有缺失、修改或顺序变化；请人工核对")
        hooks[event] = observed[:start]
    base: HookConfiguration = {**current, "hooks": hooks}
    if merge_configuration(base, managed) != current:
        raise HookSetupError("当前配置包含重复受管 Hooks 组；请人工核对")
    return base


def validate_no_legacy_commands(base: HookConfiguration) -> None:
    """识别旧安装器生成的单个绝对入口命令。"""
    executable = "dev-workflow-standards-hooks"
    for groups in base["hooks"].values():
        for group in groups:
            handlers = group.get("hooks")
            if not isinstance(handlers, list):
                continue
            for handler in handlers:
                if not isinstance(handler, dict) or handler.get("type") != "command":
                    continue
                command = handler.get("command")
                if not isinstance(command, str) or executable not in command:
                    continue
                try:
                    arguments = shlex.split(command)
                except ValueError:
                    continue
                if (
                    len(arguments) == 1
                    and Path(arguments[0]).is_absolute()
                    and Path(arguments[0]).name == executable
                    and shlex.quote(arguments[0]) == command
                ):
                    raise HookSetupError(
                        f"hooks.json 含旧版 Hooks 命令（{executable}）；请先审阅并处理旧版注册"
                    )


def merge_base(
    directory: Path, files: dict[Path, bytes], manifest: Path
) -> HookConfiguration:
    """只接入现有普通配置；受管清单存在时拒绝重新合并。"""
    config = directory / "hooks.json"
    validate_install_target([path for path in files if path != config], manifest)
    if config.is_symlink() or not config.is_file() or config.stat().st_nlink != 1:
        raise HookSetupError(
            "--merge 要求已有普通 hooks.json 文件，拒绝符号链接和硬链接"
        )
    base = validate_configuration(json.loads(config.read_bytes()))
    validate_no_legacy_commands(base)
    return base


def backup_configuration(path: Path, original: bytes) -> None:
    """独占保存原始配置字节并报告备份位置，失败时由调用者停止注册。"""
    descriptor, name = tempfile.mkstemp(prefix="hooks.json.backup-", dir=path.parent)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(original)
    print(f"原配置备份：{name}", file=sys.stderr)


def replace_file(path: Path, data: bytes) -> None:
    """在同目录暂存并原子替换单个文件，异常时释放句柄及临时路径。"""
    # 单文件原子替换；多文件更新中断后由清单校验失败关闭。
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def publish_files(files: dict[Path, bytes], *, update: bool, merge: bool) -> None:
    """按注册模式发布文件；更新只替换变化内容，首次注册独占创建。

    每个替换单独原子执行；中途失败时保留已发布内容供调用者核对。
    """
    for path, data in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        if update or (merge and path.name == "hooks.json"):
            if path.read_bytes() != data:
                replace_file(path, data)
        else:
            with path.open("xb") as stream:
                stream.write(data)


def install(
    directory: Path,
    configuration: HookConfiguration,
    *,
    update: bool,
    dry_run: bool,
    merge: bool = False,
    reconcile: bool = False,
) -> HookConfiguration:
    """校验后注册配置并发布清单；预览不写入，显式合并先保存备份。

    多文件发布不保证整体原子性；中断后需先核对实际配置和清单。
    """
    files = managed_files(directory, configuration)
    config = directory / "hooks.json"
    manifest = directory / "hooks/dev_agent_toolkit.manifest.json"
    snapshot: dict[Path, bytes] = {}
    reconciled = False
    base = None
    if update:
        snapshot, previous = read_update_snapshot(config, manifest)
        observed = file_hashes(
            {path: data for path, data in snapshot.items() if path != manifest}
        )
        if (
            reconcile
            and isinstance(previous, dict)
            and previous.get("files") != observed
        ):
            base = reconcile_base(config, snapshot[config], previous, configuration)
            reconciled = True
        else:
            base = validate_manifest(previous, observed).get("base_configuration")
    elif merge:
        base = merge_base(directory, files, manifest)
    else:
        validate_install_target(list(files), manifest)
    if base is not None:
        configuration = merge_configuration(base, configuration)
        files = managed_files(directory, configuration)
    record: HookManifest = {"format": 3, "files": file_hashes(files)}
    if base is not None:
        record["base_configuration"] = base
    files[manifest] = (json.dumps(record, indent=2) + "\n").encode("utf-8")
    if dry_run:
        return configuration
    if reconciled:
        if any(read_update_file(path) != data for path, data in snapshot.items()):
            raise HookSetupError("Hooks 文件在恢复校验后已变化；请重新审阅")
        backup_configuration(config, snapshot[config])
    elif merge:
        backup_configuration(config, config.read_bytes())
    publish_files(files, update=update, merge=merge)
    return configuration


def target_directory(args: argparse.Namespace, parser: argparse.ArgumentParser) -> Path:
    """解析项目或全局目标，保留最终目录链接供注册校验拒绝。"""
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
    parser.add_argument(
        "--reconcile",
        action="store_true",
        help="更新时核验受管组，备份并保留当前其他 Hooks",
    )
    return parser


def main(executable: Path, arguments: list[str]) -> int:
    """注册 CLI 边界；输出候选配置，仅向用户返回安全诊断和退出码。"""
    parser = build_parser()
    args = parser.parse_args(arguments)
    if args.merge and not args.install:
        parser.error("--merge 只能与 --install 一起使用")
    if args.reconcile and not args.update:
        parser.error("--reconcile 只能与 --update 一起使用")
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
                reconcile=args.reconcile,
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
