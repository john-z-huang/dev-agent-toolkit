"""Validation and local cleanup workflow use cases.

This module contains application logic only; MCP registration lives in tools/.
"""

from __future__ import annotations

import re
from typing import Any

from ..infrastructure.git import _require_clean_worktree
from ..infrastructure.github_cli import _gh_api_json, _gh_pr_for_cleanup, _resolve_repo
from ..infrastructure.paths import _run_repo, _validated_repo_path
from ..infrastructure.process import _run_fixed
from ..policy import ATTRIBUTION_PATTERN, CHINESE_PATTERN, OID_PATTERN, SUBJECT_PATTERN
from ..policy import branch_errors as _branch_errors


def check_branch_names(
    branch_names: list[str] | None = None, repo_path: str | None = None
) -> dict[str, Any]:
    """检查一个或多个分支名；省略 branch_names 时检查当前仓库分支。

    只读取 git branch --show-current，不创建、切换、删除分支或安装 Hook。
    """
    if branch_names is None:
        if repo_path is None:
            return {
                "passed": False,
                "checks": [],
                "error": "repo_path 绝对路径为必填项，除非提供 branch_names",
            }
        result, _, path_error = _run_repo(
            repo_path, ["git", "branch", "--show-current"]
        )
        if path_error:
            return {"passed": False, "checks": [], "error": path_error}
        if result.returncode != 0 or not result.stdout.strip():
            return {
                "passed": False,
                "checks": [],
                "error": "无法确定当前分支或当前处于 detached HEAD",
            }
        branch_names = [result.stdout.strip()]
    if not branch_names:
        return {
            "passed": False,
            "checks": [],
            "error": "至少提供一个分支名，或省略以检查当前分支",
        }
    checks = [
        {
            "branch_name": name,
            "passed": not (errors := _branch_errors(name)),
            "errors": errors,
        }
        for name in branch_names
    ]
    return {"passed": all(item["passed"] for item in checks), "checks": checks}


def check_commit_message(message: str) -> dict[str, Any]:
    """检查提交信息标题、中文说明和禁止的工具署名；不读取或修改 Git 状态。"""
    lines = [
        line
        for line in message.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    subject = lines[0].strip() if lines else ""
    errors: list[str] = []
    if not subject:
        errors.append("提交主题不能为空")
    else:
        if not SUBJECT_PATTERN.fullmatch(subject):
            errors.append("提交主题必须使用允许的类型前缀和格式：<type>: 中文说明")
        if not CHINESE_PATTERN.search(subject):
            errors.append("提交主题必须包含中文说明")
    match = ATTRIBUTION_PATTERN.search("\n".join(lines))
    if match:
        errors.append(f"禁止包含工具署名或生成声明: {match.group(0)}")
    return {"passed": not errors, "subject": subject, "errors": errors}


def check_staged_changes(repo_path: str) -> dict[str, Any]:
    """运行固定的 `git diff --cached --check` 检查暂存区空白错误。

    只读 Git 暂存区；不运行测试、用户提供的命令或任何 shell 命令。
    """
    result, _, path_error = _run_repo(repo_path, ["git", "diff", "--cached", "--check"])
    if path_error:
        return {"passed": False, "diagnostics": [], "error": path_error}
    if result.returncode == 0:
        return {"passed": True, "diagnostics": []}
    return {
        "passed": False,
        "diagnostics": [line for line in result.stdout.splitlines() if line],
        "error": "git diff --cached --check 执行失败",
        "exit_code": result.returncode,
    }


def _issue_pr_request_error(
    issue_number: int | None,
    pr_number: int | None,
    expected_base: str | None,
    expected_head: str | None,
) -> str | None:
    """检查审计对象与关联字段；缺少 PR 时不能验证 base/head。"""
    if issue_number is not None and issue_number <= 0:
        return "issue_number 必须为正数"
    if pr_number is not None and pr_number <= 0:
        return "pr_number 必须为正数"
    if issue_number is None and pr_number is None:
        return "至少提供正数 issue_number 或 pr_number"
    if expected_base is not None and pr_number is None:
        return "expected_base 需要与 pr_number 一起使用"
    if expected_head is not None and pr_number is None:
        return "expected_head 需要与 pr_number 一起使用"
    return None


def _pull_request_policy_errors(
    pr: dict[str, Any],
    pr_number: int,
    expected_base: str | None,
    expected_head: str | None,
    issue_number: int | None,
) -> list[str]:
    """依据已读取的 PR 响应核对开放状态、分支和 Issue 关闭关联。"""
    errors: list[str] = []
    if pr.get("state") != "open":
        errors.append(
            f"PR #{pr_number}: PR 当前不是开放状态: {pr.get('state', '未知')}"
        )
    base = (pr.get("base") or {}).get("ref")
    head = (pr.get("head") or {}).get("ref")
    if expected_base is not None and base != expected_base:
        errors.append(
            f"PR #{pr_number}: base 实际为 {base!r}，预期为 {expected_base!r}"
        )
    if expected_head is not None and head != expected_head:
        errors.append(
            f"PR #{pr_number}: head 实际为 {head!r}，预期为 {expected_head!r}"
        )
    if issue_number is not None:
        body = pr.get("body") or ""
        pattern = re.compile(
            rf"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#\s*{issue_number}\b",
            re.IGNORECASE,
        )
        if not pattern.search(body):
            errors.append(
                f"PR #{pr_number}: 描述未关联 Closes/Fixes/Resolves #{issue_number}"
            )
    return errors


def audit_issue_pr_policy(
    repo_path: str,
    repo: str | None = None,
    issue_number: int | None = None,
    pr_number: int | None = None,
    expected_base: str | None = None,
    expected_head: str | None = None,
) -> dict[str, Any]:
    """只读审计 GitHub Issue/PR 开放状态、PR base/head 和关闭 Issue 的正文关联。

    通过固定的 gh repo view / gh api 只读请求；不创建、修改、关闭或合并 GitHub 资源。
    """
    root, path_error = _validated_repo_path(repo_path)
    if path_error:
        return {"passed": False, "errors": [path_error]}
    request_error = _issue_pr_request_error(
        issue_number, pr_number, expected_base, expected_head
    )
    if request_error:
        return {"passed": False, "errors": [request_error]}
    resolved_repo, error = _resolve_repo(repo, cwd=root)
    if error:
        return {"passed": False, "errors": [error]}

    errors: list[str] = []
    if issue_number is not None:
        issue, error = _gh_api_json(
            f"repos/{resolved_repo}/issues/{issue_number}", cwd=root
        )
        if error:
            return {"passed": False, "repo": resolved_repo, "errors": [error]}
        if issue.get("state") != "open":
            errors.append(
                f"Issue #{issue_number}: Issue 当前不是开放状态: {issue.get('state', '未知')}"
            )
    if pr_number is not None:
        pr, error = _gh_api_json(f"repos/{resolved_repo}/pulls/{pr_number}", cwd=root)
        if error:
            return {"passed": False, "repo": resolved_repo, "errors": [error]}
        errors.extend(
            _pull_request_policy_errors(
                pr, pr_number, expected_base, expected_head, issue_number
            )
        )
    return {"passed": not errors, "repo": resolved_repo, "errors": errors}


def _cleanup_branches(
    info: dict[str, Any], branch_name: str | None, root: str
) -> tuple[str | None, str | None, str | None]:
    """只有已合并 PR 的确切 head 可以成为本地删除目标。"""
    if info.get("state") != "MERGED":
        return None, None, f"PR 尚未合并（状态: {info.get('state', '未知')}）"
    base = info.get("baseRefName")
    head = info.get("headRefName")
    target_branch = branch_name or head
    if not base or not head:
        return None, None, "PR 缺少 base/head 分支信息"
    if branch_name is not None and branch_name != head:
        return None, None, "指定 branch_name 与 PR head 不一致"
    if target_branch == base:
        return None, None, "PR head 不能与 base 分支相同"
    ref_check = _run_fixed(
        ["git", "check-ref-format", "--branch", target_branch], cwd=root
    )
    if ref_check.returncode != 0:
        return None, None, "PR head 不是有效的本地分支名"
    return base, target_branch, None


def _delete_merged_branch(
    root: str, target_branch: str, merged_head_oid: str | None, actions: list[str]
) -> str | None:
    """先尝试普通删除，仅在原 head OID 严格匹配后允许强制删除。"""
    current = _run_fixed(["git", "branch", "--show-current"], cwd=root)
    if current.returncode != 0 or current.stdout.strip() == target_branch:
        return "当前仍处于待删除分支，或无法确定当前分支"
    deleted = _run_fixed(["git", "branch", "-d", "--", target_branch], cwd=root)
    if deleted.returncode == 0:
        actions.append(f"deleted local branch {target_branch} with -d")
        return None
    if merged_head_oid is None:
        return "普通删除失败；若为 squash merge，需提供合并前记录的 PR head SHA 后重试"
    local_head = _run_fixed(
        ["git", "rev-parse", "--verify", f"refs/heads/{target_branch}"], cwd=root
    )
    if (
        local_head.returncode != 0
        or local_head.stdout.strip().lower() != merged_head_oid.lower()
    ):
        return "本地 head SHA 与合并前记录值不一致，拒绝强制删除"
    forced = _run_fixed(["git", "branch", "-D", "--", target_branch], cwd=root)
    if forced.returncode != 0:
        return "核验后强制删除本地分支失败"
    actions.append(
        f"deleted local branch {target_branch} with -D after exact OID verification"
    )
    return None


def _cleanup_pr_preflight(
    repo_path: str, pr_number: int, repo: str | None, merged_head_oid: str | None
) -> tuple[str | None, dict[str, Any] | None, str | None]:
    """在切换和删除分支前校验输入、干净状态及远端 PR 事实。"""
    if pr_number <= 0:
        return None, None, "pr_number 必须为正数"
    if merged_head_oid is not None and not OID_PATTERN.fullmatch(merged_head_oid):
        return None, None, "merged_head_oid 格式无效"
    root, path_error = _validated_repo_path(repo_path)
    if path_error:
        return None, None, path_error
    clean_error = _require_clean_worktree(root)
    if clean_error:
        return None, None, clean_error
    info, error = _gh_pr_for_cleanup(pr_number, repo, cwd=root)
    if error:
        return None, None, error
    return root, info, None


def cleanup_merged_pr_local_branch(
    repo_path: str,
    pr_number: int,
    repo: str | None = None,
    branch_name: str | None = None,
    merged_head_oid: str | None = None,
) -> dict[str, Any]:
    """在明确的人类授权后同步已合并 PR 的 base 并删除本地 head 分支。

    Invoke only after explicit user authorization; Codex write-approval must be enabled. The tool
    verifies a clean worktree and a MERGED PR, switches to the actual base,
    runs `git pull --ff-only origin <base>`, then uses `git branch -d`. It uses `git branch -D`
    only if the supplied pre-merge head OID exactly matches the local branch OID. It never deletes
    a remote branch or merges a PR. Side effects: local branch switch, fast-forward pull, local
    head branch deletion. The supplied OID must have been recorded before merge.
    """
    root, info, preflight_error = _cleanup_pr_preflight(
        repo_path, pr_number, repo, merged_head_oid
    )
    if preflight_error:
        return {"completed": False, "actions": [], "error": preflight_error}
    assert root is not None and info is not None
    base, target_branch, branch_error = _cleanup_branches(info, branch_name, root)
    if branch_error:
        return {"completed": False, "actions": [], "error": branch_error}
    assert base is not None and target_branch is not None

    actions: list[str] = []
    switched = _run_fixed(["git", "switch", "--", base], cwd=root)
    if switched.returncode != 0:
        switched = _run_fixed(["git", "switch", "--track", f"origin/{base}"], cwd=root)
    if switched.returncode != 0:
        return {
            "completed": False,
            "actions": actions,
            "error": "无法切换到 PR base 分支",
        }
    actions.append(f"switched to {base}")
    pull = _run_fixed(["git", "pull", "--ff-only", "origin", base], cwd=root)
    if pull.returncode != 0:
        return {
            "completed": False,
            "actions": actions,
            "error": "git pull --ff-only 同步 base 失败",
        }
    actions.append(f"fast-forwarded origin/{base}")
    clean_error = _require_clean_worktree(root)
    if clean_error:
        return {"completed": False, "actions": actions, "error": clean_error}

    delete_error = _delete_merged_branch(root, target_branch, merged_head_oid, actions)
    if delete_error:
        return {"completed": False, "actions": actions, "error": delete_error}
    return {"completed": True, "repo": repo, "pr_number": pr_number, "actions": actions}
