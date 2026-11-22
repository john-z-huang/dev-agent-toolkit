from __future__ import annotations

import hashlib
import io
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class GlobalAgentsTests(unittest.TestCase):
    def setUp(self):
        from dev_workflow_standards_tools.services import global_agents

        self.global_agents = global_agents
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.home = self.root / "home"
        self.home.mkdir()
        self.env = patch.dict(os.environ, {"HOME": str(self.home)})
        self.env.start()
        self.source = self.root / "source.md"
        self.template = self._template("candidate v1")
        self.source.write_text(self.template, encoding="utf-8")
        self.target = self.home / ".codex" / "AGENTS.md"
        self.metadata = self.home / ".codex" / ".AGENTS.md.dev-workflow-standards.json"
        self.lock = self.home / ".codex" / ".AGENTS.md.global-agents.lock"

    def tearDown(self):
        self.env.stop()
        self.temporary.cleanup()

    def _template(self, body: str) -> str:
        return f"# Global instructions\n\n{body}\n"

    def _manage(self, action="update", **options):
        return self.global_agents.manage_global_agents(
            action, str(self.source), **options
        )

    def _set_candidate(self, body):
        self.template = self._template(body)
        self.source.write_text(self.template, encoding="utf-8")

    def _rendered(self):
        return self.template.replace("{{HOME}}", str(self.home)).encode("utf-8")

    def test_dry_run_has_diff_and_creates_no_paths_or_lock(self):
        result = self._manage(dry_run=True)
        self.assertEqual(result["status"], "preview")
        self.assertEqual(result["plan_action"], "create")
        self.assertTrue(result["changed"])
        self.assertIsNone(result["backup_name"])
        self.assertFalse(result["conflict"])
        self.assertIn("+candidate v1", result["diff"])
        self.assertFalse(self.home.joinpath(".codex").exists())
        self.assertFalse(self.lock.exists())

    def test_create_then_identical_update_is_unchanged_without_backup(self):
        created = self._manage()
        self.assertEqual(created["status"], "updated")
        self.assertEqual(created["plan_action"], "create")
        self.assertIsNone(created["backup"])
        self.assertEqual(self.target.read_bytes(), self._rendered())
        self.assertEqual(stat.S_IMODE(self.target.stat().st_mode), 0o600)
        unchanged = self._manage()
        self.assertEqual(unchanged["status"], "unchanged")
        self.assertFalse(unchanged["changed"])
        self.assertFalse(list(self.target.parent.glob("AGENTS_BAK_*.md")))

    def test_show_returns_hashes_and_status_without_instruction_contents(self):
        self.target.parent.mkdir()
        self.target.write_text("private unknown text\n", encoding="utf-8")
        result = self._manage("show")
        self.assertEqual(result["status"], "unmanaged")
        self.assertEqual(
            result["current_sha256"],
            hashlib.sha256(b"private unknown text\n").hexdigest(),
        )
        self.assertNotIn("private unknown text", json.dumps(result))

    def test_unmanaged_target_requires_adopt_and_exact_adopt_only_writes_metadata(self):
        self.target.parent.mkdir()
        self.target.write_bytes(self._rendered())
        preview = self._manage(dry_run=True)
        self.assertEqual(preview["plan_action"], "unchanged")
        self.assertIsNone(preview["conflict"])
        # 显式 adopt 相同内容只登记受管关系，不重写目标或创建多余备份。
        adopted = self._manage(adopt=True)
        self.assertEqual(adopted["plan_action"], "adopt_metadata")
        self.assertIsNone(adopted["backup"])
        self.assertTrue(self.metadata.exists())
        self.assertEqual(self.target.read_bytes(), self._rendered())
        self.assertFalse(list(self.target.parent.glob("AGENTS_BAK_*.md")))

    def test_unmanaged_different_target_requires_adopt_and_backup_is_exact(self):
        original = b"unknown user instructions\r\nsecond line\n"
        self.target.parent.mkdir()
        self.target.write_bytes(original)
        with patch.object(self.global_agents, "_backup_timestamp", return_value=12345):
            preview = self._manage(dry_run=True)
            self.assertEqual(
                preview["conflict"], {"kind": "adopt", "requires": "--adopt"}
            )
            self.assertIn("unknown user instructions", preview["diff"])
            self.assertEqual(preview["backup_name"], "AGENTS_BAK_12345.md")
            collision = self.target.parent / "AGENTS_BAK_12345.md"
            collision.write_bytes(b"preserved collision")
            collision_preview = self._manage(dry_run=True)
            self.assertTrue(collision_preview["backup_collision"])
            self.assertEqual(collision.read_bytes(), b"preserved collision")
            collision.unlink()
            with self.assertRaisesRegex(
                self.global_agents.GlobalAgentsError, "--adopt"
            ):
                self._manage()
            adopted = self._manage(adopt=True)
        backup = Path(adopted["backup"])
        self.assertEqual(backup.name, "AGENTS_BAK_12345.md")
        self.assertEqual(backup.parent, self.target.parent)
        self.assertEqual(backup.read_bytes(), original)
        self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o600)
        self.assertEqual(self.target.read_bytes(), self._rendered())

    def test_managed_local_edit_requires_replace_local_not_adopt(self):
        self._manage()
        modified = self._rendered().replace(b"candidate v1", b"my local edit")
        self.target.write_bytes(modified)
        preview = self._manage(dry_run=True)
        self.assertEqual(preview["status"], "preview")
        self.assertEqual(
            preview["conflict"],
            {"kind": "replace_local", "requires": "--replace-local"},
        )
        with self.assertRaisesRegex(
            self.global_agents.GlobalAgentsError, "--replace-local"
        ):
            self._manage(adopt=True)
        with patch.object(self.global_agents, "_backup_timestamp", return_value=987):
            result = self._manage(replace_local=True)
        self.assertEqual(Path(result["backup"]).name, "AGENTS_BAK_987.md")
        self.assertEqual(Path(result["backup"]).read_bytes(), modified)
        self.assertEqual(self.target.read_bytes(), self._rendered())

    def test_unknown_and_malformed_placeholders_are_rejected(self):
        self._set_candidate("{{OTHER}}")
        with self.assertRaisesRegex(self.global_agents.GlobalAgentsError, "占位符"):
            self._manage(dry_run=True)
        self._set_candidate("{HOME}")
        with self.assertRaisesRegex(self.global_agents.GlobalAgentsError, "占位符"):
            self._manage(dry_run=True)

    def test_missing_link_dependency_fails_before_any_target_write(self):
        self._set_candidate("[Local notes]({{HOME}}/notes.md)")
        with self.assertRaisesRegex(self.global_agents.GlobalAgentsError, "缺失"):
            self._manage()
        self.assertFalse(self.home.joinpath(".codex").exists())

        (self.home / "notes.md").write_text("notes\n", encoding="utf-8")
        self.assertEqual(self._manage()["status"], "updated")
        self.assertEqual(self.target.read_bytes(), self._rendered())

    def test_malformed_metadata_fails_closed_even_with_override(self):
        self._manage()
        self.metadata.write_text('{"owner":"other"}', encoding="utf-8")
        self._set_candidate("candidate v2")
        with self.assertRaisesRegex(self.global_agents.GlobalAgentsError, "元数据无效"):
            self._manage(replace_local=True)
        self.assertIn("candidate v1", self.target.read_text())

    def test_backup_collision_and_backup_failure_leave_target_unchanged(self):
        self.target.parent.mkdir()
        original = b"unknown baseline\n"
        self.target.write_bytes(original)
        self._set_candidate("candidate v2")
        collision = self.target.parent / "AGENTS_BAK_234.md"
        collision.write_bytes(b"existing backup")
        with (
            patch.object(self.global_agents, "_backup_timestamp", return_value=234),
            self.assertRaisesRegex(self.global_agents.GlobalAgentsError, "拒绝覆盖"),
        ):
            self._manage(adopt=True)
        self.assertEqual(self.target.read_bytes(), original)
        self.assertEqual(collision.read_bytes(), b"existing backup")
        with (
            patch.object(
                self.global_agents,
                "_backup",
                side_effect=self.global_agents.GlobalAgentsError("backup failure"),
            ),
            self.assertRaisesRegex(
                self.global_agents.GlobalAgentsError, "backup failure"
            ),
        ):
            self._manage(adopt=True)
        self.assertEqual(self.target.read_bytes(), original)

    def test_atomic_target_publish_failure_keeps_original_and_backup(self):
        self.target.parent.mkdir()
        original = b"unknown baseline\n"
        self.target.write_bytes(original)
        self._set_candidate("candidate v2")
        real_publish = self.global_agents._publish_file

        def fail_target(parent, path, data, mode, *, replace):
            if path == self.target:
                raise self.global_agents.GlobalAgentsError("injected publish failure")
            return real_publish(parent, path, data, mode, replace=replace)

        with (
            patch.object(self.global_agents, "_publish_file", side_effect=fail_target),
            patch.object(self.global_agents, "_backup_timestamp", return_value=456),
            self.assertRaisesRegex(
                self.global_agents.GlobalAgentsError, "injected publish"
            ),
        ):
            self._manage(adopt=True)
        self.assertEqual(self.target.read_bytes(), original)
        self.assertEqual(
            (self.target.parent / "AGENTS_BAK_456.md").read_bytes(), original
        )

    def test_metadata_publish_failure_reports_uncertain_state_and_retains_backup(self):
        self.target.parent.mkdir()
        original = b"unknown baseline\n"
        self.target.write_bytes(original)
        self._set_candidate("candidate v2")
        real_publish = self.global_agents._publish_file

        def fail_metadata(parent, path, data, mode, *, replace):
            if path == self.metadata:
                raise self.global_agents.GlobalAgentsError("injected metadata failure")
            return real_publish(parent, path, data, mode, replace=replace)

        with (
            patch.object(
                self.global_agents, "_publish_file", side_effect=fail_metadata
            ),
            patch.object(self.global_agents, "_backup_timestamp", return_value=654),
            self.assertRaisesRegex(
                self.global_agents.GlobalAgentsError, "元数据更新失败.*状态不确定"
            ),
        ):
            self._manage(adopt=True)
        self.assertEqual(self.target.read_bytes(), self._rendered())
        self.assertEqual(
            (self.target.parent / "AGENTS_BAK_654.md").read_bytes(), original
        )
        self.assertFalse(self.metadata.exists())

    def test_post_publish_external_edit_is_not_reported_as_success(self):
        self.target.parent.mkdir()
        original = b"unknown baseline\n"
        external = b"external edit after publish\n"
        self.target.write_bytes(original)
        self._set_candidate("candidate v2")
        real_publish = self.global_agents._publish_file

        def publish_then_external_edit(parent, path, data, mode, *, replace):
            result = real_publish(parent, path, data, mode, replace=replace)
            if path == self.metadata:
                self.target.write_bytes(external)
            return result

        with (
            patch.object(
                self.global_agents,
                "_publish_file",
                side_effect=publish_then_external_edit,
            ),
            patch.object(self.global_agents, "_backup_timestamp", return_value=655),
            self.assertRaisesRegex(
                self.global_agents.GlobalAgentsError, "发布后目标或元数据发生变化"
            ),
        ):
            self._manage(adopt=True)
        self.assertEqual(self.target.read_bytes(), external)
        self.assertEqual(
            (self.target.parent / "AGENTS_BAK_655.md").read_bytes(), original
        )

    def test_external_change_after_backup_is_detected_and_backup_retained(self):
        self.target.parent.mkdir()
        original = b"unknown baseline\n"
        external = b"editor changed this\n"
        self.target.write_bytes(original)
        self._set_candidate("candidate v2")
        real_backup = self.global_agents._backup

        def backup_then_external_edit(parent, data):
            result = real_backup(parent, data)
            self.target.write_bytes(external)
            return result

        with (
            patch.object(
                self.global_agents, "_backup", side_effect=backup_then_external_edit
            ),
            patch.object(self.global_agents, "_backup_timestamp", return_value=789),
            self.assertRaisesRegex(self.global_agents.GlobalAgentsError, "发生变化"),
        ):
            self._manage(adopt=True)
        self.assertEqual(self.target.read_bytes(), external)
        self.assertEqual(
            (self.target.parent / "AGENTS_BAK_789.md").read_bytes(), original
        )

    def test_cooperating_lock_rejects_second_writer(self):
        self.target.parent.mkdir()
        with (
            self.global_agents._lock(self.lock),
            self.assertRaisesRegex(
                self.global_agents.GlobalAgentsError, "另一个全局 AGENTS 更新"
            ),
        ):
            self._manage()
        self.assertFalse(self.target.exists())

    def test_read_and_directory_creation_oserrors_are_sanitized(self):
        with (
            patch.object(
                self.global_agents.os,
                "fstat",
                side_effect=OSError("sensitive low-level detail"),
            ),
            self.assertRaisesRegex(
                self.global_agents.GlobalAgentsError, "无法安全读取"
            ) as raised,
        ):
            self._manage("show")
        self.assertNotIn("sensitive low-level detail", str(raised.exception))
        real_mkdir = Path.mkdir

        def fail_target_mkdir(path, *args, **kwargs):
            if path == self.target.parent:
                raise OSError("sensitive mkdir detail")
            return real_mkdir(path, *args, **kwargs)

        with (
            patch.object(Path, "mkdir", fail_target_mkdir),
            self.assertRaisesRegex(
                self.global_agents.GlobalAgentsError, "无法创建 ~/.codex"
            ) as raised,
        ):
            self._manage()
        self.assertNotIn("sensitive mkdir detail", str(raised.exception))
        self.assertFalse(self.target.parent.exists())

    def test_unsupported_platform_stops_before_creating_target_or_lock(self):
        with (
            patch.object(self.global_agents.sys, "platform", "win32"),
            self.assertRaisesRegex(
                self.global_agents.GlobalAgentsError, "仅支持 macOS/Linux"
            ),
        ):
            self._manage()
        self.assertFalse(self.target.parent.exists())
        self.assertFalse(self.lock.exists())

    def test_symlink_hardlink_and_special_targets_are_rejected(self):
        self.target.parent.mkdir()
        external = self.root / "external.md"
        external.write_text("untouched", encoding="utf-8")
        self.target.symlink_to(external)
        with self.assertRaisesRegex(self.global_agents.GlobalAgentsError, "符号链接"):
            self._manage(dry_run=True)
        self.target.unlink()
        os.link(external, self.target)
        with self.assertRaisesRegex(
            self.global_agents.GlobalAgentsError, "硬链接|独立普通"
        ):
            self._manage(dry_run=True)
        self.target.unlink()
        os.mkfifo(self.target)
        with self.assertRaisesRegex(self.global_agents.GlobalAgentsError, "普通文件"):
            self._manage(dry_run=True)

    def test_cli_json_and_invalid_argument_combinations(self):
        from dev_workflow_standards_tools.cli import main

        stdout, stderr = io.StringIO(), io.StringIO()
        with patch("sys.stdout", stdout), patch("sys.stderr", stderr):
            status = main(
                ["agents", "update", "--source", str(self.source), "--dry-run"]
            )
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(stdout.getvalue())["status"], "preview")
        stdout.seek(0)
        stdout.truncate(0)
        with patch("sys.stdout", stdout), patch("sys.stderr", stderr):
            status = main(
                [
                    "agents",
                    "update",
                    "--source",
                    str(self.source),
                    "--adopt",
                    "--replace-local",
                ]
            )
        self.assertEqual(status, 1)
        self.assertFalse(json.loads(stderr.getvalue())["ok"])


if __name__ == "__main__":
    unittest.main()
