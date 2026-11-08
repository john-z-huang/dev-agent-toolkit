from __future__ import annotations

from dev_workflow_standards_tools.services import workflows
from worktree_fixtures import WorktreeTestCase


class WorktreeFileCopyTests(WorktreeTestCase):
    def test_verified_untracked_files_are_copied_without_staging(self) -> None:
        _, source, target, _ = self.init_remote()
        (source / "notes.txt").write_bytes(b"keep these notes\n")
        manifest = workflows.capture_untracked_file_manifest(str(source))
        self.assertTrue(manifest["ok"], manifest)
        entries = [
            workflows.ManifestEntry.model_validate(item) for item in manifest["entries"]
        ]

        result = workflows.copy_untracked_files_to_worktree(
            str(source), str(target), entries
        )

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["copied"], ["notes.txt"])
        self.assertFalse(result["staged"])
        self.assertEqual((target / "notes.txt").read_bytes(), b"keep these notes\n")
        self.assertEqual(self.git(target, "diff", "--cached", "--name-only").stdout, "")

    def test_later_source_change_prevents_all_destination_writes(self) -> None:
        _, source, target, _ = self.init_remote()
        (source / "first.txt").write_bytes(b"first")
        (source / "second.txt").write_bytes(b"second")
        manifest = workflows.capture_untracked_file_manifest(str(source))
        self.assertTrue(manifest["ok"], manifest)
        entries = [
            workflows.ManifestEntry.model_validate(item) for item in manifest["entries"]
        ]
        (source / "second.txt").write_bytes(b"changed after capture")

        result = workflows.copy_untracked_files_to_worktree(
            str(source), str(target), entries
        )

        self.assertFalse(result["ok"], result)
        self.assertEqual(result["copied"], [])
        self.assertIn("指纹与清单不一致", result["error"])
        self.assertFalse((target / "first.txt").exists())
        self.assertFalse((target / "second.txt").exists())

    def test_source_parent_symlink_is_rejected_after_manifest_capture(self) -> None:
        _, source, target, _ = self.init_remote()
        directory = source / "notes"
        directory.mkdir()
        (directory / "draft.txt").write_bytes(b"draft")
        manifest = workflows.capture_untracked_file_manifest(str(source))
        self.assertTrue(manifest["ok"], manifest)
        entries = [
            workflows.ManifestEntry.model_validate(item) for item in manifest["entries"]
        ]
        directory.rename(source / "saved-notes")
        directory.symlink_to(source / "saved-notes", target_is_directory=True)

        result = workflows.copy_untracked_files_to_worktree(
            str(source), str(target), entries
        )

        self.assertFalse(result["ok"], result)
        self.assertEqual(result["copied"], [])
        self.assertIn("symlink 目录", result["error"])
        self.assertFalse((target / "notes").exists())

    def test_destination_conflict_reports_completed_copies_and_preserves_existing_file(
        self,
    ) -> None:
        _, source, target, _ = self.init_remote()
        (source / "first.txt").write_bytes(b"first")
        (source / "second.txt").write_bytes(b"second")
        (target / "second.txt").write_bytes(b"user content")
        manifest = workflows.capture_untracked_file_manifest(str(source))
        self.assertTrue(manifest["ok"], manifest)
        entries = [
            workflows.ManifestEntry.model_validate(item) for item in manifest["entries"]
        ]

        result = workflows.copy_untracked_files_to_worktree(
            str(source), str(target), entries
        )

        self.assertFalse(result["ok"], result)
        self.assertEqual(result["copied"], ["first.txt"])
        self.assertIn("拒绝覆盖", result["error"])
        self.assertEqual((target / "first.txt").read_bytes(), b"first")
        self.assertEqual((target / "second.txt").read_bytes(), b"user content")
