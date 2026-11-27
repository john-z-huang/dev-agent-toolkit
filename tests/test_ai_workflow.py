from __future__ import annotations

import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from ai_workflow_fixtures import (
    API_KEY_A,
    BASE_URL_A,
    choice_answer,
    configured_env,
    decision_response,
)
from dev_agent_toolkit_tools.infrastructure import openai_client
from dev_agent_toolkit_tools.services import ai_workflow
from dev_agent_toolkit_tools.services.ai_workflow import (
    SessionDecisionRequest,
    audit_issue_pr_policy,
    check_branch_names,
    check_commit_message,
    decide_codex_session_action,
)


class DecisionAndValidationTests(unittest.IsolatedAsyncioTestCase):
    async def test_decision_prompts_include_exact_local_rules_and_listed_choice_constraints(
        self,
    ) -> None:
        responses = [
            decision_response(
                choice_answer(
                    "branch_policy", "compliant", ai_workflow.DECISION_CHOICES
                )
            ),
            decision_response(
                choice_answer(
                    "commit_policy", "compliant", ai_workflow.DECISION_CHOICES
                )
            ),
        ]
        with patch.object(
            ai_workflow.openai_client, "create_decision", side_effect=responses
        ) as create:
            branch_result = await check_branch_names(["feat/synthetic"])
            commit_result = await check_commit_message("feat: 增加合成工具")
        self.assertTrue(branch_result["passed"])
        self.assertTrue(commit_result["passed"])
        self.assertEqual(
            create.call_args_list[0].kwargs["purpose"],
            "将已提供的 branch_policy 判断规则应用于本地观测。",
        )
        self.assertEqual(
            create.call_args_list[1].kwargs["purpose"],
            "将已提供的 commit_policy 判断规则应用于本地观测。",
        )
        branch_input, branch_questions = create.call_args_list[0].args
        commit_input, commit_questions = create.call_args_list[1].args
        branch_facts = json.loads(branch_input[0]["content"])
        commit_facts = json.loads(commit_input[0]["content"])
        branch_prompt = branch_questions[0]["instructions"]
        commit_prompt = commit_questions[0]["instructions"]
        self.assertEqual(
            branch_facts,
            {"branch_checks": [{"branch_name": "feat/synthetic", "passed": True}]},
        )
        self.assertEqual(
            commit_facts,
            {
                "inspected_commit": {
                    "subject": "feat: 增加合成工具",
                    "subject_format_valid": True,
                    "chinese_description_present": True,
                    "prohibited_attribution_present": False,
                }
            },
        )
        for expected in (
            repr(sorted(ai_workflow.ROOT_BRANCH_NAMES)),
            repr(ai_workflow.WORK_BRANCH_PATTERN.pattern),
            repr(ai_workflow.FORBIDDEN_AGENT_NAMES),
        ):
            self.assertIn(expected, branch_prompt)
            self.assertNotIn(expected, json.dumps(branch_facts, ensure_ascii=False))
        for expected in (
            repr(ai_workflow.SUBJECT_PATTERN.pattern),
            repr(ai_workflow.CHINESE_PATTERN.pattern),
            repr(ai_workflow.ATTRIBUTION_PATTERN.pattern),
            "中文词语“工具”本身只是普通说明，不是署名。",
            "不得增加风格偏好",
        ):
            self.assertIn(expected, commit_prompt)
            self.assertNotIn(expected, json.dumps(commit_facts, ensure_ascii=False))
        self.assertNotIn("commit_message", commit_facts)
        self.assertNotIn("rules", commit_facts)
        commit_choices = {
            item["value"]: item["description"]
            for item in commit_questions[0]["choices"]
        }
        self.assertIn("subject_format_valid=false", commit_choices["requires_fix"])
        self.assertIn(
            "chinese_description_present=false", commit_choices["requires_fix"]
        )
        self.assertIn(
            "prohibited_attribution_present=true", commit_choices["requires_fix"]
        )
        for prompt in (branch_prompt, commit_prompt):
            self.assertIn("绝不能编造选项值", prompt)
            self.assertIn("仅当本问题列出了证据不足选项", prompt)
            self.assertNotIn("无条件选择 insufficient_evidence", prompt)

    async def test_commit_attribution_uses_local_comment_filter_but_checks_body(
        self,
    ) -> None:
        comment_only = "feat: 增加功能\n# Generated with Codex\n"
        with patch.object(
            ai_workflow.openai_client,
            "create_decision",
            return_value=decision_response(
                choice_answer(
                    "commit_policy", "compliant", ai_workflow.DECISION_CHOICES
                )
            ),
        ) as create:
            accepted = await check_commit_message(comment_only)
        self.assertTrue(accepted["passed"])
        submitted_facts = json.loads(create.call_args.args[0][0]["content"])
        self.assertFalse(
            submitted_facts["inspected_commit"]["prohibited_attribution_present"]
        )

        body_attribution = (
            "feat: 增加功能\n实现了用户请求的能力。\nGenerated with Codex"
        )
        with patch.object(ai_workflow.openai_client, "create_decision") as create:
            rejected = await check_commit_message(body_attribution)
        create.assert_not_called()
        self.assertFalse(rejected["passed"])
        self.assertIn("禁止包含工具署名", " ".join(rejected["errors"]))

    async def test_issue_pr_single_object_requests_are_valid_and_false_flags_mean_not_requested(
        self,
    ) -> None:
        for requested, kwargs in (
            ("issue", {"issue_number": 4}),
            ("pr", {"pr_number": 5}),
        ):
            with (
                self.subTest(requested=requested),
                patch.object(
                    ai_workflow.validation,
                    "audit_issue_pr_policy",
                    return_value={"passed": True, "errors": []},
                ),
                patch.object(
                    ai_workflow.openai_client,
                    "create_decision",
                    return_value=decision_response(
                        choice_answer(
                            "issue_pr_policy", "compliant", ai_workflow.DECISION_CHOICES
                        )
                    ),
                ) as create,
            ):
                result = await audit_issue_pr_policy("/synthetic/repo", **kwargs)
            self.assertTrue(result["passed"])
            facts = json.loads(create.call_args.args[0][0]["content"])
            self.assertEqual(facts["issue_requested"], requested == "issue")
            self.assertEqual(facts["pull_request_requested"], requested == "pr")
            self.assertFalse(facts["expected_base_checked"])
            self.assertFalse(facts["expected_head_checked"])
            prompt = create.call_args.args[1][0]["instructions"]
            self.assertIn("false 表示未请求该比较", prompt)
            self.assertIn("仅检查 Issue 或仅检查 PR 都是有效审计", prompt)
            self.assertIn("不得推断 CI、labels、仓库身份、可合并性", prompt)
            self.assertIn(
                "仅对这些本地观测应用本问题 instructions 中定义的请求范围内检查",
                prompt,
            )
            self.assertIn(
                "不得增加对未请求对象、字段或外部条件的检查",
                prompt,
            )
            self.assertNotIn("始终要求关闭 Issue 的引用", prompt)

    async def test_invalid_local_check_skips_decisions_and_never_passes(self) -> None:
        local = {
            "passed": False,
            "checks": [
                {"branch_name": "bad", "passed": False, "errors": ["hard error"]}
            ],
        }
        with (
            patch.object(
                ai_workflow.validation, "check_branch_names", return_value=local
            ),
            patch.object(ai_workflow.openai_client, "create_decision") as create,
        ):
            result = await check_branch_names(["bad"])
        create.assert_not_called()
        self.assertFalse(result["passed"])
        self.assertFalse(result["local_passed"])
        self.assertEqual(result["checks"], local["checks"])
        self.assertEqual(result["ai_status"], "skipped_local_failure")

    async def test_local_failure_cannot_be_flipped_by_compliant_decision(self) -> None:
        local = {"passed": False, "subject": "bad", "errors": ["local rule"]}
        with (
            patch.object(
                ai_workflow.validation, "check_commit_message", return_value=local
            ),
            patch.object(
                ai_workflow.openai_client,
                "create_decision",
                return_value=decision_response(
                    choice_answer(
                        "commit_policy", "compliant", ai_workflow.DECISION_CHOICES
                    )
                ),
            ) as create,
        ):
            result = await check_commit_message("bad")
        create.assert_not_called()
        self.assertFalse(result["passed"])
        self.assertEqual(result["errors"], ["local rule"])

    async def test_local_pass_requires_compliant_decision(self) -> None:
        local = {"passed": True, "subject": "docs: 文档", "errors": []}
        fake_response = decision_response(
            choice_answer("commit_policy", "requires_fix", ai_workflow.DECISION_CHOICES)
        )
        with (
            patch.object(
                ai_workflow.validation, "check_commit_message", return_value=local
            ),
            patch.object(
                ai_workflow.openai_client, "create_decision", return_value=fake_response
            ),
        ):
            result = await check_commit_message("docs: 文档")
        self.assertFalse(result["passed"])
        self.assertTrue(result["local_passed"])
        self.assertEqual(result["decision"], "requires_fix")
        self.assertTrue(result["requires_agent_review"])

    async def test_sensitive_commit_input_is_not_echoed_when_api_request_is_blocked(
        self,
    ) -> None:
        for sensitive_value in (API_KEY_A, BASE_URL_A):
            message = f"docs: 文档 {sensitive_value}"
            with (
                self.subTest(
                    kind="key" if sensitive_value == API_KEY_A else "base_url"
                ),
                patch.dict(os.environ, configured_env(), clear=True),
                patch.object(openai_client, "AsyncOpenAI") as factory,
            ):
                result = await check_commit_message(message)
            factory.assert_not_called()
            self.assertFalse(result["passed"])
            self.assertTrue(result["local_passed"])
            self.assertEqual(result["error_code"], "sensitive_input_detected")
            self.assertEqual(result["api_input_review"]["status"], "blocked_local")
            self.assertTrue(result["api_input_review"]["findings"])
            self.assertNotIn(sensitive_value, json.dumps(result))
            self.assertNotIn("subject", result)

    async def test_issue_pr_api_input_omits_repo_path_repo_and_raw_body(self) -> None:
        local = {"passed": True, "repo": "private/example", "errors": []}
        result = decision_response(
            choice_answer("issue_pr_policy", "compliant", ai_workflow.DECISION_CHOICES)
        )
        with (
            patch.object(
                ai_workflow.validation, "audit_issue_pr_policy", return_value=local
            ),
            patch.object(
                ai_workflow.openai_client, "create_decision", return_value=result
            ) as create,
        ):
            wrapped = await audit_issue_pr_policy(
                "/secret/repo", repo="private/example", issue_number=4, pr_number=5
            )
        self.assertTrue(wrapped["passed"])
        payload = json.dumps(create.call_args.args[0], ensure_ascii=False)
        self.assertNotIn("/secret/repo", payload)
        self.assertNotIn("private/example", payload)
        self.assertNotIn("body", payload)

    async def test_decision_answer_shape_choice_and_unique_name_are_strict(
        self,
    ) -> None:
        question = {
            "name": "q",
            "choices": [{"value": value} for value in ai_workflow.DECISION_CHOICES],
        }
        valid = choice_answer("q", "compliant", ai_workflow.DECISION_CHOICES)
        with patch.object(
            ai_workflow.openai_client,
            "create_decision",
            return_value=decision_response(valid),
        ):
            self.assertEqual(
                await ai_workflow._decisions([question], {}), {"q": "compliant"}
            )
        refusal = SimpleNamespace(type="refusal", name="q")
        with patch.object(
            ai_workflow.openai_client,
            "create_decision",
            return_value=decision_response(refusal),
        ):
            self.assertEqual(
                await ai_workflow._decisions([question], {}),
                {"error_code": "invalid_decision_response"},
            )
        bad = choice_answer("q", "not-an-option", ai_workflow.DECISION_CHOICES)
        with patch.object(
            ai_workflow.openai_client,
            "create_decision",
            return_value=decision_response(bad),
        ):
            self.assertEqual(
                await ai_workflow._decisions([question], {}),
                {"error_code": "invalid_decision_response"},
            )
        duplicate = decision_response(valid, valid)
        with patch.object(
            ai_workflow.openai_client, "create_decision", return_value=duplicate
        ):
            self.assertEqual(
                await ai_workflow._decisions([question], {}),
                {"error_code": "invalid_decision_response"},
            )

    async def test_session_actions_enforce_source_access_and_persistence_bounds(
        self,
    ) -> None:
        request = SessionDecisionRequest(
            user_request="检查历史背景",
            has_relevant_sources=True,
            history_accessible=True,
            history_fully_read=True,
            relevant_facts_found=True,
            persistence_allowed=False,
            existing_summary=False,
            new_fact_origin="original_session",
        )
        response = decision_response(
            choice_answer(
                "lookup_action", "read_history", ai_workflow.SESSION_LOOKUP_CHOICES
            ),
            choice_answer(
                "persistence_action",
                "skip_persistence",
                ai_workflow.SESSION_PERSISTENCE_CHOICES,
            ),
        )
        with patch.object(
            ai_workflow.openai_client, "create_decision", return_value=response
        ) as create:
            result = await decide_codex_session_action(request)
        self.assertEqual(result["lookup_action"], "read_history")
        self.assertEqual(result["persistence_action"], "skip_persistence")
        self.assertFalse(result["metadata_verified"])
        self.assertTrue(result["requires_agent_review"])
        self.assertEqual(
            result["rules_hash"], ai_workflow._fingerprint(create.call_args.args[1])
        )
        self.assertEqual(create.call_args.args[0][0]["role"], "user")
        lookup_prompt, persistence_prompt = [
            q["instructions"] for q in create.call_args.args[1]
        ]
        self.assertIn(
            "若 has_relevant_sources=false，选择 query_project", lookup_prompt
        )
        self.assertIn("若 history_accessible=false，选择 blocked", lookup_prompt)
        self.assertIn(
            "使用和追溯已经读过的证据，避免不必要的重复 I/O",
            lookup_prompt,
        )
        self.assertNotIn("existing_summary=true", lookup_prompt)
        self.assertIn(
            "若 persistence_allowed=false，或者 new_fact_origin 为 current_session 或 none",
            persistence_prompt,
        )
        self.assertIn(
            "若 has_relevant_sources=false，选择 skip_persistence", persistence_prompt
        )
        self.assertIn(
            "existing_summary=true 选择 update_summary，existing_summary=false 选择 create_summary",
            persistence_prompt,
        )
        self.assertNotIn("选择 query_project", persistence_prompt)

    async def test_session_model_cannot_create_on_current_facts_or_skip_source_block(
        self,
    ) -> None:
        current = SessionDecisionRequest(
            user_request="归纳当前发现",
            has_relevant_sources=True,
            history_accessible=True,
            history_fully_read=True,
            relevant_facts_found=True,
            persistence_allowed=True,
            existing_summary=False,
            new_fact_origin="current_session",
        )
        bad_response = decision_response(
            choice_answer(
                "lookup_action", "read_history", ai_workflow.SESSION_LOOKUP_CHOICES
            ),
            choice_answer(
                "persistence_action",
                "create_summary",
                ai_workflow.SESSION_PERSISTENCE_CHOICES,
            ),
        )
        with patch.object(
            ai_workflow.openai_client, "create_decision", return_value=bad_response
        ):
            rejected = await decide_codex_session_action(current)
        self.assertFalse(rejected["ok"])
        self.assertEqual(
            rejected["error_code"], "decision_inconsistent_with_session_rules"
        )

        unavailable = SessionDecisionRequest(
            user_request="查历史",
            has_relevant_sources=True,
            history_accessible=False,
            history_fully_read=False,
            relevant_facts_found=None,
            persistence_allowed=True,
            existing_summary=True,
            new_fact_origin="original_session",
        )
        good_blocked = decision_response(
            choice_answer(
                "lookup_action", "blocked", ai_workflow.SESSION_LOOKUP_CHOICES
            ),
            choice_answer(
                "persistence_action",
                "await_source_evidence",
                ai_workflow.SESSION_PERSISTENCE_CHOICES,
            ),
        )
        with patch.object(
            ai_workflow.openai_client, "create_decision", return_value=good_blocked
        ):
            allowed = await decide_codex_session_action(unavailable)
        self.assertEqual(allowed["lookup_action"], "blocked")
        self.assertEqual(allowed["persistence_action"], "await_source_evidence")


if __name__ == "__main__":
    unittest.main()
