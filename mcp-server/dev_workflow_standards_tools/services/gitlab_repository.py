"""GitLab 仓库、Issue/MR 审计、Fork 同步和本地清理。"""

from typing import Any

from ..infrastructure.git import (
    _current_branch,
    _require_clean_worktree,
    _valid_remote_branch,
)
from ..infrastructure.gitlab_cli import (
    gitlab_context,
    gitlab_object,
    require_origin,
    require_positive,
)
from ..infrastructure.process import _run_fixed
from ..policy import OID_PATTERN
from .gitlab_merge_requests import require_same_project_mr
from .validation import (
    _cleanup_local_branch,
    _issue_pr_request_error,
    _pull_request_policy_errors,
)


def audit_gitlab_repository_state(repo_path: str, repo: str) -> dict[str, Any]:
    """本地状态与 GitLab 项目事实分别返回；远端失败不伪装通过。"""
    try:
        context = gitlab_context(repo_path, repo)
        status = _run_fixed(
            ["git", "status", "--short", "--branch", "--untracked-files=all"],
            cwd=context.root,
        )
        remotes = _run_fixed(["git", "remote"], cwd=context.root)
        data, remote_error = None, None
        try:
            project = gitlab_object(context)
            parent = project.get("forked_from_project")
            data = {
                key: project.get(key)
                for key in ("id", "path_with_namespace", "default_branch")
            }
            data["forked_from_project"] = (
                {
                    key: parent.get(key)
                    for key in ("id", "path_with_namespace", "default_branch")
                }
                if isinstance(parent, dict)
                else None
            )
        except ValueError as error:
            remote_error = str(error)
        return {
            "ok": status.returncode == 0 and remotes.returncode == 0,
            "repo_path": context.root,
            "repo": repo,
            "current_branch": _current_branch(context.root),
            "status_lines": status.stdout.splitlines()
            if status.returncode == 0
            else [],
            "remotes": remotes.stdout.splitlines() if remotes.returncode == 0 else [],
            "gitlab": data,
            "gitlab_error": remote_error,
        }
    except ValueError as error:
        return {"ok": False, "gitlab": None, "gitlab_error": str(error)}


# 保持 Issue/PR 审计的平铺字段与 null 语义，6 个参数是对应 MCP 接口的有意例外。
def audit_issue_mr_policy(
    repo_path: str,
    repo: str,
    issue_number: int | None = None,
    mr_number: int | None = None,
    expected_base: str | None = None,
    expected_head: str | None = None,
) -> dict[str, Any]:
    """固定只读检查，不把 CI、标签或可合并性混入请求范围。"""
    try:
        context = gitlab_context(repo_path, repo)
        error = _issue_pr_request_error(
            issue_number, mr_number, expected_base, expected_head
        )
        if error:
            raise ValueError(error.replace("pr_number", "mr_number"))
        errors = []
        if issue_number is not None:
            issue = gitlab_object(context, f"/issues/{issue_number}")
            if issue.get("state") != "opened":
                errors.append("Issue 不是 opened 状态")
        if mr_number is not None:
            mr = gitlab_object(context, f"/merge_requests/{mr_number}")
            normalized = {
                "state": "open" if mr.get("state") == "opened" else mr.get("state"),
                "base": {"ref": mr.get("target_branch")},
                "head": {"ref": mr.get("source_branch")},
                "body": mr.get("description"),
            }
            errors.extend(
                message.replace("PR #", "MR !")
                for message in _pull_request_policy_errors(
                    normalized, mr_number, expected_base, expected_head, issue_number
                )
            )
        return {"passed": not errors, "repo": repo, "errors": errors}
    except ValueError as error:
        return {"passed": False, "errors": [str(error)]}


def cleanup_merged_mr_local_branch(
    repo_path: str,
    repo: str,
    mr_number: int,
    branch_name: str | None = None,
    merged_head_oid: str | None = None,
) -> dict[str, Any]:
    """明确清理授权后同步 MR 实际 base 并删除本地 head；保留 OID 门禁。"""
    try:
        context = gitlab_context(repo_path, repo)
        require_positive(mr_number)
        if merged_head_oid is not None and not OID_PATTERN.fullmatch(merged_head_oid):
            raise ValueError("merged_head_oid 格式无效")
        error = _require_clean_worktree(context.root)
        if error:
            raise ValueError(error)
        require_origin(context)
        mr = gitlab_object(context, f"/merge_requests/{mr_number}")
        require_same_project_mr(context, mr)
        base, head = mr.get("target_branch"), mr.get("source_branch")
        if (
            mr.get("state") != "merged"
            or not mr.get("merged_at")
            or not isinstance(base, str)
            or not _valid_remote_branch(base)
            or not isinstance(head, str)
            or not _valid_remote_branch(head)
            or head in {"main", "master"}
        ):
            raise ValueError("MR 必须已合并且分支有效；禁止清理主分支")
        info = {"state": "MERGED", "baseRefName": base, "headRefName": head}
        return _cleanup_local_branch(context.root, info, branch_name, merged_head_oid)
    except ValueError as error:
        return {"completed": False, "actions": [], "error": str(error)}


def push_gitlab_fork_main_fast_forward(repo_path: str, repo: str) -> dict[str, Any]:
    """核实真实 Fork 和 origin 后推送已快进同步的本地 main。"""
    try:
        context = gitlab_context(repo_path, repo)
        project = gitlab_object(context)
        parent = project.get("forked_from_project")
        if not isinstance(parent, dict) or not parent.get("id"):
            raise ValueError("目标不是已核实的 GitLab Fork")
        if (
            project.get("default_branch") != "main"
            or _current_branch(context.root) != "main"
        ):
            raise ValueError("只支持默认分支为 main 且当前检出 main 的 Fork")
        error = _require_clean_worktree(context.root)
        if error:
            raise ValueError(error)
        require_origin(context)
        remotes = _run_fixed(["git", "remote"], cwd=context.root)
        ancestor = _run_fixed(
            ["git", "merge-base", "--is-ancestor", "upstream/main", "main"],
            cwd=context.root,
        )
        if (
            remotes.returncode != 0
            or not {"origin", "upstream"}.issubset(remotes.stdout.splitlines())
            or ancestor.returncode != 0
        ):
            raise ValueError(
                "需配置 origin/upstream 且 upstream/main 已快进合入本地 main"
            )
        pushed = _run_fixed(["git", "push", "origin", "main"], cwd=context.root)
        return {
            "ok": pushed.returncode == 0,
            "repo": repo,
            "branch": "main",
            "error": None
            if pushed.returncode == 0
            else "git push origin main 失败；结果须回读，未强推",
        }
    except ValueError as error:
        return {"ok": False, "error": str(error)}
