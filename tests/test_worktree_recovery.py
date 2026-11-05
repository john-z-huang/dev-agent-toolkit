from __future__ import annotations

import unittest
from unittest.mock import patch

import test_worktree_base_sync as fixtures
from dev_workflow_standards_tools.services import worktree_sync as sync
from dev_workflow_standards_tools.services import worktree_recovery as recovery


class WorktreeRecoveryTests(fixtures.WorktreeBaseSyncTests):
    # Reuse fixture utilities without rerunning the inherited P0 cases.
    def conflict(self, kind='merge', *, twice=False):
        bare, seed, topic, baseline = self.init_remote()
        original = self.commit_file(topic, 'shared.txt', 'topic one\n', 'topic one')
        if twice:
            original = self.commit_file(topic, 'shared.txt', 'topic two\n', 'topic two')
        if kind == 'merge':
            self.git(topic, 'push', 'origin', 'feat/topic')
        base = self.commit_file(seed, 'shared.txt', 'base side\n', 'base edit')
        self.git(seed, 'push', 'origin', 'main')
        self.assertTrue(sync.fetch_repository_branch(str(topic), 'origin', 'main')['ok'])
        action = sync.merge_repository_branch if kind == 'merge' else sync.rebase_repository_branch
        result = action(str(topic), 'feat/topic', 'refs/remotes/origin/main', original, base)
        self.assertEqual(result['error_code'], f'{kind}_conflict', result)
        return bare, seed, topic, original, base

    def request(self, topic):
        audit = sync.audit_worktree_base_sync(str(topic), 'refs/remotes/origin/main')
        context = audit['recovery_context']
        self.assertEqual(context['status'], 'managed_in_progress', audit)
        return dict(repo_path=str(topic), operation_id=context['operation_id'],
                    expected_current_head_oid=context['current_head_oid'],
                    expected_state_fingerprint=audit['current_state_fingerprint'])

    def resolve(self, topic, content='resolved\n'):
        (topic / 'shared.txt').write_text(content)
        self.git(topic, 'add', 'shared.txt')

    def test_recovery_continue_preserves_untracked_and_ignored(self):
        for kind in ('merge', 'rebase'):
            with self.subTest(kind=kind):
                _, _, topic, _, _ = self.conflict(kind)
                self.resolve(topic)
                (topic / 'notes.txt').write_text('keep me\n')
                self.git(topic, 'config', 'core.excludesFile', str(self.root / 'ignore'))
                (self.root / 'ignore').write_text('deps/\n')
                (topic / 'deps').mkdir()
                (topic / 'deps' / 'large').write_bytes(b'x' * (9 * 1024 * 1024))
                for i in range(4100):
                    (topic / 'deps' / str(i)).touch()
                result = getattr(sync, f'continue_repository_{kind}')(**self.request(topic))
                self.assertTrue(result['ok'], result)
                self.assertTrue(result['completed'])
                self.assertEqual((topic / 'notes.txt').read_text(), 'keep me\n')
                self.assertEqual((topic / 'deps' / 'large').stat().st_size, 9 * 1024 * 1024)
                self.assertEqual(recovery.recovery_snapshot(str(topic.resolve()), git=sync._git)['recovery_context']['status'], 'none')

    def test_recovery_abort_offline_preserves_untracked(self):
        for kind in ('merge', 'rebase'):
            _, _, topic, original, _ = self.conflict(kind)
            self.resolve(topic)
            (topic / 'notes').write_text('keep')
            request = self.request(topic)
            self.git(topic, 'remote', 'set-url', 'origin', str(self.root / 'missing.git'))
            # Remote configuration changes need a fresh fingerprint.
            request = self.request(topic)
            result = getattr(sync, f'abort_repository_{kind}')(**request, confirm_discard_resolution_work=True)
            self.assertTrue(result['ok'], result)
            self.assertEqual(self.oid(topic, 'HEAD'), original)
            self.assertEqual((topic / 'notes').read_text(), 'keep')

    def test_recovery_unresolved_unstaged_stale_and_locked_rejected(self):
        _, _, topic, _, _ = self.conflict()
        request = self.request(topic)
        self.assertEqual(sync.continue_repository_merge(**request)['error_code'], 'unmerged_index')
        self.resolve(topic)
        self.assertEqual(sync.continue_repository_merge(**request)['error_code'], 'stale_state_fingerprint')
        (topic / 'shared.txt').write_text('unstaged')
        self.assertEqual(sync.continue_repository_merge(**self.request(topic))['error_code'], 'unstaged_resolution')
        self.resolve(topic)
        self.git(topic, 'worktree', 'lock', str(topic))
        result = sync.continue_repository_merge(**self.request(topic))
        self.assertEqual(result['error_code'], 'worktree_locked', result)
        self.assertFalse(result['action_started'])

    def test_rebase_publication_and_successive_conflicts(self):
        _, _, topic, _, _ = self.conflict('rebase', twice=True)
        self.resolve(topic, 'first resolution\n')
        result = sync.continue_repository_rebase(**self.request(topic))
        self.assertFalse(result['ok'], result)
        self.assertTrue(result['still_in_progress'], result)
        self.assertTrue(result['needs_review'], result)
        self.resolve(topic, 'second resolution\n')
        self.git(topic, 'push', 'origin', 'refs/heads/feat/topic:refs/heads/feat/topic')
        result = sync.continue_repository_rebase(**self.request(topic))
        self.assertEqual(result['error_code'], 'published_branch', result)
        self.assertFalse(result['action_started'])
        self.git(topic, 'push', 'origin', '--delete', 'feat/topic')
        self.assertTrue(sync.continue_repository_rebase(**self.request(topic))['ok'])

    def test_tampered_record_native_cross_worktree_and_unrelated_rename(self):
        import json
        from pathlib import Path
        _, seed, topic, _, _ = self.conflict()
        self.resolve(topic)
        request = self.request(topic)
        self.assertFalse(sync.continue_repository_merge(**{**request, 'operation_id': '00000000-0000-0000-0000-000000000000'})['action_started'])
        self.assertFalse(sync.continue_repository_merge(**{**request, 'expected_current_head_oid': 'f' * 40})['action_started'])
        self.assertFalse(sync.continue_repository_merge(**{**request, 'repo_path': str(seed)})['action_started'])
        self.git(topic, 'mv', 'shared.txt', 'unrelated.txt')
        result = sync.continue_repository_merge(**self.request(topic))
        self.assertEqual(result['error_code'], 'unrelated_staged_paths', result)
        self.git(topic, 'mv', 'unrelated.txt', 'shared.txt')
        request = self.request(topic)
        _, record_path = recovery._record_path(str(topic.resolve()), sync._git)
        record_path.write_text(json.dumps(json.loads(record_path.read_text()), indent=2))
        result = sync.continue_repository_merge(**request)
        self.assertFalse(result['action_started'], result)
        self.assertEqual(result['error_code'], 'recovery_record_invalid', result)

    def test_rebase_original_ref_lock_and_complex_todo_refused(self):
        from pathlib import Path
        _, _, topic, _, _ = self.conflict('rebase')
        self.resolve(topic)
        lock = Path(self.git(topic, 'rev-parse', '--git-path', 'refs/heads/feat/topic.lock').stdout.strip())
        if not lock.is_absolute():
            lock = topic / lock
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.touch()
        result = sync.continue_repository_rebase(**self.request(topic))
        self.assertEqual(result['error_code'], 'worktree_locked', result)
        self.assertFalse(result['action_started'])
        lock.unlink()
        request = self.request(topic)
        directory = Path(self.git(topic, 'rev-parse', '--absolute-git-dir').stdout.strip()) / 'rebase-merge'
        (directory / 'git-rebase-todo').write_text('exec true\n')
        result = sync.continue_repository_rebase(**request)
        self.assertFalse(result['action_started'], result)
        self.assertEqual(result['error_code'], 'recovery_todo_unsupported', result)

    def test_normal_merge_hook_and_postaction_verification_failure(self):
        from pathlib import Path
        _, _, topic, _, _ = self.conflict()
        self.resolve(topic)
        hooks = self.root / 'hooks'
        hooks.mkdir()
        marker = self.root / 'hook-ran'
        hook = hooks / 'pre-commit'
        hook.write_text('#!/bin/sh\ntouch "' + str(marker) + '"\n')
        hook.chmod(0o755)
        self.git(topic, 'config', 'core.hooksPath', str(hooks))
        with patch.object(recovery, 'verify_protected_worktree', side_effect=recovery._RecoveryFailure('synthetic_readback', 'synthetic')):
            result = sync.continue_repository_merge(**self.request(topic))
        self.assertTrue(result['action_started'], result)
        self.assertTrue(result['needs_review'], result)
        self.assertEqual(result['error_code'], 'synthetic_readback', result)
        self.assertTrue(marker.exists())

    def test_deleted_resolution_missing_parent_and_merge_native_tamper(self):
        from pathlib import Path
        _, seed, topic, _ = self.init_remote()
        self.commit_file(seed, 'd/f', 'base\n', 'add nested')
        self.git(topic, 'merge', '--ff-only', 'main')
        original = self.commit_file(topic, 'd/f', 'topic\n', 'topic')
        self.git(topic, 'push', 'origin', 'feat/topic')
        base = self.commit_file(seed, 'd/f', 'main\n', 'main')
        self.git(seed, 'push', 'origin', 'main')
        self.assertTrue(sync.fetch_repository_branch(str(topic), 'origin', 'main')['ok'])
        self.assertEqual(sync.merge_repository_branch(str(topic), 'feat/topic', 'refs/remotes/origin/main', original, base)['error_code'], 'merge_conflict')
        self.git(topic, 'rm', 'd/f')
        self.assertFalse((topic / 'd').exists())
        request = self.request(topic)
        gitdir = Path(self.git(topic, 'rev-parse', '--absolute-git-dir').stdout.strip())
        saved = (gitdir / 'ORIG_HEAD').read_bytes()
        (gitdir / 'ORIG_HEAD').write_text(base + '\n')
        self.assertFalse(sync.continue_repository_merge(**request)['action_started'])
        (gitdir / 'ORIG_HEAD').write_bytes(saved)
        (gitdir / 'MERGE_AUTOSTASH').write_text(original + '\n')
        self.assertFalse(sync.continue_repository_merge(**request)['action_started'])
        (gitdir / 'MERGE_AUTOSTASH').unlink()
        result = sync.continue_repository_merge(**self.request(topic))
        self.assertTrue(result['ok'], result)
        self.assertFalse((topic / 'd').exists())

    def test_unmanaged_operation_refused(self):
        _, seed, topic, _ = self.init_remote()
        self.commit_file(topic, 'shared.txt', 'topic\n', 'topic')
        self.commit_file(seed, 'shared.txt', 'main\n', 'main')
        self.git(topic, 'merge', 'main', check=False)
        audit = sync.audit_worktree_base_sync(str(topic), 'main')
        self.assertEqual(audit['recovery_context']['status'], 'unmanaged', audit)
        result = sync.abort_repository_merge(str(topic), '11111111-1111-4111-8111-111111111111', self.oid(topic, 'HEAD'), 'a' * 64, True)
        self.assertFalse(result['action_started'])

    def test_p0_symbolic_branch_alias_refused_before_action(self):
        _, seed, topic, _ = self.init_remote()
        original = self.commit_file(topic, 'topic.txt', 'topic\n', 'topic')
        base = self.commit_file(seed, 'base.txt', 'main\n', 'main')
        self.git(seed, 'push', 'origin', 'main')
        self.assertTrue(sync.fetch_repository_branch(str(topic), 'origin', 'main')['ok'])
        self.git(topic, 'branch', 'other', original)
        self.git(topic, 'symbolic-ref', 'refs/heads/feat/topic', 'refs/heads/other')
        result = sync.rebase_repository_branch(str(topic), 'feat/topic', 'refs/remotes/origin/main', original, base)
        self.assertFalse(result['ok'], result)
        self.assertFalse(result['action_started'], result)
        self.assertEqual(self.oid(topic, 'refs/heads/other'), original)

    def test_abort_acknowledgement_strict_at_service_boundary(self):
        for value in (False, None, 'true', 1, 0):
            result = sync.abort_repository_merge('/missing', 'bad', 'bad', 'bad', value)
            self.assertEqual(result['error_code'], 'discard_acknowledgement_required')

    def test_recovery_failure_after_action_retains_record(self):
        _, _, topic, _, _ = self.conflict()
        self.resolve(topic)
        with patch.object(recovery, 'clear_managed_operation', side_effect=recovery._RecoveryFailure('synthetic_cleanup_failure', 'synthetic')):
            result = sync.continue_repository_merge(**self.request(topic))
        self.assertTrue(result['action_started'], result)
        self.assertTrue(result['needs_review'], result)
        self.assertEqual(result['error_code'], 'synthetic_cleanup_failure')
        self.assertEqual(sync._recovery_fields(str(topic.resolve()))['recovery_context']['status'], 'needs_review')


# The fixture base is intentionally shared; only this class's recovery cases run here.
for _name in tuple(fixtures.WorktreeBaseSyncTests.__dict__):
    if _name.startswith('test_'):
        setattr(WorktreeRecoveryTests, _name, None)

if __name__ == '__main__':
    unittest.main()
