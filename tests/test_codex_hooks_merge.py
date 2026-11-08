"""核验已有用户 Hooks 的显式合并、备份和后续更新。"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from codex_hooks_test_support import hooks_command


def run_setup(directory: Path, *flags: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [*hooks_command(), "--global", *flags],
        env={**os.environ, "CODEX_HOME": str(directory)},
        capture_output=True,
        text=True,
        check=False,
    )


class CodexHookMergeTests(unittest.TestCase):
    def test_merge_preserves_existing_hooks_and_backup_through_updates(self):
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
            refused = run_setup(root, "--install")
            self.assertEqual(refused.returncode, 1)
            self.assertIn("--merge --dry-run", refused.stderr)
            preview = run_setup(root, "--install", "--merge", "--dry-run")
            self.assertEqual(preview.returncode, 0, preview.stderr)
            self.assertEqual(config.read_bytes(), original)
            self.assertEqual(list(root.iterdir()), [config])
            installed = run_setup(root, "--install", "--merge")
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
                result = run_setup(root, *flags)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(config.read_bytes()), merged)
            self.assertEqual(list(root.glob("hooks.json.backup-*")), backups)
            config.write_bytes(b"local edit after merge")
            refused = run_setup(root, "--update")
            self.assertEqual(refused.returncode, 1)
            self.assertEqual(config.read_bytes(), b"local edit after merge")

    def test_merge_refuses_residual_managed_resources_and_invalid_configuration(self):
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
                result = run_setup(root, "--install", "--merge")
                self.assertEqual(result.returncode, 1)
                self.assertNotIn("SENSITIVE", result.stderr)
                self.assertEqual(config.read_bytes(), original)
                self.assertEqual(list(root.glob("hooks.json.backup-*")), [])

    def test_merge_rejects_configuration_links_and_invalid_operation(self):
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
                result = run_setup(root, flag, "--merge")
                self.assertEqual(result.returncode, 2 if mode == "update" else 1)
                self.assertEqual(source.read_bytes(), b'{"hooks": {}}')
                self.assertFalse((root / "hooks").exists())
