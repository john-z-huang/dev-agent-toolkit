from __future__ import annotations

import asyncio
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dev_agent_toolkit_tools.server import mcp as complete_server
from dev_agent_toolkit_tools.services import worktree_sync as sync
from worktree_fixtures import WorktreeTestCase


class WorktreeBaseSyncTests(WorktreeTestCase):
    def test_audit_reports_local_relation_and_optional_live_publication(self) -> None:
        _, seed, topic, baseline = self.init_remote()
        topic_oid = self.add_topic_commit(topic)
        base_oid = self.advance_main(seed)

        fetched = sync.fetch_repository_branch(str(topic), "origin", "main")
        self.assertTrue(fetched["ok"], fetched)
        self.assertEqual(fetched["fetched_oid"], base_oid)
        self.assertTrue(fetched["fetch_head_written"])
        self.assertTrue(fetched["tracking_ref_updated"])

        local = sync.audit_worktree_base_sync(str(topic), "refs/remotes/origin/main")
        self.assertTrue(local["ok"], local)
        self.assertEqual(local["status"], "diverged")
        self.assertEqual(local["head_oid"], topic_oid)
        self.assertEqual(local["base_oid"], base_oid)
        self.assertEqual(local["merge_base_oid"], baseline)
        self.assertEqual((local["ahead_by"], local["behind_by"]), (1, 1))
        self.assertEqual(local["publication_status"], "unknown")
        self.assertFalse(local["network_accessed"])

        live = sync.audit_worktree_base_sync(
            str(topic), "refs/remotes/origin/main", "origin"
        )
        self.assertTrue(live["ok"], live)
        self.assertEqual(live["publication_status"], "unpublished")
        self.assertIsNone(live["publication_remote_oid"])
        self.assertTrue(live["network_accessed"])

    def test_fetch_updates_only_requested_ref_and_rejects_rewind(self) -> None:
        bare, seed, topic, initial = self.init_remote()
        self.git(seed, "branch", "side", "main")
        self.git(seed, "checkout", "side")
        side_tip = self.commit_file(seed, "side.txt", "side one\n", "side one")
        self.git(seed, "push", "origin", "side")
        self.git(seed, "checkout", "main")
        base_tip = self.advance_main(seed)

        self.git(
            topic,
            "config",
            "remote.origin.fetch",
            "+refs/heads/*:refs/remotes/origin/*",
        )
        self.git(topic, "config", "fetch.prune", "true")
        self.git(topic, "config", "fetch.pruneTags", "true")
        self.git(bare, "update-ref", "refs/tags/remote-only", side_tip)
        self.git(topic, "update-ref", "refs/remotes/origin/side", initial)

        fetched = sync.fetch_repository_branch(str(topic), "origin", "main")
        self.assertTrue(fetched["ok"], fetched)
        self.assertEqual(fetched["fetched_oid"], base_tip)
        self.assertEqual(self.oid(topic, "refs/remotes/origin/main"), base_tip)
        self.assertEqual(self.oid(topic, "refs/remotes/origin/side"), initial)
        self.assertNotEqual(
            self.git(
                topic,
                "show-ref",
                "--verify",
                "--hash",
                "refs/tags/remote-only",
                check=False,
            ).returncode,
            0,
        )

        self.git(bare, "update-ref", "refs/heads/main", initial)
        rewind = sync.fetch_repository_branch(str(topic), "origin", "main")
        self.assertFalse(rewind["ok"])
        self.assertEqual(rewind["error_code"], "fetch_rewind_rejected")
        self.assertTrue(rewind["fetch_head_written"])
        self.assertFalse(rewind["tracking_ref_updated"])
        self.assertEqual(self.oid(topic, "refs/remotes/origin/main"), base_tip)

    def test_fetch_rejects_symbolic_destination_and_compare_swap_race(self) -> None:
        _, seed, topic, initial = self.init_remote()
        base_tip = self.advance_main(seed)
        ref = "refs/remotes/origin/main"
        self.git(topic, "update-ref", ref, initial)
        self.assertEqual(self.oid(topic, ref), initial)
        competitor_oid = self.add_topic_commit(topic)
        real_git = sync._git
        raced = False

        def race_before_ref_update(root: str, *args: str):
            nonlocal raced
            if args[:3] == ("update-ref", "--no-deref", ref) and not raced:
                raced = True
                self.git(topic, "update-ref", ref, competitor_oid)
            return real_git(root, *args)

        with patch.object(sync, "_git", side_effect=race_before_ref_update):
            result = sync.fetch_repository_branch(str(topic), "origin", "main")
        self.assertTrue(raced)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "fetch_ref_update_failed")
        self.assertTrue(result["needs_review"])
        self.assertFalse(result["tracking_ref_updated"])
        self.assertEqual(self.oid(topic, ref), competitor_oid)
        self.assertNotEqual(self.oid(topic, ref), base_tip)

        symbolic_repo = self.root / "symbolic fetch checkout"
        self.git(
            seed,
            "worktree",
            "add",
            "-b",
            "feat/symbolic-test",
            str(symbolic_repo),
            "main",
        )
        self.git(symbolic_repo, "update-ref", "refs/remotes/origin/side", initial)
        self.git(symbolic_repo, "symbolic-ref", ref, "refs/remotes/origin/side")
        before = self.oid(symbolic_repo, "refs/remotes/origin/side")
        symbolic = sync.fetch_repository_branch(str(symbolic_repo), "origin", "main")
        self.assertFalse(symbolic["ok"])
        self.assertEqual(symbolic["error_code"], "symbolic_ref_rejected")
        self.assertFalse(symbolic["network_accessed"])
        self.assertEqual(self.oid(symbolic_repo, "refs/remotes/origin/side"), before)

    def test_unpublished_rebase_preserves_topic_and_other_refs(self) -> None:
        _bare, seed, topic, _ = self.init_remote()
        old_topic = self.add_topic_commit(topic)
        self.git(topic, "branch", "feat/other", old_topic)
        self.git(topic, "config", "rebase.updateRefs", "true")
        self.git(topic, "config", "rebase.autoStash", "true")
        main_before = self.oid(seed, "main")
        base_oid = self.advance_main(seed)
        fetched = sync.fetch_repository_branch(str(topic), "origin", "main")
        self.assertTrue(fetched["ok"], fetched)

        result = sync.rebase_repository_branch(
            str(topic),
            "feat/topic",
            "refs/remotes/origin/main",
            old_topic,
            base_oid,
            remote="origin",
        )
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["rebased"])
        self.assertEqual(result["head_oid_before"], old_topic)
        self.assertTrue(
            self.git(topic, "merge-base", "--is-ancestor", base_oid, "HEAD").returncode
            == 0
        )
        self.assertEqual(
            self.git(topic, "show", "-s", "--format=%s", "HEAD").stdout.strip(),
            "topic work",
        )
        self.assertEqual(
            (topic / "topic.txt").read_text(encoding="utf-8"), "topic work\n"
        )
        self.assertEqual(
            (topic / "base.txt").read_text(encoding="utf-8"), "base update\n"
        )
        self.assertEqual(self.oid(topic, "refs/heads/feat/other"), old_topic)
        self.assertEqual(self.oid(seed, "refs/heads/main"), base_oid)
        self.assertEqual(self.oid(seed, "HEAD"), base_oid)
        self.assertNotEqual(main_before, base_oid)
        self.assertEqual(self.git(seed, "status", "--porcelain").stdout, "")

    def test_published_branch_rebase_rejected_even_without_tracking_ref(self) -> None:
        _, _, topic, _ = self.init_remote()
        topic_oid = self.add_topic_commit(topic)
        self.git(topic, "push", "origin", "feat/topic")
        self.git(topic, "update-ref", "-d", "refs/remotes/origin/feat/topic")

        audit = sync.audit_worktree_base_sync(str(topic), "main", "origin")
        self.assertEqual(audit["publication_status"], "published")
        self.assertEqual(audit["publication_remote_oid"], topic_oid)
        self.assertTrue(audit["network_accessed"])

        result = sync.rebase_repository_branch(
            str(topic),
            "feat/topic",
            "main",
            topic_oid,
            self.oid(topic, "main"),
            remote="origin",
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "published_branch")
        self.assertFalse(result["needs_review"])
        self.assertEqual(self.oid(topic, "HEAD"), topic_oid)

    def test_published_merge_keeps_old_head_and_can_push_without_force(self) -> None:
        bare, seed, topic, _ = self.init_remote()
        topic_oid = self.add_topic_commit(topic)
        self.git(topic, "push", "-u", "origin", "feat/topic")
        base_oid = self.advance_main(seed)
        fetched = sync.fetch_repository_branch(str(topic), "origin", "main")
        self.assertTrue(fetched["ok"], fetched)
        self.git(topic, "config", "merge.ff", "false")

        result = sync.merge_repository_branch(
            str(topic),
            "feat/topic",
            "refs/remotes/origin/main",
            topic_oid,
            base_oid,
            "origin",
        )
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["merge_type"], "merge_commit")
        self.assertEqual(result["publication_remote_oid"], topic_oid)
        parents = (
            self.git(topic, "rev-list", "--parents", "-n", "1", "HEAD")
            .stdout.strip()
            .split()[1:]
        )
        self.assertIn(topic_oid, parents)
        self.assertIn(base_oid, parents)
        pushed = self.git(topic, "push", "origin", "feat/topic")
        self.assertEqual(pushed.returncode, 0, pushed.stderr)
        self.assertEqual(
            self.oid(bare, "refs/heads/feat/topic"), result["head_oid_after"]
        )

    def test_stale_dirty_detached_missing_ref_and_network_failure_fail_closed(
        self,
    ) -> None:
        _, _seed, topic, _ = self.init_remote()
        topic_oid = self.add_topic_commit(topic)
        base_oid = self.oid(topic, "main")
        stale_head = sync.rebase_repository_branch(
            str(topic), "feat/topic", "main", "f" * 40, base_oid
        )
        self.assertEqual(stale_head["error_code"], "stale_oid")
        stale_base = sync.rebase_repository_branch(
            str(topic), "feat/topic", "main", topic_oid, "e" * 40
        )
        self.assertEqual(stale_base["error_code"], "stale_oid")
        missing = sync.audit_worktree_base_sync(str(topic), "refs/heads/missing")
        self.assertFalse(missing["ok"])
        self.assertEqual(missing["error_code"], "base_ref_missing")

        (topic / "dirty.txt").write_text("keep me\n", encoding="utf-8")
        dirty = sync.rebase_repository_branch(
            str(topic), "feat/topic", "main", topic_oid, base_oid
        )
        self.assertEqual(dirty["error_code"], "dirty_worktree")
        self.assertEqual((topic / "dirty.txt").read_text(encoding="utf-8"), "keep me\n")
        (topic / "dirty.txt").unlink()

        self.git(topic, "checkout", "--detach", "HEAD")
        detached = sync.audit_worktree_base_sync(str(topic), "main")
        self.assertEqual(detached["status"], "blocked")
        self.assertTrue(detached["detached"])

        self.git(topic, "checkout", "feat/topic")
        unavailable_remote = self.root / "missing remote.git"
        self.git(topic, "remote", "set-url", "origin", str(unavailable_remote))
        before = self.oid(topic, "HEAD")
        result = sync.rebase_repository_branch(
            str(topic), "feat/topic", "main", before, base_oid, remote="origin"
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "publication_check_failed")
        self.assertTrue(result["network_accessed"])
        self.assertFalse(result["needs_review"])
        self.assertEqual(self.oid(topic, "HEAD"), before)

    def test_rebase_and_merge_conflicts_remain_unresolved_for_review(self) -> None:
        _, seed, topic, _ = self.init_remote()
        self.commit_file(topic, "shared.txt", "topic side\n", "topic edit")
        topic_oid = self.oid(topic, "HEAD")
        base_oid = self.commit_file(seed, "shared.txt", "base side\n", "base edit")
        self.git(seed, "push", "origin", "main")
        self.assertTrue(
            sync.fetch_repository_branch(str(topic), "origin", "main")["ok"]
        )
        result = sync.rebase_repository_branch(
            str(topic), "feat/topic", "refs/remotes/origin/main", topic_oid, base_oid
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "rebase_conflict")
        self.assertTrue(result["needs_review"])
        self.assertIn("shared.txt", result["conflict_paths"])
        self.assertTrue(
            self.git(topic, "rev-parse", "--git-path", "rebase-merge").stdout.strip()
        )
        self.assertNotEqual(self.git(topic, "status", "--porcelain").stdout, "")

        _, seed2, topic2, _ = self.init_remote()
        topic2_oid = self.commit_file(
            topic2, "shared.txt", "topic side\n", "topic edit"
        )
        self.git(topic2, "push", "-u", "origin", "feat/topic")
        base2_oid = self.commit_file(seed2, "shared.txt", "base side\n", "base edit")
        self.git(seed2, "push", "origin", "main")
        self.assertTrue(
            sync.fetch_repository_branch(str(topic2), "origin", "main")["ok"]
        )
        merge = sync.merge_repository_branch(
            str(topic2), "feat/topic", "refs/remotes/origin/main", topic2_oid, base2_oid
        )
        self.assertFalse(merge["ok"])
        self.assertEqual(merge["error_code"], "merge_conflict")
        self.assertTrue(merge["needs_review"])
        self.assertIn("shared.txt", merge["conflict_paths"])
        self.assertEqual(
            self.git(
                topic2, "rev-parse", "--verify", "MERGE_HEAD", check=False
            ).returncode,
            0,
        )

    def test_old_boundary_replays_only_child_commits_after_parent_squash(self) -> None:
        bare, seed, _, _ = self.init_remote()
        parent = self.root / "parent linked checkout"
        child = self.root / "child linked checkout"
        self.git(seed, "worktree", "add", "-b", "feat/parent", str(parent), "main")
        parent_oid = self.commit_file(
            parent, "parent.txt", "parent content\n", "parent work"
        )
        self.git(seed, "worktree", "add", "-b", "feat/child", str(child), "feat/parent")
        child_oid = self.commit_file(
            child, "child.txt", "child content\n", "child work"
        )

        self.git(seed, "checkout", "main")
        self.commit_file(seed, "parent.txt", "parent content\n", "squashed parent")
        self.git(seed, "push", "origin", "main")
        base_oid = sync.fetch_repository_branch(str(child), "origin", "main")[
            "fetched_oid"
        ]
        self.assertIsNotNone(base_oid)

        result = sync.rebase_repository_branch(
            str(child),
            "feat/child",
            "refs/remotes/origin/main",
            child_oid,
            base_oid,
            parent_oid,
        )
        self.assertTrue(result["ok"], result)
        self.assertTrue(
            self.git(child, "merge-base", "--is-ancestor", base_oid, "HEAD").returncode
            == 0
        )
        self.assertNotEqual(
            self.git(
                child, "merge-base", "--is-ancestor", parent_oid, "HEAD", check=False
            ).returncode,
            0,
        )
        self.assertEqual(
            self.git(child, "show", "-s", "--format=%s", "HEAD").stdout.strip(),
            "child work",
        )
        self.assertTrue((child / "parent.txt").exists())
        self.assertEqual(
            (child / "child.txt").read_text(encoding="utf-8"), "child content\n"
        )
        self.assertTrue((bare / "HEAD").exists())

    def test_ignored_path_collision_is_rejected_without_overwriting_user_file(
        self,
    ) -> None:
        _, seed, topic, _ = self.init_remote()
        self.commit_file(seed, ".gitignore", "private.dat\n", "ignore private file")
        self.git(seed, "push", "origin", "main")
        self.git(topic, "merge", "--ff-only", "main")
        topic_oid = self.add_topic_commit(topic)
        base_before = self.oid(topic, "refs/remotes/origin/main")
        private = topic / "private.dat"
        private.write_text("user content must survive\n", encoding="utf-8")
        self.commit_file(seed, ".gitignore", "", "stop ignoring private path")
        base_oid = self.commit_file(
            seed, "private.dat", "tracked base content\n", "track formerly ignored path"
        )
        self.git(seed, "push", "origin", "main")
        fetched = sync.fetch_repository_branch(str(topic), "origin", "main")
        self.assertTrue(fetched["ok"], fetched)
        self.assertNotEqual(base_before, base_oid)

        result = sync.rebase_repository_branch(
            str(topic), "feat/topic", "refs/remotes/origin/main", topic_oid, base_oid
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "ignored_path_collision")
        self.assertEqual(result["ignored_path_collisions"], ["private.dat"])
        self.assertFalse(result["needs_review"])
        self.assertEqual(
            private.read_text(encoding="utf-8"), "user content must survive\n"
        )
        self.assertEqual(self.oid(topic, "HEAD"), topic_oid)

        _, seed2, topic2, _ = self.init_remote()
        self.commit_file(seed2, ".gitignore", "private.dat\n", "ignore private file")
        self.git(seed2, "push", "origin", "main")
        self.git(topic2, "merge", "--ff-only", "main")
        topic2_oid = self.add_topic_commit(topic2)
        self.git(topic2, "push", "-u", "origin", "feat/topic")
        private2 = topic2 / "private.dat"
        private2.write_text("keep this ignored file\n", encoding="utf-8")
        self.commit_file(seed2, ".gitignore", "", "stop ignoring private path")
        base2_oid = self.commit_file(
            seed2, "private.dat", "new tracked base content\n", "track ignored path"
        )
        self.git(seed2, "push", "origin", "main")
        self.assertTrue(
            sync.fetch_repository_branch(str(topic2), "origin", "main")["ok"]
        )
        merge = sync.merge_repository_branch(
            str(topic2), "feat/topic", "refs/remotes/origin/main", topic2_oid, base2_oid
        )
        self.assertEqual(merge["error_code"], "ignored_path_collision")
        self.assertEqual(merge["ignored_path_collisions"], ["private.dat"])
        self.assertEqual(
            private2.read_text(encoding="utf-8"), "keep this ignored file\n"
        )
        self.assertEqual(self.oid(topic2, "HEAD"), topic2_oid)

    def test_merge_rejects_branch_merge_options_that_change_merge_semantics(
        self,
    ) -> None:
        _, seed, topic, _ = self.init_remote()
        topic_oid = self.add_topic_commit(topic)
        self.git(topic, "push", "-u", "origin", "feat/topic")
        base_oid = self.advance_main(seed)
        self.assertTrue(
            sync.fetch_repository_branch(str(topic), "origin", "main")["ok"]
        )
        self.git(topic, "config", "branch.feat/topic.mergeOptions", "-s ours")

        result = sync.merge_repository_branch(
            str(topic), "feat/topic", "refs/remotes/origin/main", topic_oid, base_oid
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "merge_options_rejected")
        self.assertFalse(result["action_started"])
        self.assertFalse(result["needs_review"])
        self.assertEqual(self.oid(topic, "HEAD"), topic_oid)

    def test_post_action_readback_failure_marks_uncertain_write_for_review(
        self,
    ) -> None:
        _, seed, topic, _ = self.init_remote()
        topic_oid = self.add_topic_commit(topic)
        base_oid = self.advance_main(seed)
        self.assertTrue(
            sync.fetch_repository_branch(str(topic), "origin", "main")["ok"]
        )
        with patch.object(
            sync,
            "_clean_readback",
            side_effect=sync._SyncFailure("readback_unavailable", "synthetic"),
        ):
            result = sync.rebase_repository_branch(
                str(topic),
                "feat/topic",
                "refs/remotes/origin/main",
                topic_oid,
                base_oid,
            )
        self.assertFalse(result["ok"])
        self.assertTrue(result["action_started"])
        self.assertTrue(result["rebased"])
        self.assertTrue(result["needs_review"])
        self.assertNotEqual(self.oid(topic, "HEAD"), topic_oid)

        _, seed2, topic2, _ = self.init_remote()
        topic2_oid = self.add_topic_commit(topic2)
        self.git(topic2, "push", "-u", "origin", "feat/topic")
        base2_oid = self.advance_main(seed2)
        self.assertTrue(
            sync.fetch_repository_branch(str(topic2), "origin", "main")["ok"]
        )
        with patch.object(
            sync,
            "_clean_readback",
            side_effect=sync._SyncFailure("readback_unavailable", "synthetic"),
        ):
            merged = sync.merge_repository_branch(
                str(topic2),
                "feat/topic",
                "refs/remotes/origin/main",
                topic2_oid,
                base2_oid,
            )
        self.assertFalse(merged["ok"])
        self.assertTrue(merged["action_started"])
        self.assertTrue(merged["merged"])
        self.assertTrue(merged["needs_review"])
        self.assertNotEqual(self.oid(topic2, "HEAD"), topic2_oid)


class WorktreeBaseSyncMcpTests(unittest.IsolatedAsyncioTestCase):
    async def test_audit_is_discoverable_and_callable_with_synthetic_input(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="mcp base audit ") as temp:
            repo = Path(temp) / "repo"
            repo.mkdir()
            (
                await asyncio.to_thread(
                    subprocess.run, ["git", "init", "-q"], cwd=repo, check=True
                )
            )
            (
                await asyncio.to_thread(
                    subprocess.run,
                    ["git", "config", "user.name", "Synthetic"],
                    cwd=repo,
                    check=True,
                )
            )
            (
                await asyncio.to_thread(
                    subprocess.run,
                    ["git", "config", "user.email", "fixture@example.invalid"],
                    cwd=repo,
                    check=True,
                )
            )
            (repo / "base.txt").write_text("base\n", encoding="utf-8")
            (
                await asyncio.to_thread(
                    subprocess.run, ["git", "add", "base.txt"], cwd=repo, check=True
                )
            )
            (
                await asyncio.to_thread(
                    subprocess.run,
                    ["git", "commit", "-m", "baseline"],
                    cwd=repo,
                    check=True,
                )
            )
            (
                await asyncio.to_thread(
                    subprocess.run,
                    ["git", "branch", "-M", "main"],
                    cwd=repo,
                    check=True,
                )
            )
            base_oid = (
                await asyncio.to_thread(
                    subprocess.run,
                    ["git", "rev-parse", "HEAD"],
                    cwd=repo,
                    check=True,
                    capture_output=True,
                    text=True,
                )
            ).stdout.strip()

            raw = await complete_server.call_tool(
                "audit_worktree_base_sync",
                {"repo_path": str(repo), "base_ref": "main", "remote": None},
            )
            self.assertFalse(raw.is_error)
            payload = json.loads(raw.content[0].text)
            self.assertTrue(payload["ok"], payload)
            self.assertEqual(payload["status"], "up_to_date")
            self.assertEqual(payload["head_oid"], base_oid)
            self.assertEqual(payload["publication_status"], "unknown")
            self.assertFalse(payload["network_accessed"])
