"""安装或更新项目级或用户全局 Codex hooks；无操作参数时仅预览。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
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


def validate_target(
    files: dict[Path, bytes], manifest: Path, update: bool
) -> HookManifest | None:
    """首次注册拒绝已有资源，更新核对清单及旧脚本；失败不写入。"""
    paths = [*files, manifest]
    if not update:
        paths.append(manifest.parent / "dev_workflow.py")
        if any(path.exists() or path.is_symlink() for path in paths):
            raise HookSetupError(
                "目标已有 Hooks 资源。受管安装请用 --update；仅有 hooks.json 时，"
                "可先加 --merge --dry-run 审阅合并计划。"
            )
        return None
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


def validate_manifest(record: object, observed: dict[str, str]) -> HookManifest:
    """核对受管指纹及版本结构，将外部 JSON 转为明确的清单类型。"""
    if not isinstance(record, dict) or record.get("files") != observed:
        raise HookSetupError("受管文件已修改或清单不匹配；不会覆盖本地修改")
    schema = record.get("format")
    expected = {"format", "files"}
    if schema == 2 or (schema == 3 and "base_configuration" in record):
        expected.add("base_configuration")
    if type(schema) is not int or schema not in (1, 2, 3) or set(record) != expected:
        raise HookSetupError("受管清单格式无效")
    validated: HookManifest = {"format": schema, "files": observed}
    if "base_configuration" in record:
        validated["base_configuration"] = validate_configuration(
            record["base_configuration"]
        )
    return validated


def merge_base(
    directory: Path, files: dict[Path, bytes], manifest: Path
) -> HookConfiguration:
    """只接入现有普通配置；本工具脚本或清单残留时拒绝推断归属。"""
    config = directory / "hooks.json"
    # 只允许接入已有普通配置；脚本和清单有残留时不能推断安装归属。
    if config.is_symlink() or not config.is_file() or config.stat().st_nlink != 1:
        raise HookSetupError(
            "--merge 要求已有普通 hooks.json 文件，拒绝符号链接和硬链接"
        )
    validate_target(
        {path: data for path, data in files.items() if path != config}, manifest, False
    )
    return validate_configuration(json.loads(config.read_bytes()))


def backup_configuration(path: Path) -> None:
    """独占保存原始配置字节并报告备份位置，失败时由调用者停止注册。"""
    descriptor, name = tempfile.mkstemp(prefix="hooks.json.backup-", dir=path.parent)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(path.read_bytes())
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
) -> HookConfiguration:
    """校验后注册配置并发布清单；预览不写入，显式合并先保存备份。

    多文件发布不保证整体原子性；中断后需先核对实际配置和清单。
    """
    files = managed_files(directory, configuration)
    manifest = directory / "hooks/dev_workflow.manifest.json"
    previous = None if merge else validate_target(files, manifest, update)
    base = previous.get("base_configuration") if previous is not None else None
    if merge:
        base = merge_base(directory, files, manifest)
    if base is not None:
        configuration = merge_configuration(base, configuration)
        files = managed_files(directory, configuration)
    record: HookManifest = {"format": 3, "files": file_hashes(files)}
    if base is not None:
        record["base_configuration"] = base
    files[manifest] = (json.dumps(record, indent=2) + "\n").encode("utf-8")
    if dry_run:
        return configuration
    if merge:
        backup_configuration(directory / "hooks.json")
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
    return parser


def main(executable: Path, arguments: list[str]) -> int:
    """注册 CLI 边界；输出候选配置，仅向用户返回安全诊断和退出码。"""
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
