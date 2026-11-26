"""核验已有用户 Hooks 的显式合并、备份和后续更新。"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

from codex_hooks_test_support import InstalledHooksTestCase


class CodexHookMergeTests(InstalledHooksTestCase):
    def run_setup(
        self, directory: Path, *flags: str
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [*self.configure_command, "--global", *flags],
            env={**os.environ, "CODEX_HOME": str(directory)},
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )

    def test_update_rejects_boolean_legacy_manifest_version_without_writing(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            config = root / "hooks.json"
            original = b'{"hooks": {}}'
            config.write_bytes(original)
            legacy = root / "hooks/dev_workflow.py"
            legacy.parent.mkdir()
            legacy.write_bytes(b"# old runtime")
            record = {
                "format": True,
                "files": {
                    path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in (config, legacy)
                },
            }
            manifest = root / "hooks/dev_workflow.manifest.json"
            manifest.write_text(json.dumps(record), encoding="utf-8")
            result = self.run_setup(root, "--update")
            self.assertEqual(result.returncode, 1)
            self.assertIn("清单格式无效", result.stderr)
            self.assertEqual(config.read_bytes(), original)
            self.assertEqual(json.loads(manifest.read_bytes()), record)

    def test_merge_preserves_existing_hooks_and_backup_through_updates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            config = root / "hooks.json"
            custom = {
                "hooks": [{"type": "command", "command": "custom-check"}],
                "matcher": "^Bash$",
            }
            base = {
                "description": "existing hooks",
                "hooks": {"PreToolUse": [custom], "SessionEnd": [custom]},
            }
            original = (json.dumps(base, indent=4) + "\n").encode()
            config.write_bytes(original)
            refused = self.run_setup(root, "--install")
            self.assertEqual(refused.returncode, 1)
            self.assertIn("--merge --dry-run", refused.stderr)
            preview = self.run_setup(root, "--install", "--merge", "--dry-run")
            self.assertEqual(preview.returncode, 0, preview.stderr)
            self.assertEqual(config.read_bytes(), original)
            self.assertEqual(list(root.iterdir()), [config])
            installed = self.run_setup(root, "--install", "--merge")
            self.assertEqual(installed.returncode, 0, installed.stderr)
            backups = list(root.glob("hooks.json.backup-*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), original)
            merged = json.loads(config.read_bytes())
            self.assertEqual(merged, json.loads(preview.stdout))
            self.assertEqual(merged["description"], base["description"])
            self.assertEqual(merged["hooks"]["SessionEnd"], [custom])
            self.assertEqual(merged["hooks"]["PreToolUse"][0], custom)
            for flags in (("--update", "--dry-run"), ("--update",), ("--update",)):
                result = self.run_setup(root, *flags)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(config.read_bytes()), merged)
            self.assertEqual(list(root.glob("hooks.json.backup-*")), backups)
            config.write_bytes(b"local edit after merge")
            refused = self.run_setup(root, "--update")
            self.assertEqual(refused.returncode, 1)
            self.assertEqual(config.read_bytes(), b"local edit after merge")

    def test_merge_refuses_residual_managed_resources_and_invalid_configuration(
        self,
    ) -> None:
        for resource in (
            "hooks/dev_workflow.py",
            "hooks/dev_workflow.manifest.json",
            None,
        ):
            with (
                self.subTest(resource=resource),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory).resolve()
                config = root / "hooks.json"
                original = b'{"hooks": {}}' if resource else b"SENSITIVE_INVALID_JSON"
                config.write_bytes(original)
                if resource:
                    path = root / resource
                    path.parent.mkdir()
                    path.write_bytes(b"existing resource")
                result = self.run_setup(root, "--install", "--merge")
                self.assertEqual(result.returncode, 1)
                self.assertNotIn("SENSITIVE", result.stderr)
                self.assertEqual(config.read_bytes(), original)
                self.assertEqual(list(root.glob("hooks.json.backup-*")), [])

    def test_reconcile_updates_only_current_unmanaged_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            config = root / "hooks.json"
            custom = {"hooks": [{"type": "command", "command": "custom-check"}]}
            config.write_text(
                json.dumps({"hooks": {"SessionEnd": [custom]}}), encoding="utf-8"
            )
            installed = self.run_setup(root, "--install", "--merge")
            self.assertEqual(installed.returncode, 0, installed.stderr)
            backups = set(root.glob("hooks.json.backup-*"))
            manifest = root / "hooks/dev_workflow.manifest.json"
            old_manifest = manifest.read_bytes()
            current = json.loads(config.read_bytes())
            current["description"] = "updated by user"
            current["hooks"]["SessionEnd"] = []
            current["hooks"]["Stop"] = [custom]
            current["hooks"]["PreToolUse"].insert(0, custom)
            original = (json.dumps(current, indent=4) + "\n").encode()
            config.write_bytes(original)

            refused = self.run_setup(root, "--update")
            self.assertEqual(refused.returncode, 1)
            self.assertIn("--reconcile --dry-run", refused.stderr)
            preview = self.run_setup(root, "--update", "--reconcile", "--dry-run")
            self.assertEqual(preview.returncode, 0, preview.stderr)
            self.assertEqual(json.loads(preview.stdout), current)
            self.assertEqual(config.read_bytes(), original)
            self.assertEqual(manifest.read_bytes(), old_manifest)
            self.assertEqual(set(root.glob("hooks.json.backup-*")), backups)

            result = self.run_setup(root, "--update", "--reconcile")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(config.read_bytes()), current)
            recovery_backups = set(root.glob("hooks.json.backup-*")) - backups
            self.assertEqual(len(recovery_backups), 1)
            self.assertEqual(next(iter(recovery_backups)).read_bytes(), original)
            result = self.run_setup(root, "--update")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(config.read_bytes()), current)

    def test_reconcile_refuses_changes_to_managed_groups_or_original_fingerprint(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            installed = self.run_setup(root, "--install")
            self.assertEqual(installed.returncode, 0, installed.stderr)
            config = root / "hooks.json"
            manifest = root / "hooks/dev_workflow.manifest.json"
            original = config.read_bytes()
            old_manifest = manifest.read_bytes()
            modified = json.loads(original)
            modified["hooks"]["PreToolUse"].reverse()
            config.write_text(json.dumps(modified), encoding="utf-8")
            result = self.run_setup(root, "--update", "--reconcile")
            self.assertEqual(result.returncode, 1)
            self.assertIn("顺序变化", result.stderr)
            self.assertEqual(json.loads(config.read_bytes()), modified)
            self.assertEqual(manifest.read_bytes(), old_manifest)

            config.write_bytes(original + b"\n")
            stale = json.loads(old_manifest)
            stale["files"]["hooks.json"] = "0" * 64
            manifest.write_text(json.dumps(stale), encoding="utf-8")
            result = self.run_setup(root, "--update", "--reconcile")
            self.assertEqual(result.returncode, 1)
            self.assertIn("无法重建", result.stderr)
            self.assertEqual(config.read_bytes(), original + b"\n")
            self.assertEqual(json.loads(manifest.read_bytes()), stale)
            self.assertFalse(list(root.glob("hooks.json.backup-*")))

    def test_merge_rejects_configuration_links_and_invalid_operation(self) -> None:
        for mode in ("symlink", "hardlink", "missing", "update"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                source = root / "source.json"
                source.write_bytes(b'{"hooks": {}}')
                config = root / "hooks.json"
                if mode == "symlink":
                    config.symlink_to(source)
                elif mode == "hardlink":
                    config.hardlink_to(source)
                flag = "--update" if mode == "update" else "--install"
                result = self.run_setup(root, flag, "--merge")
                self.assertEqual(result.returncode, 2 if mode == "update" else 1)
                self.assertEqual(source.read_bytes(), b'{"hooks": {}}')
                self.assertFalse((root / "hooks").exists())
