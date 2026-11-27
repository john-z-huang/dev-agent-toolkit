"""Offline, backup-first management of the user's global Codex instructions."""

import ctypes
import difflib
import errno
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
import time
from contextlib import contextmanager
from importlib.resources import files
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

OWNER = "dev-agent-toolkit-tools"
SCHEMA = 1
MAX_BYTES = 2_000_000
TARGET_NAME = "AGENTS.md"
METADATA_NAME = ".AGENTS.md.dev-agent-toolkit.json"
LOCK_NAME = ".AGENTS.md.global-agents.lock"
HOME_PLACEHOLDER = "{{HOME}}"
_MARKDOWN_LINK = re.compile(r"\]\(([^)]+)\)")
_PLACEHOLDER = re.compile(r"\{\{[^{}]*\}\}")
_MALFORMED_SINGLE_PLACEHOLDER = re.compile(
    r"(?<!\{)\{(?:HOME|[A-Z_][A-Z0-9_]*)\}(?!\})"
)


class GlobalAgentsError(Exception):
    """A safe, user-displayable local validation or update error."""


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _lexists(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    except OSError:
        raise GlobalAgentsError("无法安全检查本地路径状态") from None
    return True


def _check_directory_chain(path: Path) -> None:
    """Reject symlinked ancestors and existing non-directories without resolving them."""
    absolute = Path(os.path.abspath(path))
    for item in reversed((absolute, *absolute.parents)):
        if item.is_symlink():
            raise GlobalAgentsError("目标或祖先目录是符号链接；拒绝继续")
        if _lexists(item) and not item.is_dir():
            raise GlobalAgentsError("目标或祖先不是普通目录；拒绝继续")


def _read_regular(path: Path, *, label: str) -> tuple[bytes, int]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        raise GlobalAgentsError(f"{label}无法安全读取；检查文件类型和权限") from None
    try:
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or info.st_size > MAX_BYTES
            ):
                raise GlobalAgentsError(f"{label}必须是独立普通文件且不超过大小上限")
            data = stream.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise GlobalAgentsError(f"{label}超过大小上限")
            return data, stat.S_IMODE(info.st_mode)
    except GlobalAgentsError:
        raise
    except OSError:
        raise GlobalAgentsError(f"{label}无法安全读取；检查文件类型和权限") from None


def _source_bytes(raw_source: str | None) -> tuple[bytes, str]:
    if raw_source is None:
        try:
            resource = files("dev_agent_toolkit_tools").joinpath(
                "global_instructions", "codex-global.md"
            )
            data = resource.read_bytes()
        except (OSError, ModuleNotFoundError, TypeError):
            raise GlobalAgentsError(
                "发布包缺少全局 AGENTS 指令资源；请从完整 wheel 安装工具"
            ) from None
        source_name = "bundled"
    else:
        if not raw_source or "\x00" in raw_source:
            raise GlobalAgentsError("--source 必须是有效的本地 Markdown 文件路径")
        source = Path(os.path.abspath(Path(raw_source).expanduser()))
        if source.is_symlink():
            raise GlobalAgentsError("--source 不能是符号链接")
        data, _ = _read_regular(source, label="--source")
        source_name = str(source)
    if not data or len(data) > MAX_BYTES:
        raise GlobalAgentsError("全局 AGENTS 指令源为空或超过大小上限")
    try:
        text = data.decode("utf-8")
    except UnicodeError:
        raise GlobalAgentsError("全局 AGENTS 指令源必须是 UTF-8 Markdown") from None
    if not text or "\x00" in text:
        raise GlobalAgentsError("全局 AGENTS 指令源为空或包含无效字符")
    return data, source_name


def _render(template: bytes, home: Path) -> bytes:
    try:
        text = template.decode("utf-8")
    except UnicodeError:
        raise GlobalAgentsError("全局 AGENTS 指令源必须是 UTF-8 Markdown") from None
    text = text.replace(HOME_PLACEHOLDER, str(home))
    if (
        "{{" in text
        or "}}" in text
        or _PLACEHOLDER.search(text)
        or _MALFORMED_SINGLE_PLACEHOLDER.search(text)
    ):
        raise GlobalAgentsError("全局 AGENTS 指令源包含未知或格式错误的占位符")

    home_prefix = str(home).rstrip("/") + "/"
    for link in _MARKDOWN_LINK.findall(text):
        parsed = urlsplit(link)
        if parsed.scheme or not parsed.path.startswith("/"):
            continue
        decoded = unquote(parsed.path)
        if decoded != str(home) and not decoded.startswith(home_prefix):
            raise GlobalAgentsError("全局 AGENTS 指令源包含非用户主目录的本地绝对链接")
        path = Path(decoded)
        if ".." in PurePosixPath(decoded).parts:
            raise GlobalAgentsError("全局 AGENTS 指令源包含越界本地链接")
        _check_directory_chain(path.parent)
        if path.is_symlink() or not _lexists(path):
            raise GlobalAgentsError("全局 AGENTS 指令源引用的本地文件缺失或为符号链接")
        _read_regular(path, label="全局 AGENTS 链接目标")
    return text.encode("utf-8")


def _metadata(path: Path) -> dict:
    data, _ = _read_regular(path, label="全局 AGENTS 元数据")
    try:
        value = json.loads(data)
        if (
            not isinstance(value, dict)
            or set(value) != {"schema", "owner", "target", "rendered_sha256"}
            or type(value["schema"]) is not int
            or value["schema"] != SCHEMA
            or value["owner"] != OWNER
            or value["target"] != TARGET_NAME
            or not isinstance(value["rendered_sha256"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", value["rendered_sha256"])
        ):
            raise ValueError
        return value
    except (ValueError, TypeError, KeyError, UnicodeError):
        raise GlobalAgentsError("全局 AGENTS 元数据无效；拒绝更新并保留现场") from None


def _target_paths() -> tuple[Path, Path, Path]:
    home = Path.home()
    if not home.is_absolute():
        raise GlobalAgentsError("无法确定绝对用户主目录")
    target = home / ".codex" / TARGET_NAME
    parent = target.parent
    _check_directory_chain(parent)
    if target.is_symlink():
        raise GlobalAgentsError("全局 AGENTS 目标是符号链接；拒绝继续")
    return target, parent / METADATA_NAME, parent / LOCK_NAME


def _snapshot(target: Path, metadata_path: Path) -> dict:
    target_exists = _lexists(target)
    metadata_exists = _lexists(metadata_path)
    if target.is_symlink() or metadata_path.is_symlink():
        raise GlobalAgentsError("全局 AGENTS 目标或元数据是符号链接；拒绝继续")
    target_bytes = target_mode = None
    if target_exists:
        target_bytes, target_mode = _read_regular(target, label="全局 AGENTS 目标")
    metadata_bytes = metadata_value = None
    if metadata_exists:
        metadata_bytes, _ = _read_regular(metadata_path, label="全局 AGENTS 元数据")
        metadata_value = _metadata(metadata_path)
    if metadata_value is not None and target_bytes is None:
        raise GlobalAgentsError("全局 AGENTS 元数据存在但目标缺失；拒绝自动修复")
    if target_bytes is None:
        status = "missing"
    elif metadata_value is None:
        status = "unmanaged"
    elif _digest(target_bytes) != metadata_value["rendered_sha256"]:
        status = "locally_modified"
    else:
        status = "managed"
    return {
        "target_exists": target_exists,
        "target_bytes": target_bytes,
        "target_mode": target_mode,
        "metadata_exists": metadata_exists,
        "metadata_bytes": metadata_bytes,
        "metadata_value": metadata_value,
        "status": status,
    }


def _state_identity(snapshot: dict) -> tuple:
    return (
        snapshot["target_exists"],
        snapshot["target_bytes"],
        snapshot["target_mode"],
        snapshot["metadata_exists"],
        snapshot["metadata_bytes"],
    )


def _classify(
    snapshot: dict, rendered: bytes, *, adopt: bool, replace_local: bool
) -> tuple[str, str | None]:
    target_bytes = snapshot["target_bytes"]
    if not snapshot["target_exists"]:
        return "create", None
    if target_bytes == rendered:
        if snapshot["status"] == "unmanaged" and adopt:
            return "adopt_metadata", None
        if snapshot["status"] == "locally_modified":
            if not replace_local:
                return "repair_metadata", "replace_local"
            return "repair_metadata", None
        return "unchanged", None
    if snapshot["status"] == "unmanaged":
        return "adopt", None if adopt else "adopt"
    if snapshot["status"] == "locally_modified":
        return "replace_local", None if replace_local else "replace_local"
    return "update", None


def _metadata_bytes(rendered: bytes) -> bytes:
    value = {
        "schema": SCHEMA,
        "owner": OWNER,
        "target": TARGET_NAME,
        "rendered_sha256": _digest(rendered),
    }
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def _backup_timestamp() -> int:
    return int(time.time())


def _backup(parent: Path, original: bytes) -> Path:
    path = parent / f"AGENTS_BAK_{_backup_timestamp()}.md"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError:
        raise GlobalAgentsError(f"备份文件已存在，拒绝覆盖: {path.name}") from None
    except OSError:
        raise GlobalAgentsError("无法创建 AGENTS.md 备份；目标保持不变") from None
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(original)
            stream.flush()
            os.fsync(fd)
    except OSError:
        os.close(fd)
        raise GlobalAgentsError("写入 AGENTS.md 备份失败；目标保持不变") from None
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
    try:
        verified, _ = _read_regular(path, label="AGENTS.md 备份")
    except GlobalAgentsError:
        raise GlobalAgentsError("无法核验 AGENTS.md 备份；目标保持不变") from None
    if verified != original:
        raise GlobalAgentsError("AGENTS.md 备份字节校验失败；目标保持不变")
    _sync_directory(parent)
    return path


def _sync_directory(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        # Directory fsync is unavailable on some supported filesystems; the
        # atomic file operation and its own fsync remain mandatory.
        pass


def _noreplace_rename(source: Path, target: Path) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        function = libc.renamex_np
        function.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        function.restype = ctypes.c_int
        result = function(os.fsencode(source), os.fsencode(target), 4)  # RENAME_EXCL
    elif sys.platform.startswith("linux") and hasattr(libc, "renameat2"):
        function = libc.renameat2
        function.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        function.restype = ctypes.c_int
        result = function(
            -100, os.fsencode(source), -100, os.fsencode(target), 1
        )  # RENAME_NOREPLACE
    else:
        raise GlobalAgentsError("当前平台不支持安全的原子文件发布；仅支持 macOS/Linux")
    if result != 0:
        code = ctypes.get_errno()
        if code in {errno.EEXIST, errno.ENOTEMPTY}:
            raise GlobalAgentsError("全局 AGENTS 目标在更新期间出现；目标保持不变")
        raise GlobalAgentsError(f"全局 AGENTS 原子发布失败（errno={code}）")


def _require_noreplace_support() -> None:
    if sys.platform == "darwin":
        if not hasattr(ctypes.CDLL(None), "renamex_np"):
            raise GlobalAgentsError("当前平台缺少安全的原子文件发布能力")
    elif sys.platform.startswith("linux"):
        if not hasattr(ctypes.CDLL(None), "renameat2"):
            raise GlobalAgentsError("当前平台缺少安全的原子文件发布能力")
    else:
        raise GlobalAgentsError("当前平台不支持安全的原子文件发布；仅支持 macOS/Linux")


def _cleanup_agents_stage(raw_fd: int | None, temporary: Path) -> None:
    """尽力释放未移交的描述符和暂存文件，保留原始发布错误。"""
    if raw_fd is not None:
        try:
            os.close(raw_fd)
        except OSError:
            pass
    try:
        temporary.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


def _publish_file(
    parent: Path, target: Path, data: bytes, mode: int, *, replace: bool
) -> None:
    try:
        fd, raw_temp = tempfile.mkstemp(prefix=".AGENTS.md.stage-", dir=parent)
    except OSError:
        raise GlobalAgentsError("无法创建全局 AGENTS 暂存文件") from None
    temporary = Path(raw_temp)
    raw_fd: int | None = fd
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as stream:
            raw_fd = None
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        staged, _ = _read_regular(temporary, label="AGENTS.md 暂存文件")
        if staged != data:
            raise GlobalAgentsError("AGENTS.md 暂存文件校验失败")
        if replace:
            os.replace(temporary, target)
        else:
            _noreplace_rename(temporary, target)
        _sync_directory(parent)
    except GlobalAgentsError:
        raise
    except OSError:
        if _file_matches(target, data):
            raise GlobalAgentsError(
                "全局 AGENTS 发布后确认失败；文件状态不确定"
            ) from None
        raise GlobalAgentsError("全局 AGENTS 原子发布失败；目标保持不变") from None
    finally:
        _cleanup_agents_stage(raw_fd, temporary)


def _file_matches(path: Path, expected: bytes) -> bool:
    if not _lexists(path) or path.is_symlink():
        return False
    try:
        actual, _ = _read_regular(path, label="本地文件")
    except GlobalAgentsError:
        return False
    return actual == expected


@contextmanager
def _lock(path: Path):
    try:
        import fcntl
    except ImportError:
        raise GlobalAgentsError("当前平台不支持安全的全局 AGENTS 合作锁") from None
    flags = (
        os.O_CREAT
        | os.O_RDWR
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        fd = os.open(path, flags, 0o600)
    except OSError:
        raise GlobalAgentsError("无法安全打开全局 AGENTS 合作锁") from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise GlobalAgentsError("全局 AGENTS 合作锁必须是独立普通文件")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise GlobalAgentsError(
                "另一个全局 AGENTS 更新正在进行；请稍后重试"
            ) from None
        except OSError:
            raise GlobalAgentsError("无法取得全局 AGENTS 合作锁") from None
        yield
    finally:
        os.close(fd)


def _require_write_support() -> None:
    if not sys.platform.startswith(("darwin", "linux")):
        raise GlobalAgentsError("当前平台不支持安全的原子文件发布；仅支持 macOS/Linux")
    try:
        import fcntl  # noqa: F401 - probe before creating the target directory or lock
    except ImportError:
        raise GlobalAgentsError("当前平台不支持安全的全局 AGENTS 合作锁") from None
    _require_noreplace_support()


def _diff(current: bytes | None, rendered: bytes, target: Path) -> str:
    before = (
        current.decode("utf-8", errors="replace").splitlines(keepends=True)
        if current is not None
        else []
    )
    after = rendered.decode("utf-8", errors="replace").splitlines(keepends=True)
    fromfile = str(target) if current is not None else "/dev/null"
    return "".join(
        difflib.unified_diff(before, after, fromfile=fromfile, tofile="candidate")
    )


def _result_base(
    source_name: str, template: bytes, rendered: bytes, target: Path, snapshot: dict
) -> dict:
    current = snapshot["target_bytes"]
    if not snapshot["target_exists"]:
        status = "missing"
    elif current == rendered and snapshot["status"] == "unmanaged":
        status = "unchanged_unmanaged"
    elif current == rendered and snapshot["status"] == "managed":
        status = "up_to_date"
    elif snapshot["status"] == "unmanaged":
        status = "unmanaged"
    elif snapshot["status"] == "locally_modified":
        status = "locally_modified"
    else:
        status = "managed_outdated"
    return {
        "ok": True,
        "target": str(target),
        "source": source_name,
        "status": status,
        "source_sha256": _digest(template),
        "rendered_sha256": _digest(rendered),
        "current_sha256": _digest(current) if current is not None else None,
        "managed": snapshot["status"] == "managed",
    }


def _preview_agents_update(
    result: dict,
    snapshot: dict,
    rendered: bytes,
    plan_action: str,
    required_flag: str | None,
) -> dict:
    """生成更新预览，显式保留接管冲突、备份冲突和内容差异。"""
    target = Path(result["target"])
    target_will_change = plan_action in {"create", "adopt", "update", "replace_local"}
    changed = plan_action != "unchanged"
    backup_name = (
        f"AGENTS_BAK_{_backup_timestamp()}.md"
        if snapshot["target_exists"] and target_will_change
        else None
    )
    conflict = None
    if required_flag:
        conflict = {
            "kind": plan_action,
            "requires": f"--{required_flag.replace('_', '-')}",
        }
    backup_collision = bool(backup_name and _lexists(target.parent / backup_name))
    if backup_collision:
        collision = {
            "kind": "backup_collision",
            "backup_name": backup_name,
            "requires": "wait for a new Unix second or resolve the existing backup",
        }
        if conflict is None:
            conflict = collision
        else:
            conflict["also"] = collision
    return {
        **result,
        "status": "preview",
        "plan_action": plan_action,
        "changed": changed,
        "conflict": conflict,
        "backup_name": backup_name,
        "backup_collision": backup_collision,
        "diff": _diff(snapshot["target_bytes"], rendered, target),
    }


def _prepare_agents_update(target: Path, metadata_path: Path, lock_path: Path) -> None:
    """在创建锁和备份前核验平台能力及路径安全。"""
    _require_write_support()
    parent = target.parent
    try:
        parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError:
        raise GlobalAgentsError(
            "无法创建 ~/.codex 目标目录；检查权限和目录状态"
        ) from None
    _check_directory_chain(parent)
    if target.is_symlink() or metadata_path.is_symlink() or lock_path.is_symlink():
        raise GlobalAgentsError("更新路径包含符号链接；拒绝继续")


def _verify_agents_publication(
    target: Path, metadata_path: Path, rendered: bytes, backup_path: Path | None
) -> dict:
    """回读目标和受管指纹；发布后的任何不确定状态都必须显式失败。"""
    try:
        published = _snapshot(target, metadata_path)
    except GlobalAgentsError:
        backup_note = f"; 已保留备份 {backup_path.name}" if backup_path else ""
        raise GlobalAgentsError(
            f"发布后无法核验全局 AGENTS 与元数据；状态不确定，需人工核对{backup_note}"
        ) from None
    if (
        published["target_bytes"] != rendered
        or published["status"] != "managed"
        or published["metadata_value"]["rendered_sha256"] != _digest(rendered)
    ):
        backup_note = f"; 已保留备份 {backup_path.name}" if backup_path else ""
        raise GlobalAgentsError(
            f"发布后目标或元数据发生变化；状态不确定，需人工核对{backup_note}"
        )
    return published


def _publish_agents_update(
    target: Path, metadata_path: Path, current: dict, rendered: bytes
) -> tuple[dict, Path | None]:
    """先备份，再复核并发布目标及元数据，保留并发修改时的备份。"""
    parent = target.parent
    backup_path = None
    if current["target_exists"] and current["target_bytes"] != rendered:
        backup_path = _backup(parent, current["target_bytes"])

    # 备份后再次核对基线；遇到并发修改时保留备份，供人工审阅。
    final = _snapshot(target, metadata_path)
    if _state_identity(final) != _state_identity(current):
        backup_note = f"; 已保留备份 {backup_path.name}" if backup_path else ""
        raise GlobalAgentsError(f"目标在备份后发生变化，拒绝覆盖{backup_note}")

    if current["target_bytes"] != rendered:
        target_mode = current["target_mode"] if current["target_exists"] else 0o600
        _publish_file(
            parent, target, rendered, target_mode, replace=current["target_exists"]
        )

    try:
        _publish_file(
            parent,
            metadata_path,
            _metadata_bytes(rendered),
            0o600,
            replace=current["metadata_exists"],
        )
    except GlobalAgentsError:
        backup_note = f"; 已保留备份 {backup_path.name}" if backup_path else ""
        raise GlobalAgentsError(
            f"目标发布后元数据更新失败；状态不确定，需人工核对{backup_note}"
        ) from None
    published = _verify_agents_publication(target, metadata_path, rendered, backup_path)
    return published, backup_path


def _require_agents_update_flag(required_flag: str | None) -> None:
    if required_flag == "adopt":
        raise GlobalAgentsError("目标是未知文件；显式使用 --adopt 后才可更新")
    if required_flag:
        raise GlobalAgentsError(
            "受管目标已被本地修改；显式使用 --replace-local 后才可更新"
        )


def manage_global_agents(
    action: str,
    raw_source: str | None = None,
    *,
    dry_run: bool = False,
    adopt: bool = False,
    replace_local: bool = False,
) -> dict:
    """Inspect or explicitly update ``~/.codex/AGENTS.md`` with backup-first writes."""
    if action not in {"show", "update"}:
        raise GlobalAgentsError("未知全局 AGENTS 操作")
    if action == "show" and (dry_run or adopt or replace_local):
        raise GlobalAgentsError(
            "agents show 不接受 --dry-run、--adopt 或 --replace-local"
        )
    if adopt and replace_local:
        raise GlobalAgentsError("--adopt 与 --replace-local 不能同时使用")
    template, source_name = _source_bytes(raw_source)
    target, metadata_path, lock_path = _target_paths()
    rendered = _render(template, Path.home())
    snapshot = _snapshot(target, metadata_path)
    result = _result_base(source_name, template, rendered, target, snapshot)

    if action == "show":
        return result

    plan_action, required_flag = _classify(
        snapshot, rendered, adopt=adopt, replace_local=replace_local
    )
    if dry_run:
        return _preview_agents_update(
            result, snapshot, rendered, plan_action, required_flag
        )
    _require_agents_update_flag(required_flag)
    if plan_action == "unchanged":
        return {
            **result,
            "status": "unchanged",
            "plan_action": plan_action,
            "changed": False,
        }

    _prepare_agents_update(target, metadata_path, lock_path)

    with _lock(lock_path):
        current = _snapshot(target, metadata_path)
        # A cooperating updater may have completed the exact requested update
        # while this process waited. Treat that as an idempotent success.
        if (
            current["target_bytes"] == rendered
            and current["status"] == "managed"
            and _digest(rendered) == current["metadata_value"]["rendered_sha256"]
        ):
            return {
                **_result_base(source_name, template, rendered, target, current),
                "status": "unchanged",
                "plan_action": "unchanged",
                "changed": False,
            }
        if _state_identity(current) != _state_identity(snapshot):
            raise GlobalAgentsError(
                "目标或元数据在预检后发生变化；未执行更新，请重新查看"
            )
        plan_action, required_flag = _classify(
            current, rendered, adopt=adopt, replace_local=replace_local
        )
        _require_agents_update_flag(required_flag)
        if plan_action == "unchanged":
            return {
                **_result_base(source_name, template, rendered, target, current),
                "status": "unchanged",
                "plan_action": "unchanged",
                "changed": False,
            }

        published, backup_path = _publish_agents_update(
            target, metadata_path, current, rendered
        )
        return {
            **_result_base(source_name, template, rendered, target, published),
            "status": "updated",
            "plan_action": plan_action,
            "changed": True,
            "backup": str(backup_path) if backup_path else None,
        }
