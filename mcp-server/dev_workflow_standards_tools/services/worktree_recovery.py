"""Bounded recovery records and guarded merge/rebase continuation operations."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import uuid
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any


_RECORD_NAME = "worktree-base-sync-recovery.json"
_MAX_RECORD_BYTES = 256 * 1024
_MAX_NATIVE_FILE_BYTES = 1024 * 1024
_MAX_INDEX_BYTES = 16 * 1024 * 1024
_MAX_WORKTREE_FILE_BYTES = 8 * 1024 * 1024
_MAX_TOTAL_WORKTREE_BYTES = 32 * 1024 * 1024
_MAX_PATHS = 4096
_MAX_REPLAY_COMMITS = 20_000
_HEX_OID = re.compile(r"^(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})$")
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
_RECORD_KEYS = {
    "schema_version",
    "operation_id",
    "kind",
    "repo_path",
    "worktree_git_dir",
    "branch_name",
    "original_head_oid",
    "base_oid",
    "base_ref",
    "remote",
    "old_base_oid",
    "merge_message",
    "affected_paths",
    "replay_oids",
    "created_at",
}
_REBASE_FILES = (
    "head-name",
    "orig-head",
    "onto",
    "done",
    "git-rebase-todo",
    "msgnum",
    "end",
    "message",
    "message-squash",
    "message-fixup",
    "stopped-sha",
    "patch",
    "amend",
    "quiet",
    "verbose",
    "interactive",
    "autostash",
    "update-refs",
)


class _RecoveryFailure(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _git_dir(root: str, git) -> Path:
    result = git(root, "rev-parse", "--path-format=absolute", "--git-dir")
    if result.returncode != 0:
        raise _RecoveryFailure("worktree_git_dir_unavailable", "无法核实当前 worktree 的 Git 目录")
    try:
        path = Path(result.stdout.strip()).resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        raise _RecoveryFailure("worktree_git_dir_unavailable", "无法解析当前 worktree 的 Git 目录") from None
    if not path.is_dir():
        raise _RecoveryFailure("worktree_git_dir_unavailable", "当前 worktree 的 Git 目录不可访问")
    return path


def _record_path(root: str, git) -> tuple[Path, Path]:
    git_dir = _git_dir(root, git)
    return git_dir, git_dir / _RECORD_NAME


def _safe_relative_paths(value: Any) -> list[str]:
    if not isinstance(value, list) or len(value) > _MAX_PATHS:
        raise _RecoveryFailure("recovery_scope_invalid", "恢复记录中的受影响路径列表超出安全限制")
    paths: list[str] = []
    for path in value:
        if not isinstance(path, str) or not path or "\x00" in path or len(path) > 4096:
            raise _RecoveryFailure("recovery_scope_invalid", "恢复记录中包含无效路径")
        candidate = PurePosixPath(path)
        if candidate.is_absolute() or ".." in candidate.parts or candidate.as_posix() != path:
            raise _RecoveryFailure("recovery_scope_invalid", "恢复记录中的路径必须是规范仓库相对 POSIX 路径")
        paths.append(path)
    if paths != sorted(set(paths)):
        raise _RecoveryFailure("recovery_scope_invalid", "恢复记录中的路径必须唯一且排序")
    return paths


def _validate_record(root: str, git_dir: Path, record: Any) -> dict[str, Any]:
    if not isinstance(record, dict) or set(record) != _RECORD_KEYS:
        raise _RecoveryFailure("recovery_record_invalid", "恢复记录字段不完整或包含未知字段")
    version = record["schema_version"]
    kind = record["kind"]
    if isinstance(version, bool) or not isinstance(version, int) or version != 1:
        raise _RecoveryFailure("recovery_record_invalid", "恢复记录版本不受支持")
    if not isinstance(kind, str) or kind not in {"merge", "rebase"}:
        raise _RecoveryFailure("recovery_record_invalid", "恢复记录版本或操作类型不受支持")
    if not isinstance(record["operation_id"], str) or not _UUID.fullmatch(record["operation_id"]):
        raise _RecoveryFailure("recovery_record_invalid", "恢复记录 operation_id 格式无效")
    if (
        not isinstance(record["repo_path"], str)
        or not isinstance(record["worktree_git_dir"], str)
        or record["repo_path"] != root
        or record["worktree_git_dir"] != str(git_dir)
    ):
        raise _RecoveryFailure("recovery_record_mismatch", "恢复记录不属于当前仓库或 worktree")
    branch = record["branch_name"]
    if not isinstance(branch, str) or not branch or len(branch) > 255:
        raise _RecoveryFailure("recovery_record_invalid", "恢复记录中的分支名无效")
    for key in ("original_head_oid", "base_oid"):
        if not isinstance(record[key], str) or not _HEX_OID.fullmatch(record[key]):
            raise _RecoveryFailure("recovery_record_invalid", f"恢复记录 {key} 无效")
    old_base = record["old_base_oid"]
    if old_base is not None and (not isinstance(old_base, str) or not _HEX_OID.fullmatch(old_base)):
        raise _RecoveryFailure("recovery_record_invalid", "恢复记录 old_base_oid 无效")
    for key in ("base_ref", "remote", "merge_message", "created_at"):
        if not isinstance(record[key], str) or len(record[key]) > 4096:
            raise _RecoveryFailure("recovery_record_invalid", f"恢复记录 {key} 无效")
    if not isinstance(record["old_base_oid"], (str, type(None))):
        raise _RecoveryFailure("recovery_record_invalid", "恢复记录 old_base_oid 无效")
    if record["kind"] == "merge" and record["merge_message"] != "chore: 同步基线更新":
        raise _RecoveryFailure("recovery_record_invalid", "恢复记录的 merge message 不受支持")
    if record["kind"] == "rebase" and record["merge_message"]:
        raise _RecoveryFailure("recovery_record_invalid", "rebase 恢复记录不能含 merge message")
    record["affected_paths"] = _safe_relative_paths(record["affected_paths"])
    replay = record["replay_oids"]
    if not isinstance(replay, list) or len(replay) > _MAX_REPLAY_COMMITS:
        raise _RecoveryFailure("recovery_record_invalid", "恢复记录中的待重放提交列表超出安全限制")
    if any(not isinstance(oid, str) or not _HEX_OID.fullmatch(oid) for oid in replay):
        raise _RecoveryFailure("recovery_record_invalid", "恢复记录中的待重放提交 OID 无效")
    if record["kind"] == "merge" and replay:
        raise _RecoveryFailure("recovery_record_invalid", "merge 恢复记录不能包含待重放提交")
    return record


def begin_managed_operation(
    root: str,
    *,
    git,
    kind: str,
    branch_name: str,
    original_head_oid: str,
    base_oid: str,
    base_ref: str,
    remote: str,
    old_base_oid: str | None,
    merge_message: str,
    affected_paths: list[str],
    replay_oids: list[str],
) -> dict[str, Any]:
    git_dir, path = _record_path(root, git)
    try:
        path.lstat()
    except FileNotFoundError:
        pass
    except OSError:
        raise _RecoveryFailure("recovery_record_unavailable", "无法检查 worktree 恢复记录") from None
    else:
        raise _RecoveryFailure("recovery_record_exists", "当前 worktree 已有恢复记录；不得覆盖或重新启动同步")
    raw_record = {
        "schema_version": 1,
        "operation_id": str(uuid.uuid4()),
        "kind": kind,
        "repo_path": root,
        "worktree_git_dir": str(git_dir),
        "branch_name": branch_name,
        "original_head_oid": original_head_oid.lower(),
        "base_oid": base_oid.lower(),
        "base_ref": base_ref,
        "remote": remote,
        "old_base_oid": old_base_oid.lower() if old_base_oid else None,
        "merge_message": merge_message,
        "affected_paths": sorted(set(affected_paths)),
        "replay_oids": [oid.lower() for oid in replay_oids],
        "created_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    record = _validate_record(root, git_dir, raw_record)
    try:
        content = (json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        raise _RecoveryFailure("recovery_record_invalid", "无法安全编码恢复记录") from None
    if len(content) > _MAX_RECORD_BYTES:
        raise _RecoveryFailure("recovery_scope_invalid", "恢复记录超过大小上限")
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError:
        raise _RecoveryFailure("recovery_record_exists", "当前 worktree 已有恢复记录；不得覆盖或重新启动同步") from None
    except OSError:
        raise _RecoveryFailure("recovery_record_write_failed", "无法安全创建 worktree 恢复记录") from None
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise _RecoveryFailure("recovery_record_write_failed", "恢复记录不是安全的普通文件")
        view = memoryview(content)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise _RecoveryFailure("recovery_record_write_failed", "恢复记录写入不完整")
            view = view[written:]
        os.fsync(descriptor)
        return record
    except OSError:
        raise _RecoveryFailure("recovery_record_write_failed", "无法完整写入 worktree 恢复记录") from None
    finally:
        os.close(descriptor)


def _read_record(root: str, git) -> tuple[dict[str, Any] | None, bytes | None]:
    git_dir, path = _record_path(root, git)
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return None, None
    except OSError:
        raise _RecoveryFailure("recovery_record_unavailable", "无法检查 worktree 恢复记录") from None
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1 or metadata.st_size > _MAX_RECORD_BYTES:
        raise _RecoveryFailure("recovery_record_invalid", "恢复记录不是安全的有界普通文件")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb", closefd=True) as stream:
            opened = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_nlink != 1
                or opened.st_dev != metadata.st_dev
                or opened.st_ino != metadata.st_ino
                or opened.st_size > _MAX_RECORD_BYTES
            ):
                raise _RecoveryFailure("recovery_record_invalid", "恢复记录在读取时发生变化")
            raw = stream.read(_MAX_RECORD_BYTES + 1)
            after = os.fstat(stream.fileno())
            current = path.lstat()
            if (
                after.st_dev != opened.st_dev or after.st_ino != opened.st_ino
                or after.st_size != opened.st_size
                or after.st_mtime_ns != opened.st_mtime_ns
                or after.st_ctime_ns != opened.st_ctime_ns
                or current.st_dev != after.st_dev or current.st_ino != after.st_ino
                or current.st_mtime_ns != after.st_mtime_ns
                or current.st_ctime_ns != after.st_ctime_ns
                or len(raw) != after.st_size
            ):
                raise _RecoveryFailure("recovery_record_changed", "恢复记录在读取时发生变化")
    except _RecoveryFailure:
        raise
    except OSError:
        raise _RecoveryFailure("recovery_record_unavailable", "无法安全读取 worktree 恢复记录") from None
    if len(raw) > _MAX_RECORD_BYTES:
        raise _RecoveryFailure("recovery_record_invalid", "恢复记录超过大小上限")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeError):
        raise _RecoveryFailure("recovery_record_invalid", "恢复记录不是有效 UTF-8 JSON") from None
    record = _validate_record(root, git_dir, value)
    canonical = (json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    if raw != canonical:
        raise _RecoveryFailure("recovery_record_invalid", "恢复记录格式或内容不是服务写入的规范记录")
    return record, raw


def _assert_safe_parent(path: Path, root: Path) -> None:
    try:
        relative = path.relative_to(root)
        root_metadata = root.lstat()
    except (OSError, ValueError):
        raise _RecoveryFailure("recovery_snapshot_unsupported", "恢复状态路径越过已核实目录") from None
    if not stat.S_ISDIR(root_metadata.st_mode):
        raise _RecoveryFailure("recovery_snapshot_unsupported", "恢复状态根目录不是普通目录")
    current = root
    for part in relative.parts[:-1]:
        current = current / part
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            return
        except OSError:
            raise _RecoveryFailure("recovery_snapshot_unavailable", "无法检查恢复状态目录") from None
        if not stat.S_ISDIR(metadata.st_mode):
            raise _RecoveryFailure("recovery_snapshot_unsupported", "恢复状态路径包含符号链接或非目录父项")


def _read_native_file(
    path: Path,
    limit: int = _MAX_NATIVE_FILE_BYTES,
    *,
    root_guard: Path | None = None,
) -> bytes | None:
    if root_guard is not None:
        _assert_safe_parent(path, root_guard)
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return None
    except OSError:
        raise _RecoveryFailure("native_state_unavailable", "无法检查 Git 恢复元数据") from None
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1 or metadata.st_size > limit:
        raise _RecoveryFailure("native_state_unsupported", "Git 恢复元数据不是有界普通文件")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb", closefd=True) as stream:
            opened = os.fstat(stream.fileno())
            if opened.st_dev != metadata.st_dev or opened.st_ino != metadata.st_ino or opened.st_nlink != 1:
                raise _RecoveryFailure("native_state_changed", "Git 恢复元数据在读取时发生变化")
            data = stream.read(limit + 1)
            after = os.fstat(stream.fileno())
            path_after = path.lstat()
            if (
                after.st_dev != opened.st_dev
                or after.st_ino != opened.st_ino
                or after.st_size != opened.st_size
                or after.st_mtime_ns != opened.st_mtime_ns
                or after.st_ctime_ns != opened.st_ctime_ns
                or path_after.st_dev != opened.st_dev
                or path_after.st_ino != opened.st_ino
            ):
                raise _RecoveryFailure("native_state_changed", "Git 恢复元数据在读取时发生变化")
    except _RecoveryFailure:
        raise
    except OSError:
        raise _RecoveryFailure("native_state_unavailable", "无法安全读取 Git 恢复元数据") from None
    if len(data) > limit:
        raise _RecoveryFailure("native_state_unsupported", "Git 恢复元数据超过大小上限")
    return data


def _hash_file(path: Path, max_bytes: int, *, root_guard: Path | None = None) -> dict[str, Any]:
    if root_guard is not None:
        _assert_safe_parent(path, root_guard)
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return {"present": False}
    except OSError:
        raise _RecoveryFailure("recovery_snapshot_unavailable", "无法检查恢复状态中的文件") from None
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1 or metadata.st_size > max_bytes:
        raise _RecoveryFailure("recovery_snapshot_unsupported", "恢复状态包含链接、特殊文件或超大文件")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    digest = hashlib.sha256()
    total = 0
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb", closefd=True) as stream:
            opened = os.fstat(stream.fileno())
            if opened.st_dev != metadata.st_dev or opened.st_ino != metadata.st_ino or opened.st_nlink != 1:
                raise _RecoveryFailure("recovery_snapshot_changed", "恢复状态中的文件在读取时发生变化")
            while True:
                chunk = stream.read(min(1024 * 1024, max_bytes + 1 - total))
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise _RecoveryFailure("recovery_snapshot_unsupported", "恢复状态中的文件超过大小上限")
                digest.update(chunk)
            after = os.fstat(stream.fileno())
            path_after = path.lstat()
            if (
                after.st_dev != opened.st_dev
                or after.st_ino != opened.st_ino
                or after.st_size != opened.st_size
                or after.st_mtime_ns != opened.st_mtime_ns
                or after.st_ctime_ns != opened.st_ctime_ns
                or path_after.st_dev != opened.st_dev
                or path_after.st_ino != opened.st_ino
            ):
                raise _RecoveryFailure("recovery_snapshot_changed", "恢复状态中的文件在读取时发生变化")
    except _RecoveryFailure:
        raise
    except OSError:
        raise _RecoveryFailure("recovery_snapshot_unavailable", "无法安全读取恢复状态中的文件") from None
    return {
        "present": True,
        "size": total,
        "mode": stat.S_IMODE(metadata.st_mode),
        "sha256": digest.hexdigest(),
    }


def _git_text(root: str, git, *args: str) -> str:
    try:
        result = git(root, "--no-optional-locks", *args)
    except Exception:
        raise _RecoveryFailure("recovery_snapshot_unavailable", "无法安全读取 Git 恢复状态") from None
    if result.returncode != 0:
        raise _RecoveryFailure("recovery_snapshot_unavailable", "无法核实 Git 恢复状态")
    output = result.stdout
    if not isinstance(output, str) or len(output.encode("utf-8")) > 4 * 1024 * 1024:
        raise _RecoveryFailure("recovery_snapshot_unsupported", "Git 恢复状态输出超过大小上限")
    return output


def _path_list(raw: str, *, status: bool = False) -> tuple[list[str], list[tuple[str, str]]]:
    fields = raw.split("\0")
    paths: list[str] = []
    entries: list[tuple[str, str]] = []
    index = 0
    while index < len(fields):
        item = fields[index]
        index += 1
        if not item:
            continue
        if status:
            if len(item) < 4 or item[2] != " ":
                raise _RecoveryFailure("recovery_snapshot_unsupported", "Git 工作区状态格式不受支持")
            state, path = item[:2], item[3:]
            if state in {"??", "!!"}:
                path = path.rstrip("/")
            entries.append((state, path))
            paths.append(path)
            if "R" in state or "C" in state:
                if index >= len(fields) or not fields[index]:
                    raise _RecoveryFailure("recovery_snapshot_unsupported", "Git 重命名状态不完整")
                entries.append((state, fields[index]))
                paths.append(fields[index])
                index += 1
        else:
            paths.append(item)
        if len(paths) > _MAX_PATHS:
            raise _RecoveryFailure("recovery_snapshot_unsupported", "恢复状态路径数量超过上限")
    unique_paths = sorted(set(paths))
    _safe_relative_paths(unique_paths)
    return unique_paths, entries


def _present(path: Path, *, root_guard: Path, directory: bool = False) -> bool:
    _assert_safe_parent(path, root_guard)
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    except OSError:
        raise _RecoveryFailure("native_state_unavailable", "无法检查 Git 恢复元数据") from None
    expected = stat.S_ISDIR(metadata.st_mode) if directory else stat.S_ISREG(metadata.st_mode)
    if not expected or (not directory and metadata.st_nlink != 1):
        raise _RecoveryFailure("native_state_unsupported", "Git 恢复元数据包含链接或特殊文件")
    return True


def _operation_kind(git_dir: Path) -> str | None:
    merge = _present(git_dir / "MERGE_HEAD", root_guard=git_dir)
    rebase_merge = _present(git_dir / "rebase-merge", root_guard=git_dir, directory=True)
    rebase_apply = _present(git_dir / "rebase-apply", root_guard=git_dir, directory=True)
    unsupported = any(
        _present(git_dir / name, root_guard=git_dir)
        for name in ("CHERRY_PICK_HEAD", "REVERT_HEAD", "BISECT_LOG", "sequencer")
    )
    active = [
        name
        for name, present in (("merge", merge), ("rebase", rebase_merge), ("rebase_apply", rebase_apply))
        if present
    ]
    if unsupported or rebase_apply or len(active) > 1:
        raise _RecoveryFailure("recovery_operation_unsupported", "当前 Git 操作不是可恢复的简单 merge/rebase")
    return active[0] if active else None


def _parse_pick_commands(raw: bytes) -> list[str]:
    try:
        text = raw.decode("utf-8")
    except UnicodeError:
        raise _RecoveryFailure("recovery_todo_invalid", "rebase todo 不是有效 UTF-8") from None
    commits: list[str] = []
    for line in text.splitlines():
        item = line.strip()
        if not item or item.startswith("#"):
            continue
        parts = item.split(None, 2)
        if len(parts) < 2 or parts[0] not in {"pick", "p"} or not _HEX_OID.fullmatch(parts[1]):
            raise _RecoveryFailure("recovery_todo_unsupported", "rebase todo 包含非 pick 或自定义命令")
        commits.append(parts[1].lower())
        if len(commits) > _MAX_REPLAY_COMMITS:
            raise _RecoveryFailure("recovery_todo_unsupported", "rebase todo 超过提交数量上限")
    return commits


def _snapshot_paths(root: str, git, affected_paths: list[str]) -> tuple[str, list[str], list[str], list[str]]:
    status_raw = _git_text(root, git, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    status_paths, status_entries = _path_list(status_raw, status=True)
    ignored_paths: list[str] = []
    if affected_paths:
        ignored_raw = _git_text(
            root,
            git,
            "--literal-pathspecs",
            "status",
            "--porcelain=v1",
            "-z",
            "--ignored=traditional",
            "--untracked-files=all",
            "--",
            *affected_paths,
        )
        ignored_paths = sorted(
            {path for state, path in _path_list(ignored_raw, status=True)[1] if state == "!!"}
        )
    unmerged_raw = _git_text(
        root,
        git,
        "diff",
        "--no-ext-diff",
        "--no-textconv",
        "--name-only",
        "--diff-filter=U",
        "-z",
    )
    unmerged_paths, _ = _path_list(unmerged_raw)
    return status_raw, status_paths, ignored_paths, unmerged_paths


def _overlaps(left: str, right: str) -> bool:
    return left == right or left.startswith(right + "/") or right.startswith(left + "/")


def recovery_snapshot(root: str, *, git) -> dict[str, Any]:
    """Read and validate one managed operation, returning its freshness token."""
    git_dir, _ = _record_path(root, git)
    record, raw_record = _read_record(root, git)
    native_kind = _operation_kind(git_dir)
    if record is None:
        return {
            "recovery_context": {
                "status": "unmanaged" if native_kind else "none",
                "kind": native_kind,
                "operation_id": None,
                "error_code": "unmanaged_operation" if native_kind else None,
                "error": "Git 操作没有由本服务创建的恢复记录" if native_kind else None,
            },
            "current_state_fingerprint": None,
        }
    if native_kind != record["kind"]:
        raise _RecoveryFailure("recovery_operation_mismatch", "恢复记录与当前 Git 操作不匹配或原操作已结束")

    head_oid = _git_text(root, git, "rev-parse", "--verify", "HEAD^{commit}").strip().lower()
    if not _HEX_OID.fullmatch(head_oid):
        raise _RecoveryFailure("head_unavailable", "无法核实恢复操作的当前 HEAD")
    symbolic = git(root, "--no-optional-locks", "symbolic-ref", "-q", "--no-recurse", "HEAD")
    if symbolic.returncode == 0:
        head_ref = symbolic.stdout.strip()
        if not head_ref.startswith("refs/heads/"):
            raise _RecoveryFailure("head_unavailable", "恢复操作 HEAD 指向不受支持的符号引用")
        head_branch: str | None = head_ref[len("refs/heads/"):]
    elif symbolic.returncode == 1:
        head_ref, head_branch = None, None
    else:
        raise _RecoveryFailure("head_unavailable", "无法核实恢复操作的 HEAD 引用")
    if head_branch not in {None, record["branch_name"]}:
        raise _RecoveryFailure("recovery_branch_mismatch", "恢复操作的当前分支与记录不匹配")
    checked_branch = _git_text(root, git, "check-ref-format", "--branch", record["branch_name"]).strip()
    if checked_branch != record["branch_name"]:
        raise _RecoveryFailure("recovery_record_invalid", "恢复记录中的分支名无效")
    branch_ref = f"refs/heads/{record['branch_name']}"
    direct_ref = git(root, "--no-optional-locks", "symbolic-ref", "-q", "--no-recurse", branch_ref)
    if direct_ref.returncode == 0:
        raise _RecoveryFailure("recovery_branch_mismatch", "恢复分支引用必须是直接引用，不能是符号引用")
    if direct_ref.returncode != 1:
        raise _RecoveryFailure("recovery_branch_mismatch", "无法核实恢复分支引用类型")
    branch_oid = _git_text(
        root,
        git,
        "rev-parse",
        "--verify",
        "--end-of-options",
        f"{branch_ref}^{{commit}}",
    ).strip().lower()
    if branch_oid != record["original_head_oid"]:
        raise _RecoveryFailure("recovery_branch_mismatch", "恢复操作期间原分支引用已变化")

    native_files: dict[str, bytes | None] = {}
    if record["kind"] == "merge":
        for name in ("MERGE_HEAD", "MERGE_MSG", "MERGE_MODE", "ORIG_HEAD", "MERGE_AUTOSTASH"):
            native_files[name] = _read_native_file(git_dir / name, root_guard=git_dir)
        if native_files["MERGE_AUTOSTASH"] is not None:
            raise _RecoveryFailure("recovery_operation_unsupported", "merge 启用了 autostash")
        merge_head = native_files["MERGE_HEAD"]
        try:
            merge_heads = merge_head.decode("ascii").splitlines() if merge_head is not None else []
        except UnicodeError:
            raise _RecoveryFailure("native_state_unsupported", "MERGE_HEAD 不是有效 ASCII") from None
        if merge_heads != [record["base_oid"]]:
            raise _RecoveryFailure("recovery_operation_mismatch", "MERGE_HEAD 与记录的固定 base 不一致")
        try:
            original_head = native_files["ORIG_HEAD"].decode("ascii").strip().lower()
        except (AttributeError, UnicodeError):
            raise _RecoveryFailure("native_state_unavailable", "merge 恢复缺少有效 ORIG_HEAD") from None
        if original_head != record["original_head_oid"]:
            raise _RecoveryFailure("recovery_operation_mismatch", "ORIG_HEAD 与记录的原始 HEAD 不一致")
        if native_files["MERGE_MSG"] is None:
            raise _RecoveryFailure("native_state_unavailable", "merge 恢复缺少 MERGE_MSG")
        try:
            merge_message = native_files["MERGE_MSG"].decode("utf-8").splitlines()[0].strip()
        except (UnicodeError, IndexError):
            raise _RecoveryFailure("native_state_unsupported", "merge message 格式不受支持") from None
        if merge_message != record["merge_message"]:
            raise _RecoveryFailure("recovery_message_changed", "merge message 已改变")
        if head_oid != record["original_head_oid"] or head_branch != record["branch_name"]:
            raise _RecoveryFailure("recovery_head_mismatch", "merge 期间 HEAD 未保持原分支与 OID")
    else:
        rebase_dir = git_dir / "rebase-merge"
        try:
            names = {entry.name for entry in os.scandir(rebase_dir)}
        except OSError:
            raise _RecoveryFailure("native_state_unavailable", "无法列出 rebase 元数据") from None
        allowed_names = set(_REBASE_FILES) | {
            "author-script",
            "drop_redundant_commits",
            "git-rebase-todo.backup",
            "no-reschedule-failed-exec",
            "rewritten-list",
        }
        if names - allowed_names:
            raise _RecoveryFailure("native_state_unsupported", "rebase 元数据包含未知控制文件")
        if "autostash" in names or "update-refs" in names:
            raise _RecoveryFailure("recovery_operation_unsupported", "rebase 启用了 autostash 或 updateRefs")
        for name in sorted(names):
            native_files[f"rebase-merge/{name}"] = _read_native_file(
                rebase_dir / name, root_guard=git_dir
            )
        required = ("head-name", "orig-head", "onto", "done", "git-rebase-todo")
        if any(native_files.get(f"rebase-merge/{name}") is None for name in required):
            raise _RecoveryFailure("native_state_unavailable", "rebase 元数据缺少固定边界或 todo")
        try:
            boundaries = {
                name: native_files[f"rebase-merge/{name}"].decode("utf-8").strip()
                for name in ("head-name", "orig-head", "onto")
            }
        except UnicodeError:
            raise _RecoveryFailure("native_state_unsupported", "rebase 边界不是有效 UTF-8") from None
        if (
            boundaries["head-name"] != f"refs/heads/{record['branch_name']}"
            or boundaries["orig-head"].lower() != record["original_head_oid"]
            or boundaries["onto"].lower() != record["base_oid"]
        ):
            raise _RecoveryFailure("recovery_operation_mismatch", "rebase 原分支、原始 HEAD 或 onto 与记录不一致")
        done = _parse_pick_commands(native_files["rebase-merge/done"] or b"")
        todo = _parse_pick_commands(native_files["rebase-merge/git-rebase-todo"] or b"")
        if done + todo != record["replay_oids"]:
            raise _RecoveryFailure("recovery_todo_changed", "rebase todo 与启动时记录的提交顺序不一致")
        ancestry = git(root, "--no-optional-locks", "merge-base", "--is-ancestor", record["base_oid"], head_oid)
        if ancestry.returncode != 0:
            raise _RecoveryFailure("recovery_head_mismatch", "rebase 当前 HEAD 未基于固定 base")

    common_text = _git_text(root, git, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
    try:
        common_dir = Path(common_text).resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        raise _RecoveryFailure("worktree_git_dir_unavailable", "无法解析仓库 common-dir") from None
    if not common_dir.is_dir():
        raise _RecoveryFailure("worktree_git_dir_unavailable", "仓库 common-dir 不可访问")
    status_raw, status_paths, ignored_paths, unmerged_paths = _snapshot_paths(
        root, git, record["affected_paths"]
    )
    all_paths = sorted(set(record["affected_paths"]) | set(status_paths) | set(ignored_paths))
    if len(all_paths) > _MAX_PATHS:
        raise _RecoveryFailure("recovery_snapshot_unsupported", "恢复状态路径数量超过上限")
    path_hashes: dict[str, Any] = {}
    total_bytes = 0
    for relative in all_paths:
        item = _hash_file(Path(root) / PurePosixPath(relative), _MAX_WORKTREE_FILE_BYTES, root_guard=Path(root))
        total_bytes += item.get("size", 0)
        if total_bytes > _MAX_TOTAL_WORKTREE_BYTES:
            raise _RecoveryFailure("recovery_snapshot_unsupported", "恢复状态总读取量超过上限")
        path_hashes[relative] = item
    native_hashes = {
        name: hashlib.sha256(value).hexdigest() if value is not None else None
        for name, value in sorted(native_files.items())
    }
    state = {
        "record_sha256": hashlib.sha256(raw_record or b"").hexdigest(),
        "operation_id": record["operation_id"],
        "kind": record["kind"],
        "repo_path": root,
        "git_dir": str(git_dir),
        "common_dir": str(common_dir),
        "head_oid": head_oid,
        "head_ref": head_ref,
        "branch_ref_oid": branch_oid,
        "head_file": _hash_file(git_dir / "HEAD", _MAX_NATIVE_FILE_BYTES, root_guard=git_dir),
        "index_file": _hash_file(git_dir / "index", _MAX_INDEX_BYTES, root_guard=git_dir),
        "native_hashes": native_hashes,
        "worktree_list_sha256": hashlib.sha256(
            _git_text(root, git, "worktree", "list", "--porcelain", "-z").encode("utf-8")
        ).hexdigest(),
        "status_sha256": hashlib.sha256(status_raw.encode("utf-8")).hexdigest(),
        "status_paths": status_paths,
        "ignored_paths": ignored_paths,
        "unmerged_paths": unmerged_paths,
        "path_hashes": path_hashes,
    }
    fingerprint = hashlib.sha256(
        json.dumps(state, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    context = {
        "status": "managed_in_progress",
        "operation_id": record["operation_id"],
        "kind": record["kind"],
        "branch_name": record["branch_name"],
        "original_head_oid": record["original_head_oid"],
        "base_oid": record["base_oid"],
        "current_head_oid": head_oid,
        "old_base_oid": record["old_base_oid"],
        "allowed_paths": record["affected_paths"],
        "conflict_paths": unmerged_paths,
        "untracked_paths": [path for state_code, path in _path_list(status_raw, status=True)[1] if state_code == "??"],
        "ignored_paths": ignored_paths,
        "detached_head": head_branch is None,
    }
    return {"recovery_context": context, "current_state_fingerprint": fingerprint}


def read_managed_operation(root: str, *, git) -> dict[str, Any]:
    record, _ = _read_record(root, git)
    if record is None:
        raise _RecoveryFailure("recovery_record_missing", "当前 worktree 没有受管理的恢复记录")
    return record


def _within_scope(path: str, allowed_paths: list[str]) -> bool:
    return any(_overlaps(path, allowed) for allowed in allowed_paths)


def validate_continue_worktree(root: str, record: dict[str, Any], *, git) -> None:
    status_raw, status_paths, ignored_paths, unmerged_paths = _snapshot_paths(
        root, git, record["affected_paths"]
    )
    if unmerged_paths:
        raise _RecoveryFailure("unmerged_index", "index 仍有未解决的冲突；先由调用方解决并暂存")
    entries = _path_list(status_raw, status=True)[1]
    for status, path in entries:
        if status == "??":
            if _within_scope(path, record["affected_paths"]):
                raise _RecoveryFailure("recovery_untracked_collision", "未跟踪文件与恢复路径重叠")
            continue
        if status[1] != " ":
            raise _RecoveryFailure("unstaged_resolution", "存在未暂存的跟踪文件更改；先由调用方解决并暂存")
        if status[0] != " " and not _within_scope(path, record["affected_paths"]):
            raise _RecoveryFailure("unrelated_staged_paths", "暂存区包含恢复范围以外的路径")
    if ignored_paths:
        raise _RecoveryFailure("recovery_ignored_collision", "忽略文件与恢复范围重叠")


def protected_worktree_snapshot(root: str, record: dict[str, Any], *, git) -> dict[str, Any]:
    status_raw, status_paths, ignored_paths, _ = _snapshot_paths(root, git, record["affected_paths"])
    entries = _path_list(status_raw, status=True)[1]
    allowed = record["affected_paths"]
    unrelated_tracked = [
        path
        for status, path in entries
        if status != "??" and not _within_scope(path, allowed)
    ]
    if unrelated_tracked:
        raise _RecoveryFailure("unrelated_dirty_paths", "工作区存在恢复范围以外的跟踪文件更改")
    if ignored_paths:
        raise _RecoveryFailure("recovery_ignored_collision", "忽略文件与 abort 恢复路径重叠")
    untracked = sorted({path for status, path in entries if status == "??"})
    collisions = [path for path in untracked if _within_scope(path, allowed)]
    if collisions:
        raise _RecoveryFailure("recovery_untracked_collision", "未跟踪文件可能与 abort 恢复内容冲突")
    file_hashes: dict[str, Any] = {}
    total_bytes = 0
    for path in untracked:
        item = _hash_file(Path(root) / PurePosixPath(path), _MAX_WORKTREE_FILE_BYTES, root_guard=Path(root))
        total_bytes += item.get("size", 0)
        if total_bytes > _MAX_TOTAL_WORKTREE_BYTES:
            raise _RecoveryFailure("recovery_snapshot_unsupported", "需保护的未跟踪内容超过读取上限")
        file_hashes[path] = item
    return {
        "untracked_paths": untracked,
        "file_hashes": file_hashes,
        "status_sha256": hashlib.sha256(status_raw.encode("utf-8")).hexdigest(),
    }


def verify_protected_worktree(root: str, record: dict[str, Any], before: dict[str, Any], *, git) -> bool:
    status_raw, _, ignored_paths, unmerged_paths = _snapshot_paths(root, git, record["affected_paths"])
    if unmerged_paths or ignored_paths:
        return False
    entries = _path_list(status_raw, status=True)[1]
    if any(status != "??" for status, _ in entries):
        return False
    untracked = sorted({path for status, path in entries if status == "??"})
    if untracked != before.get("untracked_paths"):
        return False
    total_bytes = 0
    current_hashes: dict[str, Any] = {}
    for path in untracked:
        item = _hash_file(Path(root) / PurePosixPath(path), _MAX_WORKTREE_FILE_BYTES, root_guard=Path(root))
        total_bytes += item.get("size", 0)
        if total_bytes > _MAX_TOTAL_WORKTREE_BYTES:
            return False
        current_hashes[path] = item
    return current_hashes == before.get("file_hashes")


def clear_managed_operation(root: str, record: dict[str, Any], *, git) -> None:
    current, raw = _read_record(root, git)
    if current is None or raw is None or current != record:
        raise _RecoveryFailure("recovery_record_changed", "恢复记录已消失或完整内容已变化")
    try:
        expected_raw = (
            json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        raise _RecoveryFailure("recovery_record_invalid", "无法核实待清除的恢复记录") from None
    if raw != expected_raw:
        raise _RecoveryFailure("recovery_record_changed", "恢复记录原始内容已变化")
    _, path = _record_path(root, git)
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    try:
        metadata = path.lstat()
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb", closefd=True) as stream:
            opened = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_nlink != 1
                or opened.st_dev != metadata.st_dev
                or opened.st_ino != metadata.st_ino
            ):
                raise _RecoveryFailure("recovery_record_changed", "恢复记录在清除前发生变化")
            current_raw = stream.read(_MAX_RECORD_BYTES + 1)
            after = os.fstat(stream.fileno())
            path_after = path.lstat()
            if (
                current_raw != expected_raw
                or after.st_dev != opened.st_dev
                or after.st_ino != opened.st_ino
                or after.st_size != opened.st_size
                or after.st_mtime_ns != opened.st_mtime_ns
                or after.st_ctime_ns != opened.st_ctime_ns
                or path_after.st_dev != opened.st_dev
                or path_after.st_ino != opened.st_ino
            ):
                raise _RecoveryFailure("recovery_record_changed", "恢复记录在清除前发生变化")
        path.unlink()
    except _RecoveryFailure:
        raise
    except OSError:
        raise _RecoveryFailure("recovery_record_cleanup_failed", "操作已验证，但无法清除 worktree 恢复记录") from None
