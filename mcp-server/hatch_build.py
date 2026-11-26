"""从唯一指令源构建独立资源；sdist 自带同一份源，不回溯开发仓库。"""

import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlsplit

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


_SKILL_SCRIPTS = {"scripts/github_draft.py", "scripts/validate_github_draft.py"}
_GIT_COMMIT_FILE = "git-commit.txt"


def _skill_payload(source: Path) -> dict[str, bytes]:
    """校验 Skill 文件类型及内部链接，并读取独立发布所需的完整快照。"""
    payload = {}
    for path in sorted(source.rglob("*")):
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise ValueError("Skill 源包含链接或特殊文件")
        if path.is_dir():
            continue
        name = path.relative_to(source).as_posix()
        if (path.suffix != ".md" and name not in _SKILL_SCRIPTS) or any(
            part.startswith(".") for part in path.relative_to(source).parts
        ):
            raise ValueError("Skill 源只允许 Markdown 资料及指定的 GitHub 草稿脚本")
        payload[name] = path.read_bytes()
    for name, data in payload.items():
        if not name.endswith(".md"):
            continue
        for link in re.findall(r"\]\(([^)]+)\)", data.decode("utf-8")):
            url = urlsplit(link)
            if url.scheme or not url.path:
                continue
            target = (source / name).parent / unquote(url.path)
            if (
                not target.resolve().is_relative_to(source.resolve())
                or not target.exists()
            ):
                raise ValueError(f"Skill 内部链接缺失或越界: {name}: {link}")
    return payload


def _global_instructions(root: Path) -> bytes:
    """读取并校验独立的全局指令资源，与 Skill 清单保持分离。"""
    # sdist 自带独立的全局指令源，重建时无需访问原开发目录。
    global_source = root / "global-instructions-source.md"
    if not global_source.exists():
        global_source = root.parent / "instructions" / "codex-global.md"
    if global_source.is_symlink() or not global_source.is_file():
        raise ValueError("缺少全局 AGENTS 指令源")
    global_data = global_source.read_bytes()
    if not global_data or len(global_data) > 2_000_000:
        raise ValueError("全局 AGENTS 指令源为空或超过大小上限")
    try:
        global_data.decode("utf-8")
    except UnicodeError as error:
        raise ValueError("全局 AGENTS 指令源必须是 UTF-8 Markdown") from error
    return global_data


def _source_git_commit(root: Path) -> str | None:
    """Capture the source HEAD or reuse the commit carried by the sdist."""
    try:
        if (root / "skill-source").is_dir():
            commit = (root / _GIT_COMMIT_FILE).read_text(encoding="ascii").strip()
        elif (root.parent / ".git").exists():
            environment = {
                key: value
                for key, value in os.environ.items()
                if not key.startswith("GIT_")
            }
            environment["GIT_NO_LAZY_FETCH"] = "1"
            result = subprocess.run(
                [
                    "git", "--no-pager", "--no-optional-locks",
                    "-C", str(root.parent), "rev-parse", "--verify", "HEAD^{commit}",
                ],
                env=environment,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                check=True,
                timeout=5,
            )
            commit = result.stdout.decode("ascii").strip()
        else:
            return None
    except (OSError, UnicodeError, subprocess.SubprocessError):
        return None
    return commit if re.fullmatch(r"[0-9a-f]{40}(?:[0-9a-f]{24})?", commit) else None


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        root = Path(self.root)
        # sdist 中优先使用封装的源；仅开发构建从仓库的唯一源取得资源。
        source = root / "skill-source"
        if not source.exists():
            source = root.parent / "skills" / "dev-workflow-standards"
        if source.is_symlink() or not (source / "SKILL.md").is_file():
            raise ValueError("缺少完整 Skill 指令源")
        payload = _skill_payload(source)
        global_data = _global_instructions(root)

        self._stage = tempfile.TemporaryDirectory(prefix="dev-workflow-skill-build-")
        stage = Path(self._stage.name)
        for name, data in payload.items():
            path = stage / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        destination = "skill-source"
        if self.target_name == "wheel":
            manifest = {
                "schema": 1,
                "owner": "dev-workflow-standards-tools",
                "skill": "dev-workflow-standards",
                "version": self.metadata.version,
                "files": {
                    name: hashlib.sha256(data).hexdigest()
                    for name, data in payload.items()
                },
            }
            (stage / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2)
                + "\n",
                encoding="utf-8",
            )
            destination = "dev_workflow_standards_tools/skill_bundle"
        build_data.setdefault("force_include", {})[str(stage)] = destination

        self._global_stage = tempfile.TemporaryDirectory(
            prefix="dev-workflow-global-agents-build-"
        )
        global_stage = Path(self._global_stage.name)
        global_file = global_stage / "codex-global.md"
        global_file.write_bytes(global_data)
        if self.target_name == "wheel":
            global_destination = "dev_workflow_standards_tools/global_instructions/codex-global.md"
        else:
            global_destination = "global-instructions-source.md"
        build_data["force_include"][str(global_file)] = global_destination

        commit = _source_git_commit(root)
        if commit is not None:
            commit_file = global_stage / _GIT_COMMIT_FILE
            commit_file.write_text(commit + "\n", encoding="ascii")
            if self.target_name == "wheel":
                build_data["extra_metadata"][str(commit_file)] = _GIT_COMMIT_FILE
            else:
                build_data["force_include"][str(commit_file)] = _GIT_COMMIT_FILE

    def finalize(self, version, build_data, artifact_path):
        self._stage.cleanup()
        if hasattr(self, "_global_stage"):
            self._global_stage.cleanup()
