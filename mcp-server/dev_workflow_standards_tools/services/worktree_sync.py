"""Bounded worktree base-sync operations with OID preconditions and readback."""

from __future__ import annotations

import os
import re
import stat
import subprocess
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from pydantic import StrictBool

from typing import Any, Iterator

try:
    import fcntl
except ImportError:  # pragma: no cover - unsupported host; writes fail closed below
    fcntl = None  # type: ignore[assignment]

from ..infrastructure.paths import _validated_repo_path
from ..infrastructure.git import _valid_remote_branch
from . import create_branch
from . import worktree_recovery as recovery


_HEX_OID = re.compile(r"^(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})$")
_REMOTE_NAME = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._/-]*$")
_GIT_CONFIG_REDIRECT = re.compile(r"GIT_CONFIG_(?:KEY|VALUE)_\d+$")
_OPERATION_FLAGS: tuple[tuple[str, str], ...] = (
    ("merge", "MERGE_HEAD"),
    ("rebase_merge", "rebase-merge"),
    ("rebase_apply", "rebase-apply"),
    ("cherry_pick", "CHERRY_PICK_HEAD"),
    ("revert", "REVERT_HEAD"),
    ("sequencer", "sequencer"),
    ("bisect", "BISECT_LOG"),
)
_REDIRECTING_GIT_ENV = set(create_branch._REDIRECTING_GIT_ENV)


class _SyncFailure(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _git(root: str, *args: str):
    try:
        return create_branch._git(root, *args)
    except create_branch._GitFailure as exc:
        raise _SyncFailure(exc.code, exc.message) from exc
    except (OSError, UnicodeError, TypeError, ValueError) as exc:
        raise _SyncFailure("git_unavailable", "无法安全读取或运行 Git") from exc


def _network_git(root: str, *args: str):
    try:
        return subprocess.run(
            ["git", "--no-lazy-fetch", *args],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            check=False,
            timeout=120,
            env={**os.environ, "GIT_NO_LAZY_FETCH": "1", "GIT_TERMINAL_PROMPT": "0"},
        )
    except subprocess.TimeoutExpired as exc:
        raise _SyncFailure("git_timeout", "remote Git 操作超时；应先只读检查仓库状态") from exc
    except (OSError, UnicodeError, TypeError, ValueError) as exc:
        raise _SyncFailure("git_unavailable", "无法安全启动 remote Git 操作") from exc


def _redirecting_environment() -> bool:
    return any(name in os.environ for name in _REDIRECTING_GIT_ENV) or any(
        _GIT_CONFIG_REDIRECT.fullmatch(name) for name in os.environ
    )


def _root(repo_path: str) -> str:
    if _redirecting_environment():
        raise _SyncFailure("git_environment_redirected", "检测到可能重定向仓库、对象库或 index 的 Git 环境变量")
    try:
        root, error = _validated_repo_path(repo_path)
    except (OSError, UnicodeError, TypeError, ValueError):
        raise _SyncFailure("invalid_repo_path", "无法安全解析 repo_path") from None
    if error or root is None:
        raise _SyncFailure("invalid_repo_path", "repo_path 必须精确指向可访问的 Git 仓库根目录")
    return root


def _oid(value: Any, field: str, *, required: bool = False) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str) or not _HEX_OID.fullmatch(value):
        raise _SyncFailure("invalid_oid", f"{field} 必须为 40 或 64 位十六进制 OID" if value is not None else f"{field} 不能为空")
    return value.lower()


def _remote_name(root: str, remote: Any) -> str:
    if not isinstance(remote, str) or not remote or not _REMOTE_NAME.fullmatch(remote):
        raise _SyncFailure("invalid_remote", "remote 必须是已配置 remote 的名称，不接受 URL")
    configured = _git(root, "remote")
    if configured.returncode != 0:
        raise _SyncFailure("remote_state_unavailable", "无法核实已配置的 remote 名称")
    if remote not in configured.stdout.splitlines():
        raise _SyncFailure("remote_not_configured", "指定 remote 未配置")
    return remote


def _branch_name(value: Any, field: str = "branch_name") -> str:
    if not isinstance(value, str) or not _valid_remote_branch(value):
        raise _SyncFailure("invalid_branch_name", f"{field} 不是有效分支名")
    return value


def _validated_branch(root: str, value: Any, field: str = "branch_name") -> str:
    name = _branch_name(value, field)
    checked = _git(root, "check-ref-format", "--branch", name)
    if checked.returncode != 0:
        raise _SyncFailure("invalid_branch_name", f"{field} 不是有效分支名")
    return name


def _capture_oid(root: str, rev: str, *, code: str = "repository_state_unavailable") -> str:
    result = _git(root, "rev-parse", "--verify", "--end-of-options", f"{rev}^{{commit}}")
    if result.returncode != 0:
        raise _SyncFailure(code, "无法解析指定的 commit OID")
    oid = result.stdout.strip().lower()
    if not _HEX_OID.fullmatch(oid):
        raise _SyncFailure(code, "Git 返回了无效 commit OID")
    return oid


def _resolve_ref(root: str, value: Any) -> tuple[str, str]:
    """Resolve only local branch refs, remote-tracking refs, or a full commit OID."""
    if not isinstance(value, str) or not value:
        raise _SyncFailure("invalid_base_ref", "base_ref 必须是本地分支、remote-tracking ref 或完整 commit OID")
    if _HEX_OID.fullmatch(value):
        oid = value.lower()
        return oid, _capture_oid(root, oid, code="base_oid_unavailable")

    if value.startswith("refs/heads/") or value.startswith("refs/remotes/"):
        ref = value
    else:
        ref = f"refs/heads/{value}"
    checked = _git(root, "check-ref-format", ref)
    if checked.returncode != 0:
        raise _SyncFailure("invalid_base_ref", "base_ref 必须是 refs/heads、refs/remotes 下的准确 ref 或完整 OID")
    symbolic = _git(root, "symbolic-ref", "-q", "--no-recurse", ref)
    if symbolic.returncode == 0:
        raise _SyncFailure("symbolic_ref_rejected", "base_ref 不能是符号引用")
    if symbolic.returncode not in {1}:
        raise _SyncFailure("base_ref_unavailable", "无法核实 base_ref")
    shown = _git(root, "show-ref", "--verify", "--quiet", ref)
    if shown.returncode == 1:
        raise _SyncFailure("base_ref_missing", "指定 base_ref 不存在")
    if shown.returncode != 0:
        raise _SyncFailure("base_ref_unavailable", "无法读取指定 base_ref")
    resolved = _capture_oid(root, ref, code="base_ref_unavailable")
    return ref, resolved


def _head(root: str) -> tuple[str, str | None, str | None]:
    oid = _capture_oid(root, "HEAD", code="head_unavailable")
    symbolic = _git(root, "symbolic-ref", "-q", "--no-recurse", "HEAD")
    if symbolic.returncode == 0:
        ref = symbolic.stdout.strip()
        if not ref.startswith("refs/heads/"):
            raise _SyncFailure("head_unavailable", "HEAD 未指向普通本地分支")
        return oid, ref[len("refs/heads/"):], ref
    if symbolic.returncode == 1:
        return oid, None, None
    raise _SyncFailure("head_unavailable", "无法核实 HEAD 分支身份")


def _status(root: str) -> tuple[bool, list[str]]:
    result = _git(root, "--no-optional-locks", "status", "--porcelain=v1", "--untracked-files=all")
    if result.returncode != 0:
        raise _SyncFailure("worktree_state_unavailable", "无法核实工作区状态")
    lines = result.stdout.splitlines()
    return bool(lines), lines


def _operation_flags(root: str) -> dict[str, bool]:
    flags: dict[str, bool] = {}
    for key, marker in _OPERATION_FLAGS:
        path_result = _git(root, "rev-parse", "--git-path", marker)
        if path_result.returncode != 0:
            raise _SyncFailure("operation_state_unavailable", "无法检查 Git 操作状态")
        path = Path(path_result.stdout.strip())
        if not path.is_absolute():
            path = Path(root) / path
        try:
            path.lstat()
            flags[key] = True
        except FileNotFoundError:
            flags[key] = False
        except OSError:
            raise _SyncFailure("operation_state_unavailable", "无法检查 Git 操作状态") from None
    return flags


def _locked_worktree(root: str) -> bool:
    result = _git(root, "worktree", "list", "--porcelain", "-z")
    if result.returncode != 0:
        raise _SyncFailure("worktree_state_unavailable", "无法核实 worktree 锁定状态")
    expected = str(Path(root).resolve())
    records: list[list[str]] = [[]]
    for field in result.stdout.split("\0"):
        if not field:
            if records[-1]:
                records.append([])
        else:
            records[-1].append(field)
    for record in records:
        if f"worktree {expected}" in record:
            return any(item == "locked" or item.startswith("locked ") for item in record)
    raise _SyncFailure("worktree_state_unavailable", "Git worktree 列表中找不到目标目录")


def _metadata_locked(root: str, branch_name: str | None) -> bool:
    names = ["HEAD.lock", "index.lock"]
    if branch_name:
        names.append(f"refs/heads/{branch_name}.lock")
    for name in names:
        result = _git(root, "rev-parse", "--git-path", name)
        if result.returncode != 0:
            raise _SyncFailure("repository_state_unavailable", "无法检查 Git 元数据锁")
        path = Path(result.stdout.strip())
        if not path.is_absolute():
            path = Path(root) / path
        try:
            path.lstat()
            return True
        except FileNotFoundError:
            continue
        except OSError:
            raise _SyncFailure("repository_state_unavailable", "无法检查 Git 元数据锁") from None
    return False


def _unmerged_index(root: str) -> bool:
    result = _git(root, "ls-files", "--unmerged", "-z")
    if result.returncode != 0:
        raise _SyncFailure("index_state_unavailable", "无法检查 index 冲突状态")
    return bool(result.stdout)


def _state(root: str) -> dict[str, Any]:
    head_oid, branch_name, _ = _head(root)
    dirty, status_lines = _status(root)
    flags = _operation_flags(root)
    unmerged = _unmerged_index(root)
    locked = _locked_worktree(root)
    metadata_locked = _metadata_locked(root, branch_name)
    return {
        "head_oid": head_oid,
        "branch_name": branch_name,
        "detached": branch_name is None,
        "dirty": dirty,
        "status_lines": status_lines,
        "operation_flags": flags,
        "operation_in_progress": any(flags.values()),
        "unmerged_index": unmerged,
        "locked": locked or metadata_locked,
        "worktree_locked": locked,
        "metadata_locked": metadata_locked,
    }


def _check_writable_state(root: str, branch_name: str) -> dict[str, Any]:
    state = _state(root)
    if state["detached"]:
        raise _SyncFailure("detached_head", "当前 HEAD 为 detached，拒绝修改")
    if state["branch_name"] != branch_name:
        raise _SyncFailure("branch_mismatch", "当前检出分支与 branch_name 不一致")
    if state["locked"]:
        raise _SyncFailure("worktree_locked", "目标 worktree 已锁定")
    if state["operation_in_progress"]:
        raise _SyncFailure("operation_in_progress", "存在未完成的 Git 操作")
    if state["unmerged_index"]:
        raise _SyncFailure("unmerged_index", "index 含有未解决的冲突项")
    if state["dirty"]:
        raise _SyncFailure("dirty_worktree", "工作区存在暂存、未暂存或未跟踪内容")
    try:
        create_branch._check_worktree_state(root, branch_name)
    except create_branch._GitFailure as exc:
        raise _SyncFailure(exc.code, exc.message) from exc
    return state


def _verify_head(root: str, expected: str) -> tuple[str, str | None]:
    actual, branch, _ = _head(root)
    if actual != expected:
        raise _SyncFailure("stale_head", "执行前 HEAD OID 已变化")
    return actual, branch


def _read_remote_branch_oid(root: str, remote: str, branch_name: str) -> str | None:
    result = _network_git(root, "ls-remote", "--exit-code", "--refs", remote, f"refs/heads/{branch_name}")
    if result.returncode == 2 and not result.stdout.strip():
        return None
    if result.returncode != 0:
        raise _SyncFailure("publication_check_failed", "无法通过指定 remote 核实需求分支发布状态")
    rows = [line.split("\t", 1) for line in result.stdout.splitlines()]
    matches = [row for row in rows if len(row) == 2 and row[1] == f"refs/heads/{branch_name}"]
    if len(matches) != 1 or not _HEX_OID.fullmatch(matches[0][0]):
        raise _SyncFailure("publication_check_failed", "remote 返回了缺失或不明确的分支状态")
    return matches[0][0].lower()


def _read_ref_oid(root: str, ref: str, *, missing_ok: bool) -> str | None:
    symbolic = _git(root, "symbolic-ref", "-q", "--no-recurse", ref)
    if symbolic.returncode == 0:
        raise _SyncFailure("symbolic_ref_rejected", "目标引用是符号引用")
    if symbolic.returncode != 1:
        raise _SyncFailure("ref_state_unavailable", "无法核实目标引用类型")
    shown = _git(root, "show-ref", "--verify", "--quiet", ref)
    if shown.returncode == 1:
        if missing_ok:
            return None
        raise _SyncFailure("ref_missing", "目标引用不存在")
    if shown.returncode != 0:
        raise _SyncFailure("ref_state_unavailable", "无法读取目标引用")
    return _capture_oid(root, ref, code="ref_state_unavailable")


def _relation(root: str, head_oid: str, base_oid: str) -> tuple[str, str | None, int, int]:
    merge_base = _git(root, "merge-base", "--all", head_oid, base_oid)
    if merge_base.returncode == 0:
        bases = [line.strip().lower() for line in merge_base.stdout.splitlines() if line.strip()]
        merge_base_oid = bases[0] if len(bases) == 1 and _HEX_OID.fullmatch(bases[0]) else None
    elif merge_base.returncode == 1:
        merge_base_oid = None
    else:
        raise _SyncFailure("history_state_unavailable", "无法读取提交图关系")
    counts = _git(root, "rev-list", "--left-right", "--count", f"{head_oid}...{base_oid}")
    if counts.returncode != 0:
        raise _SyncFailure("history_state_unavailable", "无法统计 head/base 提交差异")
    pair = counts.stdout.strip().split()
    if len(pair) != 2 or not all(value.isdecimal() for value in pair):
        raise _SyncFailure("history_state_unavailable", "Git 返回了无效 ahead/behind 统计")
    ahead, behind = int(pair[0]), int(pair[1])
    if behind == 0:
        status = "up_to_date"
    elif ahead == 0:
        status = "fast_forwardable"
    else:
        status = "diverged"
    return status, merge_base_oid, ahead, behind


def _common_dir(root: str) -> Path:
    result = _git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if result.returncode != 0:
        raise _SyncFailure("common_dir_unavailable", "无法核实 Git common-dir")
    try:
        common = Path(result.stdout.strip()).resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        raise _SyncFailure("common_dir_unavailable", "无法解析 Git common-dir") from None
    if not common.is_dir():
        raise _SyncFailure("common_dir_unavailable", "Git common-dir 不可访问")
    return common


@contextmanager
def _sync_lock(root: str) -> Iterator[None]:
    if fcntl is None:
        raise _SyncFailure("sync_lock_unavailable", "当前平台不支持 worktree 同步协作锁")
    common = _common_dir(root)
    lock_path = common / ".worktree-base-sync.lock"
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError:
        raise _SyncFailure("sync_lock_unavailable", "无法建立 worktree 同步协作锁") from None
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise _SyncFailure("sync_lock_unavailable", "worktree 同步协作锁不是安全的普通文件")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise _SyncFailure("sync_busy", "另一个遵守协作锁的同步操作正在运行") from None
        yield
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(descriptor)


def _timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _audit_result(root: str | None, *, status: str, error_code: str | None = None, error: str | None = None, **values: Any) -> dict[str, Any]:
    return {
        "ok": error_code is None,
        "repo_path": root,
        "status": status,
        "error_code": error_code,
        "error": error,
        "observed_at": _timestamp(),
        **values,
    }


def _recovery_fields(root: str) -> dict[str, Any]:
    try:
        return recovery.recovery_snapshot(root, git=_git)
    except recovery._RecoveryFailure as exc:
        return {
            "recovery_context": {
                "status": "needs_review",
                "kind": None,
                "operation_id": None,
                "error_code": exc.code,
                "error": exc.message,
            },
            "current_state_fingerprint": None,
        }


def _begin_recovery_record(root: str, **values: Any) -> dict[str, Any]:
    try:
        return recovery.begin_managed_operation(root, git=_git, **values)
    except recovery._RecoveryFailure as exc:
        raise _SyncFailure(exc.code, exc.message) from None


def _recovery_failure(exc: recovery._RecoveryFailure) -> _SyncFailure:
    return _SyncFailure(exc.code, exc.message)


def audit_worktree_base_sync(repo_path: str, base_ref: str, remote: str | None = None) -> dict[str, Any]:
    """Read local HEAD/base relationships and optional live publication status; never fetches."""
    root: str | None = None
    base_oid: str | None = None
    state: dict[str, Any] = {}
    network_accessed = False
    publication_remote_oid: str | None = None
    publication_status = "unknown"
    recovery_fields: dict[str, Any] = {
        "recovery_context": {"status": "unknown", "operation_id": None},
        "current_state_fingerprint": None,
    }
    try:
        root = _root(repo_path)
        state = _state(root)
        recovery_fields = _recovery_fields(root)
        _, base_oid = _resolve_ref(root, base_ref)
        status, merge_base_oid, ahead_by, behind_by = _relation(root, state["head_oid"], base_oid)
        if remote is not None:
            remote_name = _remote_name(root, remote)
            if state["branch_name"] is None:
                raise _SyncFailure("detached_head", "detached HEAD 没有可查询的需求分支发布状态")
            network_accessed = True
            publication_remote_oid = _read_remote_branch_oid(root, remote_name, state["branch_name"])
            publication_status = "published" if publication_remote_oid else "unpublished"
        if (
            state["dirty"] or state["operation_in_progress"] or state["unmerged_index"]
            or state["locked"] or state["detached"]
            or recovery_fields["recovery_context"].get("status") != "none"
        ):
            status = "blocked"
        return _audit_result(
            root,
            status=status,
            base_ref=base_ref,
            head_oid=state["head_oid"],
            branch_name=state["branch_name"],
            base_oid=base_oid,
            merge_base_oid=merge_base_oid,
            ahead_by=ahead_by,
            behind_by=behind_by,
            dirty=state["dirty"],
            dirty_paths_count=len(state["status_lines"]),
            detached=state["detached"],
            locked=state["locked"],
            worktree_locked=state["worktree_locked"],
            metadata_locked=state["metadata_locked"],
            unmerged_index=state["unmerged_index"],
            operation_in_progress=state["operation_in_progress"],
            operation_flags=state["operation_flags"],
            publication_status=publication_status,
            publication_remote_oid=publication_remote_oid,
            publication_remote=remote,
            network_accessed=network_accessed,
            **recovery_fields,
        )
    except _SyncFailure as exc:
        if root is not None:
            recovery_fields = _recovery_fields(root)
        return _audit_result(
            root,
            status="unknown",
            error_code=exc.code,
            error=exc.message,
            base_ref=base_ref,
            head_oid=state.get("head_oid"),
            branch_name=state.get("branch_name"),
            base_oid=base_oid,
            merge_base_oid=None,
            ahead_by=None,
            behind_by=None,
            dirty=state.get("dirty"),
            dirty_paths_count=len(state.get("status_lines", [])),
            detached=state.get("detached"),
            locked=state.get("locked"),
            worktree_locked=state.get("worktree_locked"),
            metadata_locked=state.get("metadata_locked"),
            unmerged_index=state.get("unmerged_index"),
            operation_in_progress=state.get("operation_in_progress"),
            operation_flags=state.get("operation_flags", {}),
            publication_status="unknown",
            publication_remote_oid=publication_remote_oid,
            publication_remote=remote,
            network_accessed=network_accessed,
            **recovery_fields,
        )


def fetch_repository_branch(repo_path: str, remote: str, branch_name: str) -> dict[str, Any]:
    """Fetch one remote branch through FETCH_HEAD, then CAS its tracking ref without rewinds."""
    root: str | None = None
    ref: str | None = None
    branch = str(branch_name)
    remote_name = remote
    before_oid: str | None = None
    fetched_oid: str | None = None
    network_accessed = False
    fetch_started = False
    fetch_head_written: bool | None = False
    tracking_update_started = False
    tracking_ref_updated: bool | None = False
    try:
        root = _root(repo_path)
        branch = _validated_branch(root, branch_name)
        remote_name = _remote_name(root, remote)
        ref = f"refs/remotes/{remote_name}/{branch}"
        with _sync_lock(root):
            before_oid = _read_ref_oid(root, ref, missing_ok=True)
            fetch_started = True
            network_accessed = True
            fetched = _network_git(
                root,
                "fetch",
                "--atomic",
                "--quiet",
                "--no-tags",
                "--no-prune",
                "--no-prune-tags",
                "--no-auto-maintenance",
                "--no-recurse-submodules",
                "--refmap=",
                remote_name,
                f"refs/heads/{branch}",
            )
            if fetched.returncode != 0:
                fetch_head_written = None
                tracking_ref_updated = False
                return {
                    "ok": False,
                    "repo_path": root,
                    "remote": remote_name,
                    "branch_name": branch,
                    "fetch_ref": ref,
                    "previous_oid": before_oid,
                    "fetched_oid": None,
                    "fetched_at": None,
                    "fetch_head_written": None,
                    "objects_may_be_downloaded": True,
                    "tracking_ref_updated": False,
                    "network_accessed": network_accessed,
                    "needs_review": True,
                    "error_code": "fetch_failed",
                    "error": "固定远端分支 fetch 失败；FETCH_HEAD 或对象库可能已变化，目标跟踪引用未指定给 fetch 更新",
                }
            fetch_head_written = True
            fetched_oid = _capture_oid(root, "FETCH_HEAD", code="fetch_readback_failed")
            if before_oid is not None and not _merge_base_ancestor(root, before_oid, fetched_oid):
                return {
                    "ok": False,
                    "repo_path": root,
                    "remote": remote_name,
                    "branch_name": branch,
                    "fetch_ref": ref,
                    "previous_oid": before_oid,
                    "fetched_oid": fetched_oid,
                    "fetched_at": None,
                    "fetch_head_written": True,
                    "objects_may_be_downloaded": True,
                    "tracking_ref_updated": False,
                    "network_accessed": network_accessed,
                    "needs_review": True,
                    "error_code": "fetch_rewind_rejected",
                    "error": "远端 tip 不是既有 remote-tracking tip 的后代；已保留 FETCH_HEAD/对象，未更新跟踪引用",
                }
            format_result = _git(root, "rev-parse", "--show-object-format")
            if format_result.returncode != 0:
                raise _SyncFailure("object_format_unavailable", "无法确定 Git 对象格式以安全比较引用")
            object_format = format_result.stdout.strip()
            if object_format == "sha1":
                zero_oid = "0" * 40
            elif object_format == "sha256":
                zero_oid = "0" * 64
            else:
                raise _SyncFailure("object_format_unavailable", "Git 返回了不支持的对象格式")
            expected_old_oid = before_oid or zero_oid
            tracking_update_started = True
            tracking_ref_updated = None
            updated = _git(root, "update-ref", "--no-deref", ref, fetched_oid, expected_old_oid)
            after_oid = _read_ref_oid(root, ref, missing_ok=True)
            tracking_ref_updated = after_oid == fetched_oid
            if updated.returncode != 0 or not tracking_ref_updated:
                return {
                    "ok": False,
                    "repo_path": root,
                    "remote": remote_name,
                    "branch_name": branch,
                    "fetch_ref": ref,
                    "previous_oid": before_oid,
                    "fetched_oid": fetched_oid,
                    "fetched_at": None,
                    "fetch_head_written": True,
                    "objects_may_be_downloaded": True,
                    "tracking_ref_updated": tracking_ref_updated,
                    "network_accessed": network_accessed,
                    "needs_review": True,
                    "error_code": "fetch_ref_update_failed",
                    "error": "fetch 已取得对象，但 remote-tracking 引用的条件更新或回读未通过；先核对引用状态",
                }
            return {
                "ok": True,
                "repo_path": root,
                "remote": remote_name,
                "branch_name": branch,
                "fetch_ref": ref,
                "previous_oid": before_oid,
                "fetched_oid": fetched_oid,
                "fetched_at": _timestamp(),
                "fetch_head_written": True,
                "objects_may_be_downloaded": True,
                "tracking_ref_updated": True,
                "network_accessed": network_accessed,
                "needs_review": False,
                "error_code": None,
                "error": None,
            }
    except _SyncFailure as exc:
        return {
            "ok": False,
            "repo_path": root,
            "remote": remote_name,
            "branch_name": branch,
            "fetch_ref": ref,
            "previous_oid": before_oid,
            "fetched_oid": fetched_oid,
            "fetched_at": None,
            "fetch_head_written": fetch_head_written,
            "objects_may_be_downloaded": fetch_started,
            "tracking_ref_updated": tracking_ref_updated,
            "network_accessed": network_accessed,
            "needs_review": fetch_started or tracking_update_started,
            "error_code": exc.code,
            "error": exc.message,
        }


def _assert_expected_oid(actual: str, expected: str | None, field: str) -> None:
    normalized = _oid(expected, field, required=True) if expected is not None else None
    if normalized is not None and actual != normalized:
        raise _SyncFailure("stale_oid", f"当前 {field} 与预期 OID 不匹配")


def _preflight(root: str, branch_name: str, base_ref: str, expected_head_oid: str | None, expected_base_oid: str | None) -> dict[str, Any]:
    state = _check_writable_state(root, branch_name)
    if _branch_ref_oid(root, branch_name) != state["head_oid"]:
        raise _SyncFailure("branch_ref_changed", "当前直接分支引用与 HEAD 不匹配")
    _assert_expected_oid(state["head_oid"], expected_head_oid, "expected_head_oid")
    resolved_ref, base_oid = _resolve_ref(root, base_ref)
    _assert_expected_oid(base_oid, expected_base_oid, "expected_base_oid")
    return {**state, "base_ref": resolved_ref, "base_oid": base_oid}


def _common_result(root: str | None, branch_name: str, base_ref: Any, **values: Any) -> dict[str, Any]:
    return {
        "ok": False,
        "repo_path": root,
        "branch_name": branch_name,
        "base_ref": base_ref,
        "error_code": None,
        "error": None,
        "needs_review": False,
        **values,
    }


def _merge_base_ancestor(root: str, ancestor: str, descendant: str) -> bool:
    result = _git(root, "merge-base", "--is-ancestor", ancestor, descendant)
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    raise _SyncFailure("history_state_unavailable", "无法核实提交祖先关系")

def _reject_branch_merge_options(root: str, branch_name: str) -> None:
    result = _git(root, "config", "--null", "--get-all", f"branch.{branch_name}.mergeOptions")
    if result.returncode == 1 and not result.stdout:
        return
    if result.returncode != 0:
        raise _SyncFailure("merge_options_unavailable", "无法核实当前分支的 mergeOptions 配置")
    if result.stdout:
        raise _SyncFailure("merge_options_rejected", "当前分支配置了 mergeOptions，可能改变普通基线合并语义")


def _branch_ref_oid(root: str, branch_name: str) -> str:
    ref = f"refs/heads/{branch_name}"
    symbolic = _git(root, "symbolic-ref", "-q", "--no-recurse", ref)
    if symbolic.returncode == 0:
        raise _SyncFailure("branch_state_unsupported", "当前需求分支必须是直接引用")
    if symbolic.returncode != 1:
        raise _SyncFailure("branch_state_unavailable", "无法核实需求分支引用类型")
    return _capture_oid(root, ref, code="branch_state_unavailable")


def _clean_readback(root: str) -> bool:
    dirty, _ = _status(root)
    return not dirty and not _unmerged_index(root) and not any(_operation_flags(root).values())


def _conflict_paths(root: str) -> list[str]:
    result = _git(root, "diff", "--no-ext-diff", "--no-textconv", "--name-only", "--diff-filter=U", "-z")
    if result.returncode != 0:
        raise _SyncFailure("conflict_readback_failed", "无法读取冲突路径")
    return [path for path in result.stdout.split("\0") if path]

def _paths_from_git(root: str, *args: str) -> set[str]:
    result = _git(root, *args)
    if result.returncode != 0:
        raise _SyncFailure("path_state_unavailable", "无法核实提交将影响的路径")
    return {path for path in result.stdout.split("\0") if path}


def _ignored_path_collisions(
    root: str,
    head_oid: str,
    base_oid: str,
    old_base_oid: str | None = None,
    *,
    include_replay: bool = True,
) -> list[str]:
    """Protect ignored user files only where the planned tree transition touches them."""
    ignored = _paths_from_git(root, "ls-files", "--others", "--ignored", "--exclude-standard", "-z")
    if not ignored:
        return []
    changed = _paths_from_git(root, "diff", "--no-ext-diff", "--no-textconv", "--name-only", "--no-renames", "-z", head_oid, base_oid)
    if include_replay:
        replay_boundary = old_base_oid or base_oid
        commits_result = _git(root, "rev-list", "--reverse", "--topo-order", f"{replay_boundary}..{head_oid}")
        if commits_result.returncode != 0:
            raise _SyncFailure("path_state_unavailable", "无法核实 rebase 将重放的提交路径")
        for commit_oid in commits_result.stdout.splitlines():
            if commit_oid:
                changed.update(_paths_from_git(
                    root, "diff-tree", "--no-ext-diff", "--no-textconv", "--root", "--no-commit-id", "--name-only", "--no-renames", "-m", "-r", "-z", commit_oid
                ))

    def overlaps(left: str, right: str) -> bool:
        return left == right or left.startswith(right + "/") or right.startswith(left + "/")

    return sorted({ignored_path for ignored_path in ignored if any(overlaps(ignored_path, path) for path in changed)})


def _planned_replay_oids(root: str, head_oid: str, base_oid: str, old_base_oid: str | None) -> list[str]:
    boundary = old_base_oid or base_oid
    result = _git(root, "rev-list", "--reverse", "--topo-order", "--no-merges", f"{boundary}..{head_oid}")
    if result.returncode != 0:
        raise _SyncFailure("replay_plan_unavailable", "无法核实 rebase 的简单提交重放序列")
    commits = result.stdout.splitlines()
    if len(commits) > 20_000 or any(not _HEX_OID.fullmatch(commit) for commit in commits):
        raise _SyncFailure("replay_plan_unsupported", "rebase 提交重放序列无效或超过数量上限")
    return [commit.lower() for commit in commits]


def _recovery_paths(
    root: str,
    head_oid: str,
    base_oid: str,
    replay_oids: list[str] | None = None,
) -> list[str]:
    changed = _paths_from_git(
        root,
        "diff",
        "--no-ext-diff",
        "--no-textconv",
        "--name-only",
        "--no-renames",
        "-z",
        head_oid,
        base_oid,
    )
    for commit_oid in replay_oids or []:
        changed.update(
            _paths_from_git(
                root,
                "diff-tree",
                "--no-ext-diff",
                "--no-textconv",
                "--root",
                "--no-commit-id",
                "--name-only",
                "--no-renames",
                "-r",
                "-z",
                commit_oid,
            )
        )
    if len(changed) > 4096:
        raise _SyncFailure("recovery_scope_unsupported", "同步影响路径超过恢复记录的数量上限")
    return sorted(changed)


def rebase_repository_branch(
    repo_path: str,
    branch_name: str,
    base_branch: str,
    expected_head_oid: str | None = None,
    expected_base_oid: str | None = None,
    old_base_oid: str | None = None,
    remote: str = "origin",
) -> dict[str, Any]:
    """Rebase only an unpublished local branch after live publication and OID checks."""
    root: str | None = None
    network_accessed = False
    action_started = False
    record_created = False
    action_succeeded: bool | None = None
    record: dict[str, Any] | None = None
    initial: dict[str, Any] = {}
    collisions: list[str] = []
    result = _common_result(
        None,
        str(branch_name),
        base_branch,
        rebased=False,
        action_started=False,
        conflict_paths=[],
        ignored_path_collisions=[],
    )
    try:
        root = _root(repo_path)
        branch = _validated_branch(root, branch_name)
        remote_name = _remote_name(root, remote)
        expected_head = _oid(expected_head_oid, "expected_head_oid")
        expected_base = _oid(expected_base_oid, "expected_base_oid")
        result.update(repo_path=root, branch_name=branch, remote=remote_name)
        with _sync_lock(root):
            initial = _preflight(root, branch, base_branch, expected_head, expected_base)
            old_boundary = _oid(old_base_oid, "old_base_oid")
            if old_boundary is not None:
                old_boundary = _capture_oid(root, old_boundary, code="old_base_unavailable")
                if not _merge_base_ancestor(root, old_boundary, initial["head_oid"]):
                    raise _SyncFailure("old_base_not_ancestor", "old_base_oid 必须是当前 head 的祖先")
                if old_boundary == initial["head_oid"]:
                    raise _SyncFailure("empty_rebase_range", "old_base_oid 与当前 head 相同，没有可验证的子需求提交")

            network_accessed = True
            result["network_accessed"] = True
            published_oid = _read_remote_branch_oid(root, remote_name, branch)
            result["publication_remote_oid"] = published_oid
            if published_oid is not None:
                raise _SyncFailure("published_branch", "remote 上存在同名需求分支；禁止 rebase")

            # Re-read branch, worktree, head and base immediately before rewriting history.
            current = _preflight(root, branch, initial["base_ref"], initial["head_oid"], initial["base_oid"])
            if current["head_oid"] != initial["head_oid"] or current["base_oid"] != initial["base_oid"]:
                raise _SyncFailure("stale_oid", "执行前 head/base OID 已变化")
            if old_boundary is not None and not _merge_base_ancestor(root, old_boundary, current["head_oid"]):
                raise _SyncFailure("old_base_not_ancestor", "old_base_oid 不再是当前 head 的祖先")
            collisions = _ignored_path_collisions(
                root, current["head_oid"], current["base_oid"], old_boundary
            )
            if collisions:
                result["ignored_path_collisions"] = collisions
                raise _SyncFailure("ignored_path_collision", "rebase 目标会覆盖被忽略的用户文件；工具拒绝改写")
            published_oid = _read_remote_branch_oid(root, remote_name, branch)
            result["publication_remote_oid"] = published_oid
            if published_oid is not None:
                raise _SyncFailure("published_branch", "remote 上存在同名需求分支；禁止 rebase")

            replay_oids = _planned_replay_oids(root, initial["head_oid"], initial["base_oid"], old_boundary)
            affected_paths = _recovery_paths(
                root, initial["head_oid"], initial["base_oid"], replay_oids
            )
            record_created = True
            record = _begin_recovery_record(
                root,
                kind="rebase",
                branch_name=branch,
                original_head_oid=initial["head_oid"],
                base_oid=initial["base_oid"],
                base_ref=initial["base_ref"],
                remote=remote_name,
                old_base_oid=old_boundary,
                merge_message="",
                affected_paths=affected_paths,
                replay_oids=replay_oids,
            )
            result["operation_id"] = record["operation_id"]

            args = [
                "rebase",
                "--no-autostash",
                "--no-update-refs",
                "--no-rebase-merges",
                "--no-autosquash",
                "--reapply-cherry-picks",
                "--keep-empty",
                "--no-fork-point",
            ]
            if old_boundary is None:
                args.append(initial["base_oid"])
            else:
                args.extend(["--onto", initial["base_oid"], old_boundary])
            action_started = True
            result["action_started"] = True
            rebased = _git(root, *args)
            action_succeeded = rebased.returncode == 0
            if not action_succeeded:
                paths = _conflict_paths(root)
                state_now = _state(root)
                conflict = state_now["operation_in_progress"] or state_now["unmerged_index"] or bool(paths)
                result.update(
                    head_oid_before=initial["head_oid"],
                    head_oid_after=state_now["head_oid"],
                    base_oid=initial["base_oid"],
                    old_base_oid=old_boundary,
                    conflict_paths=paths,
                    rebased=False,
                    needs_review=True,
                    error_code="rebase_conflict" if conflict else "rebase_failed",
                    error="rebase 未完成；现场已保留，未执行 continue、abort、reset 或回滚",
                )
                result["still_in_progress"] = bool(state_now["operation_in_progress"])
                if record is not None:
                    result.update(_recovery_fields(root))
                return result

            final_oid, final_branch, _ = _head(root)
            ref_oid = _branch_ref_oid(root, branch)
            ancestor = _merge_base_ancestor(root, initial["base_oid"], final_oid)
            clean = _clean_readback(root)
            if final_branch != branch or ref_oid != final_oid or not ancestor or not clean:
                result.update(
                    head_oid_before=initial["head_oid"],
                    head_oid_after=final_oid,
                    base_oid=initial["base_oid"],
                    old_base_oid=old_boundary,
                    rebased=True,
                    needs_review=True,
                    error_code="rebase_readback_failed",
                    error="rebase 已执行，但最终分支、祖先关系或干净状态回读不符合预期",
                )
                result.update(_recovery_fields(root))
                return result
            if record is not None:
                try:
                    recovery.clear_managed_operation(root, record, git=_git)
                except recovery._RecoveryFailure as exc:
                    raise _recovery_failure(exc) from None
            result.update(
                ok=True,
                rebased=True,
                head_oid_before=initial["head_oid"],
                head_oid_after=final_oid,
                base_oid=initial["base_oid"],
                old_base_oid=old_boundary,
                conflict_paths=[],
                ignored_path_collisions=[],
                needs_review=False,
            )
            return result
    except _SyncFailure as exc:
        result.update(
            repo_path=root,
            network_accessed=network_accessed,
            head_oid_before=initial.get("head_oid"),
            head_oid_after=None,
            base_oid=initial.get("base_oid"),
            old_base_oid=old_base_oid,
            conflict_paths=[],
            ignored_path_collisions=collisions or result.get("ignored_path_collisions", []),
            action_started=action_started,
            rebased=action_succeeded if action_started else False,
            needs_review=action_started or record_created,
            error_code=exc.code,
            error=exc.message,
        )
        if record is not None:
            result["operation_id"] = record["operation_id"]
        if record_created and root is not None:
            result.update(_recovery_fields(root))
        return result


def merge_repository_branch(
    repo_path: str,
    branch_name: str,
    base_ref: str,
    expected_head_oid: str,
    expected_base_oid: str,
    remote: str = "origin",
) -> dict[str, Any]:
    """Merge a pinned base into the exact current branch, preserving existing history."""
    root: str | None = None
    initial: dict[str, Any] = {}
    network_accessed = False
    action_started = False
    record_created = False
    action_succeeded: bool | None = None
    record: dict[str, Any] | None = None
    collisions: list[str] = []
    result = _common_result(
        None,
        str(branch_name),
        base_ref,
        merged=False,
        action_started=False,
        merge_type=None,
        conflict_paths=[],
        ignored_path_collisions=[],
    )
    try:
        root = _root(repo_path)
        branch = _validated_branch(root, branch_name)
        remote_name = _remote_name(root, remote)
        expected_head = _oid(expected_head_oid, "expected_head_oid", required=True)
        expected_base = _oid(expected_base_oid, "expected_base_oid", required=True)
        assert expected_head is not None and expected_base is not None
        result.update(repo_path=root, branch_name=branch, remote=remote_name)
        with _sync_lock(root):
            initial = _preflight(root, branch, base_ref, expected_head, expected_base)
            _reject_branch_merge_options(root, branch)
            network_accessed = True
            result["network_accessed"] = True
            remote_oid = _read_remote_branch_oid(root, remote_name, branch)
            result["publication_remote_oid"] = remote_oid
            if remote_oid is not None:
                object_check = _git(root, "cat-file", "-e", f"{remote_oid}^{{commit}}")
                if object_check.returncode != 0:
                    raise _SyncFailure("remote_tip_missing_locally", "remote 分支 tip 不在本地对象库；拒绝隐式获取或 lazy fetch")
                if not _merge_base_ancestor(root, remote_oid, initial["head_oid"]):
                    raise _SyncFailure("remote_branch_not_included", "本地 head 尚未包含 remote 同名分支 tip")
            collisions = _ignored_path_collisions(
                root, initial["head_oid"], initial["base_oid"], include_replay=False
            )
            if collisions:
                result["ignored_path_collisions"] = collisions
                raise _SyncFailure("ignored_path_collision", "merge 目标会覆盖被忽略的用户文件；工具拒绝合并")

            # Recheck the exact local and remote snapshots immediately before merging.
            current = _preflight(root, branch, initial["base_ref"], expected_head, expected_base)
            if current["head_oid"] != initial["head_oid"] or current["base_oid"] != initial["base_oid"]:
                raise _SyncFailure("stale_oid", "执行前 head/base OID 已变化")
            _reject_branch_merge_options(root, branch)
            remote_oid = _read_remote_branch_oid(root, remote_name, branch)
            result["publication_remote_oid"] = remote_oid
            if remote_oid is not None:
                object_check = _git(root, "cat-file", "-e", f"{remote_oid}^{{commit}}")
                if object_check.returncode != 0:
                    raise _SyncFailure("remote_tip_missing_locally", "remote 分支 tip 不在本地对象库；拒绝隐式获取或 lazy fetch")
                if not _merge_base_ancestor(root, remote_oid, current["head_oid"]):
                    raise _SyncFailure("remote_branch_not_included", "本地 head 尚未包含 remote 同名分支 tip")
            collisions = _ignored_path_collisions(
                root, current["head_oid"], current["base_oid"], include_replay=False
            )
            if collisions:
                result["ignored_path_collisions"] = collisions
                raise _SyncFailure("ignored_path_collision", "merge 目标会覆盖被忽略的用户文件；工具拒绝合并")

            affected_paths = _recovery_paths(root, initial["head_oid"], initial["base_oid"])
            record_created = True
            record = _begin_recovery_record(
                root,
                kind="merge",
                branch_name=branch,
                original_head_oid=initial["head_oid"],
                base_oid=initial["base_oid"],
                base_ref=initial["base_ref"],
                remote=remote_name,
                old_base_oid=None,
                merge_message="chore: 同步基线更新",
                affected_paths=affected_paths,
                replay_oids=[],
            )
            result["operation_id"] = record["operation_id"]

            action_started = True
            result["action_started"] = True
            merged = _git(
                root,
                "merge",
                "--ff",
                "--no-edit",
                "--no-autostash",
                "--no-squash",
                "--commit",
                "--no-overwrite-ignore",
                "-m",
                "chore: 同步基线更新",
                initial["base_oid"],
            )
            action_succeeded = merged.returncode == 0
            if not action_succeeded:
                paths = _conflict_paths(root)
                state_now = _state(root)
                conflict = state_now["operation_in_progress"] or state_now["unmerged_index"] or bool(paths)
                result.update(
                    head_oid_before=initial["head_oid"],
                    head_oid_after=state_now["head_oid"],
                    base_oid=initial["base_oid"],
                    merge_type=None,
                    conflict_paths=paths,
                    merged=False,
                    needs_review=True,
                    error_code="merge_conflict" if conflict else "merge_failed",
                    error="merge 未完成；现场已保留，未执行 abort、reset 或回滚",
                )
                result["still_in_progress"] = bool(state_now["operation_in_progress"])
                if record is not None:
                    result.update(_recovery_fields(root))
                return result

            final_oid, final_branch, _ = _head(root)
            ref_oid = _branch_ref_oid(root, branch)
            ancestor = _merge_base_ancestor(root, initial["base_oid"], final_oid)
            clean = _clean_readback(root)
            if final_branch != branch or ref_oid != final_oid or not ancestor or not clean:
                result.update(
                    head_oid_before=initial["head_oid"],
                    head_oid_after=final_oid,
                    base_oid=initial["base_oid"],
                    merge_type=None,
                    merged=True,
                    needs_review=True,
                    error_code="merge_readback_failed",
                    error="merge 已执行，但最终分支、祖先关系或干净状态回读不符合预期",
                )
                result.update(_recovery_fields(root))
                return result
            if final_oid == initial["head_oid"]:
                merge_type = "up_to_date"
            elif final_oid == initial["base_oid"]:
                merge_type = "fast_forward"
            else:
                merge_type = "merge_commit"
            if merge_type == "merge_commit":
                parents = _git(root, "rev-list", "--parents", "-n", "1", final_oid)
                parent_oids = parents.stdout.strip().split()[1:] if parents.returncode == 0 else []
                if initial["head_oid"] not in parent_oids or initial["base_oid"] not in parent_oids:
                    raise _SyncFailure("merge_readback_failed", "merge commit 未保留原 head 与指定 base 的父提交")
            if record is not None:
                try:
                    recovery.clear_managed_operation(root, record, git=_git)
                except recovery._RecoveryFailure as exc:
                    raise _recovery_failure(exc) from None
            result.update(
                ok=True,
                merged=True,
                head_oid_before=initial["head_oid"],
                head_oid_after=final_oid,
                base_oid=initial["base_oid"],
                merge_type=merge_type,
                conflict_paths=[],
                ignored_path_collisions=[],
                needs_review=False,
            )
            return result
    except _SyncFailure as exc:
        result.update(
            repo_path=root,
            network_accessed=network_accessed,
            head_oid_before=initial.get("head_oid"),
            head_oid_after=None,
            base_oid=initial.get("base_oid"),
            merged=action_succeeded if action_started else False,
            action_started=action_started,
            merge_type=None,
            conflict_paths=[],
            ignored_path_collisions=collisions or result.get("ignored_path_collisions", []),
            needs_review=action_started or record_created,
            error_code=exc.code,
            error=exc.message,
        )
        if record is not None:
            result["operation_id"] = record["operation_id"]
        if record_created and root is not None:
            result.update(_recovery_fields(root))
        return result


def _validate_recovery_request(
    root: str,
    kind: str,
    operation_id: str,
    expected_current_head_oid: str,
    expected_state_fingerprint: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(operation_id, str) or not recovery._UUID.fullmatch(operation_id):
        raise _SyncFailure("invalid_operation_id", "operation_id 必须是标准 UUID")
    expected_head = _oid(expected_current_head_oid, "expected_current_head_oid", required=True)
    if not isinstance(expected_state_fingerprint, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_state_fingerprint):
        raise _SyncFailure("invalid_state_fingerprint", "expected_state_fingerprint 必须是 64 位小写 SHA-256")
    try:
        snapshot = recovery.recovery_snapshot(root, git=_git)
    except recovery._RecoveryFailure as exc:
        raise _recovery_failure(exc) from None
    state = _state(root)
    if state["locked"]:
        raise _SyncFailure("worktree_locked", "目标 worktree 或 Git 元数据已锁定")
    context = snapshot["recovery_context"]
    if context.get("status") != "managed_in_progress" or context.get("kind") != kind:
        raise _SyncFailure("recovery_operation_unavailable", "当前没有可继续或中止的匹配受管理操作")
    if context.get("operation_id") != operation_id:
        raise _SyncFailure("stale_operation_id", "operation_id 与当前受管理操作不匹配")
    if context.get("current_head_oid") != expected_head:
        raise _SyncFailure("stale_head", "当前 HEAD 已变化；请重新审计并核对恢复现场")
    if snapshot.get("current_state_fingerprint") != expected_state_fingerprint:
        raise _SyncFailure("stale_state_fingerprint", "当前恢复状态已变化；请重新审计并核对恢复现场")
    try:
        record = recovery.read_managed_operation(root, git=_git)
    except recovery._RecoveryFailure as exc:
        raise _recovery_failure(exc) from None
    if _metadata_locked(root, record["branch_name"]):
        raise _SyncFailure("worktree_locked", "原始分支 Git 元数据已锁定")
    return record, snapshot


def _recovery_result(root: str | None, kind: str, action: str, operation_id: str) -> dict[str, Any]:
    return {
        "ok": False,
        "repo_path": root,
        "kind": kind,
        "action": action,
        "operation_id": operation_id,
        "action_started": False,
        "network_accessed": False,
        "still_in_progress": False,
        "completed": False,
        "aborted": False,
        "needs_review": False,
        "error_code": None,
        "error": None,
        "recovery_context": None,
        "current_state_fingerprint": None,
    }


def _continue_managed_operation(
    repo_path: str,
    kind: str,
    operation_id: str,
    expected_current_head_oid: str,
    expected_state_fingerprint: str,
) -> dict[str, Any]:
    root: str | None = None
    action_started = False
    network_accessed = False
    result = _recovery_result(None, kind, "continue", str(operation_id))
    record: dict[str, Any] | None = None
    try:
        root = _root(repo_path)
        result["repo_path"] = root
        with _sync_lock(root):
            record, _ = _validate_recovery_request(
                root, kind, operation_id, expected_current_head_oid, expected_state_fingerprint
            )
            try:
                recovery.validate_continue_worktree(root, record, git=_git)
                protected = recovery.protected_worktree_snapshot(root, record, git=_git)
            except recovery._RecoveryFailure as exc:
                raise _recovery_failure(exc) from None
            if kind == "rebase":
                remote_name = _remote_name(root, record["remote"])
                network_accessed = True
                result["network_accessed"] = True
                published = _read_remote_branch_oid(root, remote_name, record["branch_name"])
                if published is not None:
                    raise _SyncFailure("published_branch", "rebase 分支现已发布；继续会改写已发布历史")

            # Revalidate the exact client snapshot and resolution state immediately before one native continue.
            record, _ = _validate_recovery_request(
                root, kind, operation_id, expected_current_head_oid, expected_state_fingerprint
            )
            try:
                recovery.validate_continue_worktree(root, record, git=_git)
                protected = recovery.protected_worktree_snapshot(root, record, git=_git)
            except recovery._RecoveryFailure as exc:
                raise _recovery_failure(exc) from None
            if kind == "rebase":
                published = _read_remote_branch_oid(root, remote_name, record["branch_name"])
                if published is not None:
                    raise _SyncFailure("published_branch", "rebase 分支现已发布；继续会改写已发布历史")

            before_oid = _capture_oid(root, "HEAD", code="head_unavailable")
            action_started = True
            result["action_started"] = True
            args = ["merge", "--continue"] if kind == "merge" else ["rebase", "--continue"]
            continued = _git_fixed_editor(root, *args)
            if continued.returncode != 0:
                fields = _recovery_fields(root)
                context = fields["recovery_context"]
                still_in_progress = context.get("status") == "managed_in_progress"
                result.update(
                    head_oid_before=before_oid,
                    head_oid_after=_head(root)[0],
                    still_in_progress=still_in_progress,
                    needs_review=True,
                    error_code=f"{kind}_continue_failed" if still_in_progress else "recovery_state_uncertain",
                    error="Git continue 未完成；未循环重试，恢复记录和现场已保留",
                    **fields,
                )
                return result

            final_oid, final_branch, _ = _head(root)
            branch_oid = _branch_ref_oid(root, record["branch_name"])
            state = _state(root)
            base_ancestor = _merge_base_ancestor(root, record["base_oid"], final_oid)
            if kind == "merge":
                parents = _git(root, "rev-list", "--parents", "-n", "1", final_oid)
                parent_oids = parents.stdout.strip().split()[1:] if parents.returncode == 0 else []
                history_ok = record["original_head_oid"] in parent_oids and record["base_oid"] in parent_oids
            else:
                history_ok = base_ancestor
            try:
                protected_ok = recovery.verify_protected_worktree(root, record, protected, git=_git)
            except recovery._RecoveryFailure as exc:
                raise _recovery_failure(exc) from None
            if (
                state["operation_in_progress"]
                or final_branch != record["branch_name"]
                or branch_oid != final_oid
                or not history_ok
                or not protected_ok
            ):
                result.update(
                    head_oid_before=before_oid,
                    head_oid_after=final_oid,
                    needs_review=True,
                    error_code=f"{kind}_continue_readback_failed",
                    error="continue 已执行，但最终分支、历史或干净状态未通过回读；恢复记录已保留",
                    **_recovery_fields(root),
                )
                return result
            try:
                recovery.clear_managed_operation(root, record, git=_git)
            except recovery._RecoveryFailure as exc:
                raise _recovery_failure(exc) from None
            result.update(
                ok=True,
                completed=True,
                head_oid_before=before_oid,
                head_oid_after=final_oid,
                needs_review=False,
                error_code=None,
                error=None,
                recovery_context={"status": "none", "operation_id": None},
                current_state_fingerprint=None,
            )
            return result
    except _SyncFailure as exc:
        result.update(
            repo_path=root,
            action_started=action_started,
            network_accessed=network_accessed,
            needs_review=action_started,
            error_code=exc.code,
            error=exc.message,
        )
        if record is not None:
            result["operation_id"] = record["operation_id"]
        if action_started and root is not None:
            result.update(_recovery_fields(root))
        return result


def continue_repository_merge(
    repo_path: str,
    operation_id: str,
    expected_current_head_oid: str,
    expected_state_fingerprint: str,
) -> dict[str, Any]:
    return _continue_managed_operation(
        repo_path, "merge", operation_id, expected_current_head_oid, expected_state_fingerprint
    )


def continue_repository_rebase(
    repo_path: str,
    operation_id: str,
    expected_current_head_oid: str,
    expected_state_fingerprint: str,
) -> dict[str, Any]:
    return _continue_managed_operation(
        repo_path, "rebase", operation_id, expected_current_head_oid, expected_state_fingerprint
    )


def _git_fixed_editor(root: str, *args: str):
    try:
        return subprocess.run(
            [
                "git",
                "--no-lazy-fetch",
                "-c",
                "core.editor=true",
                "-c",
                "sequence.editor=true",
                *args,
            ],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            check=False,
            env={
                **os.environ,
                "GIT_NO_LAZY_FETCH": "1",
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_EDITOR": "true",
                "GIT_SEQUENCE_EDITOR": "true",
            },
        )
    except subprocess.TimeoutExpired as exc:
        raise _SyncFailure("git_timeout", "Git recovery continue 超时；必须先重新审计操作状态") from exc
    except (OSError, UnicodeError, TypeError, ValueError) as exc:
        raise _SyncFailure("git_unavailable", "无法安全启动 Git recovery continue") from exc


def _abort_managed_operation(
    repo_path: str,
    kind: str,
    operation_id: str,
    expected_current_head_oid: str,
    expected_state_fingerprint: str,
    confirm_discard_resolution_work: StrictBool,
) -> dict[str, Any]:
    root: str | None = None
    action_started = False
    result = _recovery_result(None, kind, "abort", str(operation_id))
    record: dict[str, Any] | None = None
    protected: dict[str, Any] | None = None
    try:
        if confirm_discard_resolution_work is not True:
            raise _SyncFailure(
                "discard_acknowledgement_required",
                "abort 会丢弃操作范围内的冲突解决工作；confirm_discard_resolution_work 必须为 true",
            )
        root = _root(repo_path)
        result["repo_path"] = root
        with _sync_lock(root):
            record, _ = _validate_recovery_request(
                root, kind, operation_id, expected_current_head_oid, expected_state_fingerprint
            )
            try:
                protected = recovery.protected_worktree_snapshot(root, record, git=_git)
            except recovery._RecoveryFailure as exc:
                raise _recovery_failure(exc) from None
            # The exact state token is checked again after the protected-content scan.
            record, _ = _validate_recovery_request(
                root, kind, operation_id, expected_current_head_oid, expected_state_fingerprint
            )
            try:
                protected_again = recovery.protected_worktree_snapshot(root, record, git=_git)
            except recovery._RecoveryFailure as exc:
                raise _recovery_failure(exc) from None
            if protected_again != protected:
                raise _SyncFailure("stale_recovery_snapshot", "工作区在 abort 前发生变化；请重新审计")
            action_started = True
            result["action_started"] = True
            aborted = _git(root, "merge", "--abort") if kind == "merge" else _git(root, "rebase", "--abort")
            if aborted.returncode != 0:
                result.update(
                    needs_review=True,
                    error_code=f"{kind}_abort_failed",
                    error="Git abort 未成功；未使用 reset、stash 或 clean 替代，现场已保留",
                    **_recovery_fields(root),
                )
                return result
            final_oid, final_branch, _ = _head(root)
            branch_oid = _branch_ref_oid(root, record["branch_name"])
            flags = _operation_flags(root)
            no_operation = not any(flags.values())
            try:
                protected_ok = recovery.verify_protected_worktree(root, record, protected, git=_git)
            except recovery._RecoveryFailure as exc:
                raise _recovery_failure(exc) from None
            if (
                not no_operation
                or final_branch != record["branch_name"]
                or final_oid != record["original_head_oid"]
                or branch_oid != record["original_head_oid"]
                or not protected_ok
            ):
                result.update(
                    head_oid_after=final_oid,
                    needs_review=True,
                    error_code=f"{kind}_abort_readback_failed",
                    error="abort 已执行，但原分支、原始 HEAD、操作标记或受保护内容回读不符；记录已保留",
                    **_recovery_fields(root),
                )
                return result
            try:
                recovery.clear_managed_operation(root, record, git=_git)
            except recovery._RecoveryFailure as exc:
                raise _recovery_failure(exc) from None
            result.update(
                ok=True,
                aborted=True,
                head_oid_before=expected_current_head_oid,
                head_oid_after=final_oid,
                needs_review=False,
                error_code=None,
                error=None,
                recovery_context={"status": "none", "operation_id": None},
                current_state_fingerprint=None,
            )
            return result
    except _SyncFailure as exc:
        result.update(
            repo_path=root,
            action_started=action_started,
            needs_review=action_started,
            error_code=exc.code,
            error=exc.message,
        )
        if record is not None:
            result["operation_id"] = record["operation_id"]
        if action_started and root is not None:
            result.update(_recovery_fields(root))
        return result


def abort_repository_merge(
    repo_path: str,
    operation_id: str,
    expected_current_head_oid: str,
    expected_state_fingerprint: str,
    confirm_discard_resolution_work: StrictBool,
) -> dict[str, Any]:
    if not isinstance(confirm_discard_resolution_work, bool) or confirm_discard_resolution_work is not True:
        result = _recovery_result(None, "merge", "abort", str(operation_id))
        result.update(
            error_code="discard_acknowledgement_required",
            error="abort 会丢弃操作范围内的冲突解决工作；confirm_discard_resolution_work 必须为 true",
        )
        return result
    return _abort_managed_operation(
        repo_path,
        "merge",
        operation_id,
        expected_current_head_oid,
        expected_state_fingerprint,
        confirm_discard_resolution_work,
    )


def abort_repository_rebase(
    repo_path: str,
    operation_id: str,
    expected_current_head_oid: str,
    expected_state_fingerprint: str,
    confirm_discard_resolution_work: StrictBool,
) -> dict[str, Any]:
    if not isinstance(confirm_discard_resolution_work, bool) or confirm_discard_resolution_work is not True:
        result = _recovery_result(None, "rebase", "abort", str(operation_id))
        result.update(
            error_code="discard_acknowledgement_required",
            error="abort 会丢弃操作范围内的冲突解决工作；confirm_discard_resolution_work 必须为 true",
        )
        return result
    return _abort_managed_operation(
        repo_path,
        "rebase",
        operation_id,
        expected_current_head_oid,
        expected_state_fingerprint,
        confirm_discard_resolution_work,
    )
