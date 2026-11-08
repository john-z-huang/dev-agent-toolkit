from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from dev_workflow_standards_tools.infrastructure import api_input_policy as policy


class ApiInputPolicyTests(unittest.TestCase):
    def inspect(self, content: str, purpose: str = "Review an example") -> dict:
        return policy.inspect_api_input(purpose, content)

    def test_safe_relative_paths_public_urls_api_routes_and_hashes_pass(self):
        safe = (
            "relative: src/module.py; API route /v1/chat/completions; "
            "public URL https://api.example.invalid/v1; "
            "environment variable OPENAI_API_KEY; hash " + "a" * 64
        )
        result = self.inspect(safe)
        self.assertTrue(result["passed"])
        self.assertEqual(result["findings"], [])
        self.assertIsNone(result["error_code"])

    def test_credentials_private_keys_and_authenticated_urls_are_blocked(self):
        cases = (
            ("token sk-proj-" + "A1b2C3d4E5f6G7h8J9k0", "credential"),
            ("Authorization: Bearer " + "AbC123def456GhI789", "credential"),
            ("Authorization: Basic " + "dXNlcjpzZWNyZXQ=", "credential"),
            ("jwt eyJabcdefghijk.abcdefghijklm.abcdefghijklm", "credential"),
            ("OPENAI_API_KEY=" + "A1b2C3d4E5f6G7h8J9k0", "credential"),
            ("api_key=your_live_credential_123456789", "credential"),
            ('{"password":"private_synthetic_value_123"}', "credential"),
            ("password=hunter2", "credential"),
            ('{"password":"abc123"}', "credential"),
            ("token=abc123", "credential"),
            ('{"token":"abc123"}', "credential"),
            ("Cookie: sessionid=" + "AbC123def456GhI789", "credential"),
            ("-----BEGIN PRIVATE KEY-----", "credential"),
            ("https://account:secret-value@example.invalid/path", "credential"),
            ("https://private_synthetic_value_123@example.invalid/path", "credential"),
            (
                "https://api.example.invalid/?token=private_synthetic_value_123",
                "credential",
            ),
        )
        for value, category in cases:
            with self.subTest(rule=value.split(":", 1)[0]):
                result = self.inspect(value)
                self.assertFalse(result["passed"])
                self.assertEqual(result["findings"][0]["category"], category)
                self.assertNotIn(value, str(result))

    def test_file_directory_and_url_paths_do_not_create_local_findings(self):
        for path in (
            "/Users/alice/project/secrets.txt",
            "/home/alice/project/config.toml",
            "C:\\Users\\alice\\project\\secrets.txt",
            "\\\\server\\share\\private\\file.txt",
            "file:///Users/alice/project/file.txt",
            "https://api.example.invalid/?path=/Users/alice/project/file.txt",
        ):
            with self.subTest(path_kind=path[:12]):
                result = self.inspect("See " + path)
                self.assertTrue(result["passed"])
                self.assertEqual(result["findings"], [])
                both_fields = policy.inspect_api_input(
                    "Purpose refers to " + path, "Content refers to " + path
                )
                self.assertTrue(both_fields["passed"])
                self.assertEqual(both_fields["findings"], [])

    def test_nested_and_malformed_json_paths_do_not_create_findings(self):
        path = r"\\server\share\private\file.txt"
        values = (
            json.dumps({"facts": {"path": r"C:\Users\alice\private.txt"}}),
            json.dumps(json.dumps({"facts": {"path": path}})),
            json.dumps({path: "ordinary value", "path": "/Users/alice/file.txt"}),
            json.dumps({"path": path})[:-1] + ',"path":"safe"}',
            '{"path":"/Users/alice/file.txt"',
            "[" * 20 + json.dumps(path) + "]" * 20,
        )
        for value in values:
            with self.subTest(value=value[:40]):
                result = self.inspect(value)
                self.assertTrue(result["passed"])
                self.assertEqual(result["findings"], [])

    def test_credential_still_blocks_when_same_content_contains_path(self):
        result = self.inspect(
            r"See C:\Users\alice\project\file.txt; token=synthetic-sensitive-token-value"
        )
        self.assertFalse(result["passed"])
        self.assertEqual(result["findings"][0]["category"], "credential")
        self.assertTrue(
            all(item["category"] == "credential" for item in result["findings"])
        )

    def test_explicit_encoded_payload_is_bounded_and_rejected(self):
        result = self.inspect("base64: " + "YWJjZA==" * 8)
        self.assertFalse(result["passed"])
        self.assertEqual(result["findings"][0]["category"], "opaque_or_encoded")
        self.assertEqual(result["findings"][0]["rule_id"], "opaque.encoded_payload")

    def test_current_configuration_values_are_blocked_without_being_returned(self):
        configured_key = "synthetic-config-secret-that-never-leaves-test"
        configured_url = "https://synthetic-endpoint.invalid/v1"
        with patch.dict(
            os.environ,
            {"OPENAI_API_KEY": configured_key, "OPENAI_BASE_URL": configured_url},
            clear=True,
        ):
            for value in (configured_key, configured_url):
                result = self.inspect("prefix " + value + " suffix")
                self.assertFalse(result["passed"])
                self.assertEqual(
                    result["findings"][0]["rule_id"], "credential.exact_configuration"
                )
                self.assertNotIn(value, str(result))

    def test_size_and_invalid_inputs_fail_closed_without_echoing(self):
        too_large = self.inspect("x" * (policy.MAX_FIELD_BYTES + 1))
        self.assertFalse(too_large["passed"])
        self.assertEqual(too_large["error_code"], "request_too_large")
        invalid = policy.inspect_api_input(" ", "synthetic-secret")
        self.assertFalse(invalid["passed"])
        self.assertEqual(invalid["error_code"], "invalid_input")
        self.assertNotIn("synthetic-secret", str(invalid))

    def test_environment_variable_names_are_not_mistaken_for_values(self):
        for value in (
            "api_key=OPENAI_API_KEY",
            '{"api_key":"OPENAI_API_KEY"}',
            "token=OPENAI_API_KEY",
            "token=example",
            "OPENAI_BASE_URL",
        ):
            with self.subTest(value=value):
                self.assertTrue(self.inspect(value)["passed"])
        escaped = json.dumps({"input": json.dumps({"api_key": "OPENAI_API_KEY"})})
        self.assertTrue(self.inspect(escaped)["passed"])

    def test_json_escaped_sensitive_assignments_are_still_detected(self):
        serialized = json.dumps(
            {"input": json.dumps({"password": "private_synthetic_value_123"})}
        )
        result = self.inspect(serialized)
        self.assertFalse(result["passed"])
        self.assertEqual(result["findings"][0]["rule_id"], "credential.assignment")

    def test_fields_report_only_safe_locations_and_rule_identifiers(self):
        secret = "AbC123def456GhI789"
        result = policy.inspect_api_input("Review", f"Before token={secret}")
        finding = result["findings"][0]
        self.assertEqual(finding["field"], "content")
        self.assertEqual(finding["start"], len("Before "))
        self.assertEqual(finding["rule_id"], "credential.assignment")
        self.assertEqual(finding["category"], "credential")
        self.assertNotIn(secret, str(finding))

    def test_unpaired_surrogate_fails_safely(self):
        result = self.inspect("bad \ud800 value")
        self.assertFalse(result["passed"])
        self.assertEqual(result["error_code"], "invalid_input")
        self.assertEqual(result["findings"][0]["rule_id"], "input.invalid_unicode")


if __name__ == "__main__":
    unittest.main()
