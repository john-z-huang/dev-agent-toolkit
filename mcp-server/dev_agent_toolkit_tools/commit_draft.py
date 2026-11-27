"""Two-step Toolkit commit drafting via the local MCP client."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
from collections.abc import Generator
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from . import UV_TOOL_NAME
from .infrastructure.process import _run_fixed
from .services.staged_commit import CommitSnapshot

DEFAULT_TOOLKIT_SERVER = UV_TOOL_NAME
_CLIENT_COMMAND = "dev_agent_toolkit_mcp_client_cli"
_MAX_DRAFT_BYTES = 256 * 1024


class DraftError(Exception):
    def __init__(self, code: str, message: str, *, outcome_unknown: bool = False):
        super().__init__(message)
        self.code = code
        self.outcome_unknown = outcome_unknown

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"code": self.code, "message": str(self)}
        if self.outcome_unknown:
            result["outcome_unknown"] = True
        return result


class _Draft(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    version: Literal[1] = 1
    server: str
    server_config_sha256: str
    repo_path: str
    message: str = Field(min_length=1)
    staged_paths: list[str] = Field(min_length=1)
    snapshot: CommitSnapshot


def _client_command(registry: Path | None) -> list[str]:
    command = shutil.which(_CLIENT_COMMAND)
    if command is None and shutil.which("uv"):
        location = _run_fixed(["uv", "tool", "dir", "--bin"])
        if location.returncode == 0:
            command = shutil.which(str(Path(location.stdout.strip()) / _CLIENT_COMMAND))
    if command is None:
        raise DraftError("mcp_client_missing", f"Cannot find {_CLIENT_COMMAND}")
    return (
        [command, "--registry", str(registry.expanduser())] if registry else [command]
    )


def _request(
    client: list[str],
    *args: str,
    payload: dict[str, Any] | None = None,
    writing: bool = False,
) -> dict[str, Any]:
    if payload is not None:
        args += ("--stdin",)
    try:
        process = subprocess.run(
            [*client, *args],
            input="" if payload is None else json.dumps(payload),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
        )
    except OSError:
        raise DraftError(
            "mcp_client_failed", "Could not start the MCP Client"
        ) from None
    try:
        reply = json.loads(process.stdout)
        if not isinstance(reply, dict):
            raise ValueError
    except (ValueError, RecursionError):
        raise DraftError(
            "invalid_client_result",
            "The MCP Client did not return a valid result",
            outcome_unknown=writing,
        ) from None
    if process.returncode != 0 or reply.get("ok") is not True:
        error = reply.get("error", {})
        code = error.get("code", "mcp_client_failed")
        raise DraftError(code, "MCP Client request failed", outcome_unknown=writing)
    result = reply.get("result")
    if not isinstance(result, dict):
        raise DraftError(
            "invalid_client_result",
            "The MCP Client did not return a result object",
            outcome_unknown=writing,
        )
    return result


def _server_config_sha256(client: list[str], server: str) -> str:
    result = _request(client, "registry", "get", server)
    config = json.dumps(result["config"], sort_keys=True).encode("utf-8")
    return hashlib.sha256(config).hexdigest()


@contextmanager
def _session(client: list[str], server: str) -> Generator[str, None, None]:
    session_id = _request(client, "session", "open", server)["session_id"]
    try:
        yield session_id
    finally:
        with suppress(DraftError):
            _request(client, "session", "close", session_id)


def _tool(reply: dict[str, Any], name: str, *, writing: bool = False) -> dict[str, Any]:
    data = reply.get("structuredContent")
    if not isinstance(data, dict):
        try:
            data = json.loads(reply["content"][0]["text"])
        except (KeyError, IndexError, TypeError, ValueError):
            data = None
    if not isinstance(data, dict):
        raise DraftError(
            "invalid_tool_result",
            f"{name} did not return an object",
            outcome_unknown=writing,
        )
    return data


def _save(path: Path, draft: _Draft) -> None:
    data = draft.model_dump_json().encode("utf-8")
    if len(data) > _MAX_DRAFT_BYTES:
        raise DraftError(
            "draft_too_large", "The commit draft exceeds the file size limit"
        )
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent) as temp:
            temp.write(data)
            temp.flush()
            os.link(temp.name, path)
    except FileExistsError:
        raise DraftError("draft_exists", "The draft file already exists") from None
    except OSError:
        raise DraftError("draft_write_failed", "Cannot save the commit draft") from None


def _load(path: Path) -> _Draft:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError
            data = stream.read(_MAX_DRAFT_BYTES + 1)
        if len(data) > _MAX_DRAFT_BYTES:
            raise ValueError
        draft = _Draft.model_validate_json(data)
        if not Path(draft.repo_path).is_absolute():
            raise ValueError
        return draft
    except (OSError, ValueError):
        raise DraftError(
            "invalid_draft", "Cannot read a valid commit draft file"
        ) from None


def create_draft(
    registry: Path | None,
    server: str,
    repo_path: Path,
    target: Path,
) -> dict[str, Any]:
    target = target.expanduser().absolute()
    if os.path.lexists(target):
        raise DraftError("draft_exists", "The draft file already exists")
    client = _client_command(registry)
    server_config = _server_config_sha256(client, server)
    repo = str(repo_path.expanduser().resolve())
    tool = "generate_git_commit_message"
    candidate = _tool(
        _request(client, "call", server, tool, payload={"repo_path": repo}), tool
    )
    if candidate.get("ok") is not True or candidate.get("adoptable") is not True:
        detail = {
            key: candidate[key]
            for key in (
                "adoptable",
                "message",
                "missing_facts",
                "review_notes",
                "error_code",
            )
            if key in candidate
        }
        error = DraftError(
            "commit_draft_unavailable", "No adoptable commit draft was saved"
        )
        return {"ok": False, "error": error.as_dict(), "result": detail}
    try:
        draft = _Draft(
            server=server,
            server_config_sha256=server_config,
            repo_path=repo,
            message=candidate["message"],
            staged_paths=candidate["staged_paths"],
            snapshot=CommitSnapshot.model_validate(candidate["snapshot"]),
        )
    except (KeyError, ValidationError):
        raise DraftError(
            "invalid_tool_result",
            "The Toolkit did not return a complete commit snapshot",
        ) from None
    _save(target, draft)
    return {
        "ok": True,
        "result": {
            "adoptable": True,
            "message": draft.message,
            "branch": draft.snapshot.branch,
            "path_count": len(draft.staged_paths),
            "draft_file": str(target),
            "review_notes": candidate.get("review_notes", []),
        },
    }


def apply_draft(registry: Path | None, source: Path) -> dict[str, Any]:
    draft = _load(source.expanduser())
    client = _client_command(registry)
    if _server_config_sha256(client, draft.server) != draft.server_config_sha256:
        raise DraftError(
            "draft_server_changed",
            "The draft's registered server configuration changed",
        )
    with _session(client, draft.server) as session:
        request = [*client, "session", "request", session]
        schema = _request(
            request, "tools/schema", payload={"name": "commit_repository_changes"}
        )
        if "expected_snapshot" not in schema.get("inputSchema", {}).get(
            "properties", {}
        ):
            raise DraftError(
                "server_update_required",
                "The Toolkit must support guarded commit snapshots",
            )
        for name, arguments in (
            (
                "check_branch_names",
                {"repo_path": draft.repo_path, "branch_names": [draft.snapshot.branch]},
            ),
            ("check_staged_changes", {"repo_path": draft.repo_path}),
            ("check_commit_message", {"message": draft.message}),
        ):
            check = _tool(
                _request(
                    request,
                    "tools/call",
                    payload={"name": name, "arguments": arguments},
                ),
                name,
            )
            if check.get("passed") is not True:
                error = DraftError("commit_check_failed", f"{name} did not pass")
                return {"ok": False, "error": error.as_dict(), "result": check}
        name = "commit_repository_changes"
        reply = _request(
            request,
            "tools/call",
            payload={
                "name": name,
                "arguments": {
                    "repo_path": draft.repo_path,
                    "message": draft.message,
                    "expected_paths": draft.staged_paths,
                    "expected_snapshot": draft.snapshot.model_dump(),
                },
            },
            writing=True,
        )
        result = _tool(reply, name, writing=True)
    if result.get("ok") is not True or result.get("committed") is not True:
        error = DraftError(
            "commit_failed", "The Toolkit did not report a verified commit"
        )
        return {"ok": False, "error": error.as_dict(), "result": result}
    paths = result.get("paths")
    oid = result.get("commit_oid")
    if (
        not isinstance(paths, list)
        or not all(isinstance(path, str) for path in paths)
        or sorted(paths) != sorted(draft.staged_paths)
        or result.get("message") != draft.message.rstrip("\n")
        or not isinstance(oid, str)
        or not oid
    ):
        error = DraftError(
            "commit_readback_mismatch", "Commit readback differs from the draft"
        )
        return {"ok": False, "error": error.as_dict(), "result": result}
    return {
        "ok": True,
        "result": {
            "committed": True,
            "commit_oid": oid,
            "path_count": len(draft.staged_paths),
        },
    }
