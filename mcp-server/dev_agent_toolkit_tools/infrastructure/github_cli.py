"""Private GitHub CLI/API helpers; commands remain fixed by each use case."""

import json
import tempfile
from pathlib import Path
from typing import Any

from ..policy import REPO_PATTERN
from .process import _run_fixed


def _resolve_repo(repo: str | None, *, cwd: str) -> tuple[str | None, str | None]:
    if repo is not None:
        if not REPO_PATTERN.fullmatch(repo):
            return None, "repo 必须采用 owner/repo 格式"
        return repo, None
    result = _run_fixed(
        ["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"],
        cwd=cwd,
    )
    resolved = result.stdout.strip()
    if result.returncode != 0 or not REPO_PATTERN.fullmatch(resolved):
        return (
            None,
            "无法从当前目录确定 GitHub 仓库；请提供 repo=owner/repo 并确认 gh 已授权",
        )
    return resolved, None


def _gh_api_json(
    endpoint: str, *, cwd: str
) -> tuple[dict[str, Any] | None, str | None]:
    result = _run_fixed(["gh", "api", endpoint], cwd=cwd)
    if result.returncode != 0:
        return None, f"gh API 请求失败（退出码 {result.returncode}）"
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None, "gh API 返回了无效 JSON"
    if not isinstance(value, dict):
        return None, "gh API 返回的数据结构不是对象"
    return value, None


def _gh_pr_for_cleanup(
    pr_number: int, repo: str | None, *, cwd: str
) -> tuple[dict[str, Any] | None, str | None]:
    if repo is not None and not REPO_PATTERN.fullmatch(repo):
        return None, "repo 必须采用 owner/repo 格式"
    args = ["gh", "pr", "view", str(pr_number)]
    if repo:
        args.extend(["--repo", repo])
    args.extend(["--json", "state,mergedAt,baseRefName,headRefName,title"])
    result = _run_fixed(args, cwd=cwd)
    if result.returncode != 0:
        return None, f"gh pr view 失败（退出码 {result.returncode}）"
    try:
        info = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None, "gh 返回了无效的 PR JSON"
    if not isinstance(info, dict):
        return None, "gh 返回的 PR 数据不是对象"
    return info, None


def _gh_current_login(cwd: str) -> tuple[str | None, str | None]:
    result = _run_fixed(["gh", "api", "user", "--jq", ".login"], cwd=cwd)
    login = result.stdout.strip()
    if result.returncode != 0 or not login:
        return None, "无法解析当前 gh 登录账号；未输出认证信息"
    return login, None


def _gh_object(args: list[str], cwd: str) -> tuple[Any, str | None]:
    result = _run_fixed(args, cwd=cwd)
    if result.returncode != 0:
        return None, f"GitHub CLI operation failed (exit {result.returncode})"
    try:
        return json.loads(result.stdout), None
    except json.JSONDecodeError:
        return None, "GitHub CLI returned invalid JSON"


def _read_draft_file(path: Path, field: str) -> str:
    if not path.is_absolute():
        raise ValueError(f"{field} 必须是文件的绝对路径")
    try:
        if not path.is_file():
            raise ValueError(f"{field} 必须指向已存在的普通文件")
        return path.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError(f"{field} 必须采用 UTF-8 编码") from None
    except OSError:
        raise ValueError(f"无法读取 {field}") from None


def _read_draft_title(title_file: str) -> str:
    lines = _read_draft_file(Path(title_file), "title_file").splitlines()
    if len(lines) != 1 or not lines[0].strip() or "\x00" in lines[0]:
        raise ValueError("title_file 须包含一行非空标题")
    return lines[0]


def _read_markdown_body(body_file: str) -> str:
    path = Path(body_file)
    if path.suffix.lower() not in {".md", ".markdown"}:
        raise ValueError("body_file 须指向 .md 或 .markdown 文件")
    body = _read_draft_file(path, "body_file")
    if not body.strip():
        raise ValueError("body_file 的 Markdown 正文不能为空")
    return body


def _temporary_body_file(body: str) -> tuple[tempfile.TemporaryDirectory[str], str]:
    """Pass the checked body to gh even if the source draft changes."""
    directory = tempfile.TemporaryDirectory(prefix="dev-agent-toolkit-tools-")
    path = Path(directory.name) / "body.md"
    path.write_bytes(body.encode("utf-8"))
    return directory, str(path)
