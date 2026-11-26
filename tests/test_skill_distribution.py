from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlsplit

import yaml

ROOT = Path(__file__).resolve().parents[1]


class SkillDistributionTests(unittest.TestCase):
    def assert_skill_links(self, source: Path, shipped: dict[str, bytes]) -> None:
        """逐个检查随 wheel 发布的相对链接，确保发布快照完整且没有越界。"""
        for name, data in shipped.items():
            if not name.endswith(".md"):
                continue
            for link in re.findall(r"\]\(([^)]+)\)", data.decode()):
                url = urlsplit(link)
                if url.scheme or not url.path:
                    continue
                linked = (source / name).parent / unquote(url.path)
                self.assertTrue(linked.resolve().is_relative_to(source), (name, link))
                self.assertTrue(linked.exists(), (name, link))

    def test_sdist_rebuild_and_installed_cli_without_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            project = root / "checkout"
            package = project / "mcp-server"
            package.mkdir(parents=True)
            source = project / "skills" / "dev-workflow-standards"
            shutil.copytree(ROOT / "skills" / "dev-workflow-standards", source)
            global_source = ROOT / "instructions" / "codex-global.md"
            (project / "instructions").mkdir()
            shutil.copy2(global_source, project / "instructions" / "codex-global.md")
            shutil.copytree(
                ROOT / "mcp-server" / "dev_workflow_standards_tools",
                package / "dev_workflow_standards_tools",
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "skill_bundle"),
            )
            for name in ("pyproject.toml", "hatch_build.py"):
                shutil.copy2(ROOT / "mcp-server" / name, package / name)
            global_home = (root / "user-home").resolve()
            environment = {
                **os.environ,
                "OPENAI_API_KEY": "",
                "OPENAI_BASE_URL": "",
                "HOME": str(global_home),
            }
            environment.pop("PYTHONPATH", None)

            def run(argv, cwd=root, expected=0):
                result = subprocess.run(
                    argv,
                    cwd=cwd,
                    env=environment,
                    text=True,
                    capture_output=True,
                    timeout=90,
                    check=False,
                )
                self.assertEqual(
                    result.returncode, expected, result.stdout + result.stderr
                )
                return result

            run(["git", "init", "-q"], project)
            wheels = []
            commits = []
            for number in (1, 2):
                if number == 2:
                    with (source / "SKILL.md").open("a") as stream:
                        stream.write("\n测试第二个发布快照。\n")
                run(["git", "add", "--", "mcp-server", "skills", "instructions"], project)
                run(
                    ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com",
                     "commit", "-qm", f"fixture-{number}"],
                    project,
                )
                commit = run(["git", "rev-parse", "HEAD"], project).stdout.strip()
                commits.append(commit)
                artifacts = root / f"artifacts-{number}"
                artifacts.mkdir()
                run(
                    [
                        sys.executable,
                        "-m",
                        "hatchling",
                        "build",
                        "-t",
                        "sdist",
                        "-d",
                        str(artifacts),
                    ],
                    package,
                )
                sdist = next(artifacts.glob("*.tar.gz"))
                extracted = root / f"extracted-{number}"
                with tarfile.open(sdist) as archive:
                    self.assertTrue(
                        any(
                            "skill-source/SKILL.md" in name
                            for name in archive.getnames()
                        )
                    )
                    self.assertTrue(
                        any(
                            name.endswith("/global-instructions-source.md")
                            for name in archive.getnames()
                        )
                    )
                    self.assertFalse(
                        any(
                            ".git/" in name or ".venv/" in name or "archive/" in name
                            for name in archive.getnames()
                        )
                    )
                    archive.extractall(extracted, filter="data")
                rebuild_root = next(extracted.iterdir())
                self.assertEqual((rebuild_root / "git-commit.txt").read_text().strip(), commit)
                self.assertEqual(
                    (rebuild_root / "global-instructions-source.md").read_bytes(),
                    global_source.read_bytes(),
                )
                # 重建位置旁边没有原仓库 skills 目录；仅使用 sdist 中的闭包。
                run(
                    [
                        sys.executable,
                        "-m",
                        "hatchling",
                        "build",
                        "-t",
                        "wheel",
                        "-d",
                        str(artifacts),
                    ],
                    rebuild_root,
                )
                wheel = next(artifacts.glob("*.whl"))
                wheels.append(wheel)
                with zipfile.ZipFile(wheel) as archive:
                    git_metadata = next(
                        name for name in archive.namelist()
                        if name.endswith(".dist-info/extra_metadata/git-commit.txt")
                    )
                    self.assertEqual(archive.read(git_metadata).decode().strip(), commit)
                    global_resource = "dev_workflow_standards_tools/global_instructions/codex-global.md"
                    self.assertEqual(
                        archive.read(global_resource), global_source.read_bytes()
                    )
                    prefix = "dev_workflow_standards_tools/skill_bundle/"
                    manifest = json.loads(archive.read(prefix + "manifest.json"))
                    shipped = {
                        name.removeprefix(prefix): archive.read(name)
                        for name in archive.namelist()
                        if name.startswith(prefix) and name != prefix + "manifest.json"
                    }
                    expected_files = {
                        p.relative_to(source).as_posix(): p.read_bytes()
                        for p in source.rglob("*.md")
                    }
                    for script in ("scripts/github_draft.py", "scripts/validate_github_draft.py"):
                        expected_files[script] = (source / script).read_bytes()
                    self.assertEqual(shipped, expected_files)
                    self.assertIn("hooks/index.md", shipped)
                    self.assertIn("hooks/recovery.md", shipped)
                    self.assertIn("references/git-hooks.md", shipped)
                    # 宿主兼容规则必须随 Skill 发布，不依赖仓库根 AGENTS.md。
                    skill_text = shipped["SKILL.md"].decode()
                    self.assertIn("## 宿主审批兼容", skill_text)
                    self.assertIn("Pi Code Agent", skill_text)
                    self.assertIn("## Pi 工具发现与能力边界", skill_text)
                    self.assertIn("describeNamespace", skill_text)
                    self.assertIn("### Pi stdio 环境传递与工具时限", shipped["references/openai-workflow-tools.md"].decode())
                    self.assertIn("## 宿主适用范围", shipped["references/codex-session-facts.md"].decode())
                    self.assertIn("Codex writes approval", skill_text)
                    self.assertNotIn("AGENTS.md", shipped)
                    self.assertIn(
                        "../SKILL.md#宿主审批兼容",
                        shipped["references/mcp-tools.md"].decode(),
                    )
                    self.assertFalse(
                        any(name.startswith("workflows/") for name in shipped)
                    )
                    metadata = yaml.safe_load(
                        shipped["SKILL.md"].decode().split("---", 2)[1]
                    )
                    self.assertEqual(metadata["name"], "dev-workflow-standards")
                    self.assertTrue(metadata["description"].strip())
                    self.assertEqual(
                        manifest["files"],
                        {
                            name: hashlib.sha256(data).hexdigest()
                            for name, data in shipped.items()
                        },
                    )
                    entrypoints = next(
                        name
                        for name in archive.namelist()
                        if name.endswith("entry_points.txt")
                    )
                    self.assertIn(
                        "dev-workflow-standards-tools = dev_workflow_standards_tools.server:main",
                        archive.read(entrypoints).decode(),
                    )
                    metadata_path = next(
                        name
                        for name in archive.namelist()
                        if name.endswith(".dist-info/METADATA")
                    )
                    self.assertNotIn(
                        "openai-codex", archive.read(metadata_path).decode().lower()
                    )
                    self.assertFalse(
                        any(name.startswith("tests/") for name in archive.namelist())
                    )
                    self.assert_skill_links(source, shipped)
                shutil.rmtree(extracted)
            shutil.rmtree(project)
            self.assertFalse(project.exists())

            venv = root / "environment"
            run([sys.executable, "-m", "venv", "--without-pip", str(venv)])
            python = venv / "bin" / "python"
            cli = venv / "bin" / "dev-workflow-standards"
            run(
                [
                    "uv",
                    "pip",
                    "install",
                    "--offline",
                    "--python",
                    str(python),
                    "--no-deps",
                    str(wheels[0]),
                ]
            )
            build_query = (
                "import json; "
                "from dev_workflow_standards_tools.services.build_info import get_mcp_server_build_info; "
                "print(json.dumps(get_mcp_server_build_info()))"
            )
            self.assertEqual(
                json.loads(run([str(python), "-c", build_query]).stdout),
                {"server_version": "0.2.0", "git_commit": commits[0]},
            )
            # 该环境没有 OpenAI/MCP 依赖，管理命令仍应独立工作。
            skill_home = root / "skill-home"
            environment["HOME"] = str(skill_home)
            target = skill_home / ".agents" / "skills" / "dev-workflow-standards"
            args = [str(cli), "skills"]
            self.assertIn(
                "~/.agents/skills/dev-workflow-standards\n",
                run([*args, "install", "--help"]).stdout,
            )
            run([*args, "install", "--dry-run"])
            self.assertFalse(target.parent.exists())
            run([*args, "install"])
            before = (target / "SKILL.md").read_bytes()
            show = json.loads(run([*args, "show"]).stdout)
            self.assertEqual(show["target"], str(target))
            self.assertEqual(show["installed_version"], "0.2.0")
            run([*args, "install", "--target", str(target)], expected=1)
            run(
                [
                    "uv",
                    "pip",
                    "install",
                    "--offline",
                    "--reinstall",
                    "--python",
                    str(python),
                    "--no-deps",
                    str(wheels[1]),
                ]
            )
            self.assertEqual(
                json.loads(run([str(python), "-c", build_query]).stdout),
                {"server_version": "0.2.0", "git_commit": commits[1]},
            )
            self.assertEqual((target / "SKILL.md").read_bytes(), before)
            run([*args, "update", "--dry-run"])
            self.assertEqual((target / "SKILL.md").read_bytes(), before)
            run([*args, "update"])
            self.assertIn("测试第二个发布快照。", (target / "SKILL.md").read_text())
            self.assertEqual(
                json.loads(run([*args, "update"]).stdout)["status"],
                "unchanged",
            )
            (target / "user-notes.md").write_text("keep this")
            run([*args, "update", "--target", str(target)], expected=1)
            self.assertEqual((target / "user-notes.md").read_text(), "keep this")

            # 在未安装 Skill 的临时主目录中验证 wheel 自带的全局模板。
            environment["HOME"] = str(global_home)
            global_home.mkdir(parents=True, exist_ok=True)
            self.assertFalse((global_home / ".agents" / "skills").exists())
            agent_args = [str(cli), "agents"]
            agent_target = global_home / ".codex" / "AGENTS.md"
            preview = json.loads(run([*agent_args, "update", "--dry-run"]).stdout)
            self.assertEqual(preview["plan_action"], "create")
            self.assertFalse(agent_target.parent.exists())
            self.assertEqual(
                json.loads(run([*agent_args, "update"]).stdout)["status"], "updated"
            )
            self.assertEqual(agent_target.read_bytes(), global_source.read_bytes())
            show_agents = json.loads(run([*agent_args, "show"]).stdout)
            self.assertEqual(show_agents["status"], "up_to_date")


if __name__ == "__main__":
    unittest.main()
