"""GitLab MR 创建与受保护的即时合并。"""

from typing import Any, Literal

from ..infrastructure.gitlab_cli import (
    GitLabContext,
    create_and_read,
    gitlab_context,
    gitlab_object,
    require_positive,
    resource_summary,
)
from ..infrastructure.process import _run_fixed
from ..policy import OID_PATTERN
from .workflows import _pr_reference_policy


def require_same_project_mr(context: GitLabContext, mr: dict[str, Any]) -> None:
    """本地分支操作只支持当前项目内 MR，不能把 Fork 的同名分支当成本地 head。"""
    project = gitlab_object(context)
    if (
        not isinstance(project.get("id"), int)
        or mr.get("source_project_id") != project["id"]
        or mr.get("target_project_id") != project["id"]
    ):
        raise ValueError("此操作仅支持显式项目内的 MR；跨项目 Fork MR 需另行核实拓扑")


def _mr_creation_preflight(
    context: GitLabContext,
    body: str,
    base_branch: str,
    head_branch: str,
    issue_number: int,
) -> None:
    """创建前核实分支、关闭引用与开放 Issue。"""
    require_positive(issue_number)
    _, error = _pr_reference_policy(base_branch, head_branch, body, issue_number)
    if error:
        raise ValueError(error.replace("PR body", "MR description"))
    issue = gitlab_object(context, f"/issues/{issue_number}")
    if issue.get("state") != "opened":
        raise ValueError("Issue 必须处于 opened 状态")
    exists = _run_fixed(
        ["git", "show-ref", "--verify", f"refs/heads/{head_branch}"], cwd=context.root
    )
    if exists.returncode != 0:
        raise ValueError("本地 head_branch 不存在；先完成验证和推送")


def _created_mr_matches(
    mr: dict[str, Any], payload: dict[str, Any], issue_number: int
) -> bool:
    """回读核实创建时声明的关系，不把创建成功当成验收通过。"""
    _, error = _pr_reference_policy(
        payload["target_branch"],
        payload["source_branch"],
        mr.get("description") or "",
        issue_number,
    )
    assigned = [item.get("id") for item in mr.get("assignees", [])]
    return (
        mr.get("state") == "opened"
        and mr.get("target_branch") == payload["target_branch"]
        and mr.get("source_branch") == payload["source_branch"]
        and payload["assignee_ids"][0] in assigned
        and error is None
    )


# 与对应 GitHub 工具保持平铺参数及显式事实字段；7 个参数是 MCP 接口的有意例外。
def create_gitlab_merge_request(
    repo_path: str,
    repo: str,
    title: str,
    body: str,
    base_branch: str,
    head_branch: str,
    issue_number: int,
) -> dict[str, Any]:
    """显式指定 source/target，创建后回读 MR 和 Issue 关闭关联。"""
    try:
        context = gitlab_context(repo_path, repo)
        if not title.strip() or not body.strip():
            raise ValueError("title/body 必填")
        _mr_creation_preflight(context, body, base_branch, head_branch, issue_number)
        user = gitlab_object(context, global_endpoint="user")
        if not isinstance(user.get("id"), int) or user["id"] <= 0:
            raise ValueError("无法核实当前 glab 用户")
    except ValueError as error:
        return {
            "ok": False,
            "created": False,
            "write_attempted": False,
            "error": str(error),
        }
    payload = {
        "title": title,
        "description": body,
        "source_branch": head_branch,
        "target_branch": base_branch,
        "assignee_ids": [user["id"]],
        "remove_source_branch": False,
    }
    result = create_and_read(context, "/merge_requests", payload)
    result["mr_number"] = result.pop("number")
    if not result["ok"]:
        return result
    mr = result.pop("resource")
    verified = _created_mr_matches(mr, payload, issue_number)
    result.update(
        ok=verified,
        repo=repo,
        merge_request=resource_summary(mr),
        error=None if verified else "MR 已创建，但状态/分支/指派/Issue 关联回读失败",
    )
    return result


def _merge_preflight(
    context: GitLabContext, number: int, method: str
) -> dict[str, Any]:
    require_positive(number)
    if method not in {"squash", "merge", "rebase"}:
        raise ValueError("merge_method 必须为 squash/merge/rebase")
    mr = gitlab_object(context, f"/merge_requests/{number}")
    project = gitlab_object(context)
    if (
        mr.get("iid") != number
        or mr.get("target_project_id") != project.get("id")
        or not isinstance(mr.get("target_branch"), str)
        or not mr["target_branch"]
        or not isinstance(mr.get("source_branch"), str)
        or not mr["source_branch"]
    ):
        raise ValueError("MR 项目/编号/分支事实缺失或不匹配")
    if (
        mr.get("state") != "opened"
        or mr.get("detailed_merge_status") != "mergeable"
        or mr.get("draft") is not False
        or mr.get("has_conflicts") is not False
    ):
        raise ValueError(
            "MR 必须明确 opened、非 draft、无冲突且 detailed_merge_status=mergeable"
        )
    sha = mr.get("sha")
    pipeline = mr.get("head_pipeline")
    if (
        not isinstance(sha, str)
        or not OID_PATTERN.fullmatch(sha)
        or not isinstance(pipeline, dict)
        or pipeline.get("status") != "success"
        or pipeline.get("sha") != sha
    ):
        raise ValueError("MR head SHA 或对应成功 pipeline 证据缺失；不跳过 CI")
    _validate_merge_method(project, mr.get("target_branch"), method)
    return mr


def _validate_merge_method(
    project: dict[str, Any], target: str | None, method: str
) -> None:
    """项目合并配置约束独立于 MR 当前 CI 状态，不自动更改配置。"""
    if target == "main" and method != "squash":
        raise ValueError("目标 base 为 main，只允许 squash")
    project_method = project.get("merge_method")
    if project_method not in {"merge", "rebase_merge", "ff"}:
        raise ValueError("无法确认 GitLab 项目 merge_method")
    if method == "rebase" and project_method not in {"rebase_merge", "ff"}:
        raise ValueError(
            "rebase 仅适用于项目已配置 rebase_merge/ff；不自动改配置或执行 rebase"
        )
    if method == "merge" and project_method != "merge":
        raise ValueError("merge 仅适用于项目已配置 merge；不自动改配置")
    if (
        method == "squash"
        and project.get("squash_option") not in {"default_on", "default_off", "always"}
    ) or (
        method != "squash"
        and project.get("squash_option") not in {"default_on", "default_off", "never"}
    ):
        raise ValueError("项目 squash_option 缺失或与所选合并方式冲突")


def merge_gitlab_merge_request(
    repo_path: str,
    repo: str,
    mr_number: int,
    merge_method: Literal["squash", "merge", "rebase"],
) -> dict[str, Any]:
    """绑定合并前 SHA 即时合并，不自动合并、不删 source、不绕过服务端保护。"""
    attempted = False
    sha = None
    try:
        context = gitlab_context(repo_path, repo)
        mr = _merge_preflight(context, mr_number, merge_method)
        sha = mr["sha"]
        attempted = True
        gitlab_object(
            context,
            f"/merge_requests/{mr_number}/merge",
            method="PUT",
            payload={
                "sha": sha,
                "squash": merge_method == "squash",
                "should_remove_source_branch": False,
                "auto_merge": False,
            },
        )
        actual = gitlab_object(context, f"/merge_requests/{mr_number}")
        merged = actual.get("state") == "merged" and bool(actual.get("merged_at"))
        return {
            "ok": merged,
            "merged": merged,
            "write_attempted": True,
            "pre_merge_head_oid": sha,
            "merge_request": resource_summary(actual),
            "error": None
            if merged
            else "合并命令结束但未确认 merged；须回读，禁止自动重试",
        }
    except ValueError as error:
        return {
            "ok": False,
            "merged": None if attempted else False,
            "write_attempted": attempted,
            "pre_merge_head_oid": sha,
            "error": str(error),
        }
