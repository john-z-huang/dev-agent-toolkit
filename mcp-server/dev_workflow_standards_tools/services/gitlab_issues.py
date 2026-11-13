"""GitLab Issue、标签及关联分支推送。"""

from typing import Any

from ..infrastructure.git import (
    _current_branch,
    _require_clean_worktree,
    _valid_remote_branch,
)
from ..infrastructure.gitlab_cli import (
    GitLabContext,
    create_and_read,
    gitlab_context,
    gitlab_list,
    gitlab_object,
    require_origin,
    require_positive,
    resource_summary,
)
from ..infrastructure.process import _run_fixed


def issue_for_delivery(context: GitLabContext, number: int) -> dict[str, Any]:
    require_positive(number)
    issue = gitlab_object(context, f"/issues/{number}")
    user = gitlab_object(context, global_endpoint="user")
    if (
        issue.get("state") != "opened"
        or not issue.get("labels")
        or not isinstance(user.get("id"), int)
        or user["id"]
        not in [
            item.get("id")
            for item in issue.get("assignees", [])
            if isinstance(item, dict)
        ]
    ):
        raise ValueError(
            "Issue 必须开放、具备现存工作类型 label 并指派给当前 glab 用户"
        )
    return issue


def list_gitlab_issue_labels(repo_path: str, repo: str) -> dict[str, Any]:
    """只读返回项目的前 100 个标签，包含继承的 group labels。"""
    try:
        context = gitlab_context(repo_path, repo)
        labels = gitlab_list(
            context, "/labels?per_page=100&include_ancestor_groups=true"
        )
        return {
            "ok": True,
            "repo": repo,
            "limit": 100,
            "labels": [
                {key: item.get(key) for key in ("name", "description", "color")}
                for item in labels
            ],
        }
    except ValueError as error:
        return {"ok": False, "labels": [], "error": str(error)}


def _issue_creation_payload(
    context: GitLabContext, title: str, body: str, labels: list[str]
) -> dict[str, Any]:
    """写入前核实输入、现存标签和当前账号。"""
    if (
        not title.strip()
        or not body.strip()
        or not labels
        or any(not label.strip() or "," in label for label in labels)
    ):
        raise ValueError("title/body 和至少一个不含逗号的非空 label 必填")
    available = gitlab_list(
        context, "/labels?per_page=100&include_ancestor_groups=true"
    )
    if not set(labels).issubset(item.get("name") for item in available):
        raise ValueError("指定 label 不存在或未在前 100 项中")
    user = gitlab_object(context, global_endpoint="user")
    if not isinstance(user.get("id"), int) or user["id"] <= 0:
        raise ValueError("无法核实当前 glab 用户")
    return {
        "title": title,
        "description": body,
        "labels": ",".join(labels),
        "assignee_ids": [user["id"]],
    }


def create_gitlab_issue(
    repo_path: str, repo: str, title: str, body: str, labels: list[str]
) -> dict[str, Any]:
    """创建并回读 Issue；API 写入失败不推定没有创建。"""
    try:
        context = gitlab_context(repo_path, repo)
        payload = _issue_creation_payload(context, title, body, labels)
    except ValueError as error:
        return {
            "ok": False,
            "created": False,
            "write_attempted": False,
            "error": str(error),
        }
    result = create_and_read(context, "/issues", payload)
    result["issue_number"] = result.pop("number")
    if not result["ok"]:
        return result
    details = result.pop("resource")
    assigned = [item.get("id") for item in details.get("assignees", [])]
    verified = (
        details.get("state") == "opened"
        and set(labels).issubset(details.get("labels", []))
        and payload["assignee_ids"][0] in assigned
    )
    result.update(
        ok=verified,
        repo=repo,
        issue=resource_summary(details),
        error=None if verified else "Issue 已创建，但状态/labels/assignee 回读不匹配",
    )
    return result


def push_gitlab_issue_branch_to_origin(
    repo_path: str, repo: str, branch_name: str, issue_number: int
) -> dict[str, Any]:
    """核实 GitLab Issue 和 origin 后非强推当前需求分支。"""
    try:
        context = gitlab_context(repo_path, repo)
        if (
            not _valid_remote_branch(branch_name)
            or branch_name in {"main", "master"}
            or _current_branch(context.root) != branch_name
        ):
            raise ValueError("只允许推送当前检出的有效非主分支")
        error = _require_clean_worktree(context.root)
        if error:
            raise ValueError(error)
        require_origin(context)
        issue_for_delivery(context, issue_number)
        result = _run_fixed(["git", "push", "origin", branch_name], cwd=context.root)
        return {
            "ok": result.returncode == 0,
            "repo": repo,
            "branch_name": branch_name,
            "issue_number": issue_number,
            "error": None
            if result.returncode == 0
            else "git push 失败；结果须回读，未强推",
        }
    except ValueError as error:
        return {"ok": False, "error": str(error)}
