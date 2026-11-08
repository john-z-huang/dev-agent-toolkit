from __future__ import annotations

import json
import re
import unittest
from importlib.resources import files
from unittest.mock import patch

from codex_session_fixtures import DOC, source
from dev_workflow_standards_tools.services import codex_session_facts as service
from dev_workflow_standards_tools.services.codex_session_facts import (
    CodexSessionSource,
    get_codex_session_summary_guidance,
    order_codex_session_sources,
    prepare_codex_session_memory,
)


class GuidanceTests(unittest.TestCase):
    def test_resource_questions_and_template_match_reference(self) -> None:
        resource = json.loads(
            files("dev_workflow_standards_tools")
            .joinpath("resources/codex_session_summary.json")
            .read_text(encoding="utf-8")
        )
        document = DOC.read_text(encoding="utf-8")
        section = document.split("## 默认阅读问题\n", 1)[1].split(
            "\n## Serena Memory", 1
        )[0]
        questions = []
        for line in section.splitlines():
            if not line.startswith("|") or line.startswith(("| 摘要主题", "|---")):
                continue
            _, topic, question, _ = line.split("|", 3)
            questions.append(f"{topic.strip()}：{question.strip()}")
        template = re.search(r"```markdown\n(.*?)\n```", document, re.DOTALL)
        self.assertIsNotNone(template)
        self.assertEqual(resource["default_questions"], questions)
        self.assertEqual(resource["default_template"], template.group(1))

    def test_guidance_defaults_include_limits_and_followups(self) -> None:
        result = get_codex_session_summary_guidance()
        self.assertEqual(len(result["questions"]), 7)
        self.assertIn("# <created_at>", result["template"])
        self.assertFalse(result["customized"])
        self.assertFalse(result["reads_history"])
        self.assertFalse(result["writes_memory"])
        self.assertTrue(any("read_thread" in step for step in result["next_steps"]))

    def test_custom_questions_and_template_replace_defaults(self) -> None:
        template = "# user format\n\nraw body"
        result = get_codex_session_summary_guidance(["只核实目标"], template)
        self.assertEqual(result["questions"], ["只核实目标"])
        self.assertEqual(result["template"], template)
        self.assertTrue(result["customized"])

    def test_explicit_empty_custom_values_are_errors(self) -> None:
        with self.assertRaisesRegex(ValueError, "custom_questions"):
            get_codex_session_summary_guidance([])
        with self.assertRaisesRegex(ValueError, "custom_questions"):
            get_codex_session_summary_guidance([" "])
        with self.assertRaisesRegex(ValueError, "custom_template"):
            get_codex_session_summary_guidance(custom_template="")

    def test_resource_failure_does_not_fabricate_defaults(self) -> None:
        with (
            patch.object(service, "files", side_effect=FileNotFoundError("missing")),
            self.assertRaisesRegex(RuntimeError, "包内"),
        ):
            get_codex_session_summary_guidance()

    def test_fully_custom_guidance_does_not_need_default_resource(self) -> None:
        with patch.object(service, "files", side_effect=FileNotFoundError("missing")):
            result = get_codex_session_summary_guidance(["only question"], "# custom")
        self.assertEqual(result["questions"], ["only question"])
        self.assertEqual(result["template"], "# custom")


class SessionSourceTests(unittest.TestCase):
    A = "00000000-0000-4000-8000-000000000001"
    B = "00000000-0000-4000-8000-000000000002"
    C = "00000000-0000-4000-8000-000000000003"

    def test_source_link_validation_and_id_consistency(self) -> None:
        bad_links = [
            f"codex://user@threads/{self.A}",
            f"codex://threads/{self.A}?x=1",
            f"codex://threads/{self.A}#part",
            f"codex://threads/{self.A}/extra",
            f"codex://threads/{self.A}/",
            f" codex://threads/{self.A}",
            f"codex://threads/{self.A} ",
            f"codex://threads/{self.A}\n",
            f"codex://threads/{self.A}\t",
            "codex://threads/not-a-uuid",
            f"https://threads/{self.A}",
        ]
        for link in bad_links:
            with self.subTest(link=link), self.assertRaises(ValueError):
                CodexSessionSource(source_link=link)
        with self.assertRaisesRegex(ValueError, "不一致"):
            CodexSessionSource(
                source_link=f"codex://threads/{self.A}", thread_id=self.B
            )
        with self.assertRaisesRegex(ValueError, "标准 UUID"):
            CodexSessionSource(source_link=f"codex://threads/{self.A}", thread_id="bad")

    def test_timestamps_require_timezone_and_ended_not_before_created(self) -> None:
        for bad in (
            "2026-01-01T00:00:00",
            "NaN",
            "2026-13-01T00:00:00Z",
            "2026-01-01T00:00:00.1234567Z",
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                source(self.A, created_at=bad)
        with self.assertRaisesRegex(ValueError, "不能早于"):
            source(
                self.A,
                created_at="2026-01-02T00:00:00Z",
                ended_at="2026-01-01T23:59:59Z",
            )

    def test_duplicate_id_merges_missing_metadata_and_timezone_equivalence(
        self,
    ) -> None:
        a_missing = source(self.A, created_at=None, title=None)
        a_complete = source(
            self.A, created_at="2025-12-31T16:00:00-08:00", title="同一会话"
        )
        b = source(self.B, created_at="2026-01-01T00:00:00Z")
        result = order_codex_session_sources([a_missing, a_complete, b])
        self.assertEqual(result["deduplicated_count"], 2)
        self.assertEqual(
            result["priority_groups"][0]["created_at"], "2026-01-01T00:00:00Z"
        )
        self.assertEqual(
            result["priority_groups"][0]["sources"][0]["thread_id"], self.A
        )
        self.assertFalse(result["ready"])
        self.assertTrue(result["priority_groups"][0]["same_creation_time"])

    def test_later_created_session_wins_without_updated_at_inference(self) -> None:
        older = source(self.A, created_at="2026-01-01T00:00:00Z")
        newer = source(self.B, created_at="2026-01-02T00:00:00Z")
        result = order_codex_session_sources([older, newer])
        self.assertEqual(
            result["priority_groups"][0]["sources"][0]["thread_id"], self.B
        )
        self.assertEqual(result["ordering_basis"].count("updatedAt"), 1)
        with self.assertRaises(ValueError):
            CodexSessionSource(
                source_link=f"codex://threads/{self.A}",
                created_at="2026-01-01T00:00:00Z",
                updated_at="2027-01-01T00:00:00Z",
            )

    def test_missing_and_tied_creation_times_require_clarification(self) -> None:
        tied = source(self.A, created_at="2026-01-01T00:00:00Z")
        tied_other = source(self.B, created_at="2025-12-31T19:00:00-05:00")
        missing = source(self.C, created_at=None)
        result = order_codex_session_sources([tied, tied_other, missing])
        self.assertFalse(result["ready"])
        self.assertEqual(len(result["ambiguities"]), 2)
        self.assertTrue(result["priority_groups"][0]["same_creation_time"])
        self.assertIsNone(result["priority_groups"][0]["within_group_order"])
        self.assertEqual(result["missing_created_at"][0]["thread_id"], self.C)

    def test_duplicate_metadata_conflicts_are_errors(self) -> None:
        first = source(self.A, title="旧标题")
        second = source(self.A, title="新标题")
        with self.assertRaisesRegex(ValueError, "title 元数据冲突"):
            order_codex_session_sources([first, second])
        later = source(self.A, created_at="2026-01-02T00:00:00Z")
        with self.assertRaisesRegex(ValueError, "created_at 元数据冲突"):
            order_codex_session_sources([first, later])

    def test_merged_created_and_ended_metadata_is_revalidated(self) -> None:
        created_only = CodexSessionSource(
            source_link=f"codex://threads/{self.A}",
            created_at="2026-01-02T00:00:00Z",
            title="同一会话",
        )
        ended_only = CodexSessionSource(
            source_link=f"codex://threads/{self.A}",
            ended_at="2026-01-01T23:00:00Z",
            title="同一会话",
        )
        with self.assertRaisesRegex(ValueError, "合并后的 ended_at"):
            order_codex_session_sources([created_only, ended_only])


class MemoryPreparationTests(unittest.TestCase):
    THREAD = "00000000-0000-4000-8000-000000000004"
    SUMMARY = "## 用户结构\n\n摘要正文原样保留。"

    def setUp(self) -> None:
        self.source = source(
            self.THREAD,
            created_at="2026-01-02T03:04:05+08:00",
            title="测试 / Safe: 名称",
        )
        self.root = "/tmp/example-repo"

    def test_prepares_safe_payload_unknown_end_and_preserves_summary(self) -> None:
        with patch.object(
            service, "_validated_repo_path", return_value=(self.root, None)
        ):
            result = prepare_codex_session_memory(
                self.root,
                self.source,
                self.SUMMARY,
                ["turn:3", "turn:7"],
            )
        self.assertEqual(result["status"], "prepared")
        self.assertEqual(result["repo_path"], self.root)
        self.assertEqual(result["metadata"]["memory_project_root"], self.root)
        self.assertNotIn("project_scope", result["metadata"])
        self.assertEqual(result["metadata"]["ended_at"], "unknown")
        self.assertTrue(
            result["memory_name"].startswith("codex-sessions/20260101T190405Z-unknown-")
        )
        self.assertTrue(result["memory_name"].endswith(f"-{self.THREAD}"))
        self.assertNotIn("/Safe:", result["memory_name"])
        self.assertTrue(result["payload"]["content"].endswith(self.SUMMARY))
        self.assertEqual(result["payload"]["content"], self.SUMMARY)
        self.assertEqual(
            result["metadata"]["source_link"], f"codex://threads/{self.THREAD}"
        )
        self.assertTrue(result["requires_source_review"])
        self.assertFalse(result["metadata"]["metadata_verified"])

    def test_persistence_disabled_returns_no_payload(self) -> None:
        with patch.object(service, "_validated_repo_path") as repo_validation:
            result = prepare_codex_session_memory(
                self.root,
                self.source,
                "",
                [],
                persistence_allowed=False,
            )
        repo_validation.assert_not_called()
        self.assertEqual(result["status"], "skipped")
        self.assertIsNone(result["payload"])
        self.assertFalse(result["persistence_authorization_verified"])
        self.assertNotIn("memory_name", result)

    def test_empty_summary_or_evidence_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "summary"):
            prepare_codex_session_memory(self.root, self.source, "  ", ["turn:3"])
        with self.assertRaisesRegex(ValueError, "evidence_refs"):
            prepare_codex_session_memory(self.root, self.source, self.SUMMARY, [])
        with self.assertRaisesRegex(ValueError, "evidence_refs"):
            prepare_codex_session_memory(self.root, self.source, self.SUMMARY, [" "])

    def test_topic_rejects_absolute_traversal_and_global(self) -> None:
        for topic in (
            "/tmp",
            "../escape",
            "foo/../bar",
            "global",
            "global/topic",
            "foo\\bar",
            "a//b",
        ):
            with (
                self.subTest(topic=topic),
                patch.object(
                    service, "_validated_repo_path", return_value=(self.root, None)
                ),
                self.assertRaises(ValueError),
            ):
                prepare_codex_session_memory(
                    self.root, self.source, self.SUMMARY, ["turn:3"], topic=topic
                )

    def test_existing_memory_name_is_stable_for_same_thread(self) -> None:
        existing_name = (
            f"codex-sessions/20251231T190405Z-unknown-old-title-{self.THREAD}"
        )
        with patch.object(
            service, "_validated_repo_path", return_value=(self.root, None)
        ):
            result = prepare_codex_session_memory(
                self.root,
                self.source,
                self.SUMMARY,
                ["turn:3"],
                existing_memory_name=existing_name,
            )
        self.assertEqual(result["memory_name"], existing_name)
        with self.assertRaisesRegex(ValueError, "相同 thread_id"):
            prepare_codex_session_memory(
                self.root,
                self.source,
                self.SUMMARY,
                ["turn:3"],
                existing_memory_name=f"codex-sessions/old-{self.THREAD[:-1]}5",
            )

    def test_repo_root_failure_returns_no_payload(self) -> None:
        with patch.object(
            service, "_validated_repo_path", return_value=(None, "not a root")
        ):
            result = prepare_codex_session_memory(
                self.root, self.source, self.SUMMARY, ["turn:3"]
            )
        self.assertFalse(result["ok"])
        self.assertIsNone(result["payload"])
        self.assertEqual(result["error"], "not a root")

    def test_existing_name_cannot_escape_topic(self) -> None:
        for name in (
            f"other/entry-{self.THREAD}",
            f"codex-sessions/../entry-{self.THREAD}",
            f"codex-sessions/nested/entry-{self.THREAD}",
        ):
            with (
                self.subTest(name=name),
                patch.object(
                    service, "_validated_repo_path", return_value=(self.root, None)
                ),
                self.assertRaises(ValueError),
            ):
                prepare_codex_session_memory(
                    self.root,
                    self.source,
                    self.SUMMARY,
                    ["turn:3"],
                    existing_memory_name=name,
                )

    def test_utf8_byte_limits_keep_generated_names_portable(self) -> None:
        long_unicode_source = source(
            self.THREAD,
            title="\U00020000" * 100,
        )
        with patch.object(
            service, "_validated_repo_path", return_value=(self.root, None)
        ):
            result = prepare_codex_session_memory(
                self.root,
                long_unicode_source,
                self.SUMMARY,
                ["turn:3"],
            )
        basename = result["memory_name"].rsplit("/", 1)[1]
        self.assertLessEqual(len(basename.encode("utf-8")), 255)
        slug = basename.split("-", 2)[2].rsplit(f"-{self.THREAD}", 1)[0]
        self.assertLessEqual(len(slug.encode("utf-8")), 96)

        overlong_topic = "界" * 34
        with self.assertRaisesRegex(ValueError, "UTF-8 字节"):
            prepare_codex_session_memory(
                self.root,
                self.source,
                self.SUMMARY,
                ["turn:3"],
                topic=overlong_topic,
            )

        long_existing = f"codex-sessions/{'a' * 220}-{self.THREAD}"
        with self.assertRaisesRegex(ValueError, "逻辑条目最多 252"):
            prepare_codex_session_memory(
                self.root,
                self.source,
                self.SUMMARY,
                ["turn:3"],
                existing_memory_name=long_existing,
            )

        suffix = f"-{self.THREAD}"
        accepted_name = f"codex-sessions/{'a' * (252 - len(suffix))}{suffix}"
        rejected_name = f"codex-sessions/{'a' * (253 - len(suffix))}{suffix}"
        with patch.object(
            service, "_validated_repo_path", return_value=(self.root, None)
        ):
            accepted = prepare_codex_session_memory(
                self.root,
                self.source,
                self.SUMMARY,
                ["turn:3"],
                existing_memory_name=accepted_name,
            )
        self.assertEqual(accepted["memory_name"], accepted_name)
        with self.assertRaisesRegex(ValueError, "逻辑条目最多 252"):
            prepare_codex_session_memory(
                self.root,
                self.source,
                self.SUMMARY,
                ["turn:3"],
                existing_memory_name=rejected_name,
            )


if __name__ == "__main__":
    unittest.main()
