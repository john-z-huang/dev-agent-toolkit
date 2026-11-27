"""从唯一指令源构建独立资源；sdist 自带同一份源，不回溯开发仓库。"""

import os
import re
import runpy
import subprocess
import tempfile
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

_GIT_COMMIT_FILE = "git-commit.txt"
_SKILL_INSTALLATION = runpy.run_path(
    str(
        Path(__file__).parent / "dev_agent_toolkit_tools/services/skill_installation.py"
    )
)


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
                    "git",
                    "--no-pager",
                    "--no-optional-locks",
                    "-C",
                    str(root.parent),
                    "rev-parse",
                    "--verify",
                    "HEAD^{commit}",
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
            source = root.parent / "skills" / "dev-agent-toolkit"
        manifest, payload = _SKILL_INSTALLATION["load_skill_source"](
            source, self.metadata.version
        )
        global_data = _global_instructions(root)

        self._stage = tempfile.TemporaryDirectory(
            prefix="dev-agent-toolkit-skill-build-"
        )
        stage = Path(self._stage.name)
        for name, data in payload.items():
            path = stage / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        destination = "skill-source"
        if self.target_name == "wheel":
            (stage / "manifest.json").write_bytes(
                _SKILL_INSTALLATION["_manifest_bytes"](manifest)
            )
            destination = "dev_agent_toolkit_tools/skill_bundle"
        build_data.setdefault("force_include", {})[str(stage)] = destination

        self._global_stage = tempfile.TemporaryDirectory(
            prefix="dev-agent-toolkit-global-agents-build-"
        )
        global_stage = Path(self._global_stage.name)
        global_file = global_stage / "codex-global.md"
        global_file.write_bytes(global_data)
        if self.target_name == "wheel":
            global_destination = (
                "dev_agent_toolkit_tools/global_instructions/codex-global.md"
            )
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
