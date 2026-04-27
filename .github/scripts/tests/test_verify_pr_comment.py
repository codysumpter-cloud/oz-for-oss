from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from verify_pr_comment import build_verification_prompt


class BuildVerificationPromptTest(unittest.TestCase):
    def test_includes_discovered_skills_and_report_contract(self) -> None:
        prompt = build_verification_prompt(
            owner="acme",
            repo="widgets",
            pr_number=42,
            base_branch="main",
            head_branch="feature/verify",
            trigger_comment_id=1001,
            requester="alice",
            verification_skills_text="- `verify-ui` at `.agents/skills/verify-ui/SKILL.md`",
        )
        self.assertIn("Run pull request verification for pull request #42", prompt)
        self.assertNotIn("feat: add verification", prompt)
        self.assertNotIn("- Title:", prompt)
        self.assertIn("`verify-ui` at `.agents/skills/verify-ui/SKILL.md`", prompt)
        self.assertIn('"overall_status": "passed" | "failed" | "mixed"', prompt)
        self.assertIn("verification_report.json", prompt)
        self.assertIn("Do not commit, push, edit the pull request", prompt)


class MainTrustGateTest(unittest.TestCase):
    def test_untrusted_commenter_returns_before_repo_lookup(self) -> None:
        from verify_pr_comment import main

        event = {
            "comment": {
                "id": 99,
                "body": "/oz-verify",
                "user": {"login": "outsider", "type": "User"},
                "author_association": "NONE",
            },
            "issue": {"number": 7, "pull_request": {"url": "https://example.test/pr/7"}},
        }
        client = MagicMock()
        client.close = MagicMock()

        with (
            patch("verify_pr_comment.repo_parts", return_value=("acme", "widgets")),
            patch("verify_pr_comment.load_event", return_value=event),
            patch("verify_pr_comment.require_env", return_value="token"),
            patch("verify_pr_comment.Auth.Token"),
            patch("verify_pr_comment.Github", return_value=client),
            patch(
                "verify_pr_comment.is_trusted_commenter",
                return_value=False,
            ) as trust_mock,
            patch("verify_pr_comment.notice") as notice_mock,
        ):
            main()

        trust_mock.assert_called_once_with(client, event, org="acme")
        notice_mock.assert_called_once()
        self.assertIn("outsider", notice_mock.call_args.args[0])
        self.assertIn("NONE", notice_mock.call_args.args[0])
        client.get_repo.assert_not_called()


class WorkflowTrustGateRegressionTest(unittest.TestCase):
    def test_reusable_verify_workflow_contains_check_trust_gate(self) -> None:
        content = Path(".github/workflows/verify-pr-comment.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("check_trust:", content)
        self.assertIn("needs: check_trust", content)
        self.assertIn("needs.check_trust.outputs.trusted == 'true'", content)
        self.assertIn("contains(github.event.comment.body, '/oz-verify')", content)
        self.assertIn('gh api --silent "/orgs/${ORG}/members/${ACTOR}"', content)

    def test_local_adapter_delegates_gating_to_reusable_workflow(self) -> None:
        content = Path(".github/workflows/verify-pr-comment-local.yml").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("contains(github.event.comment.body, '/oz-verify')", content)
        self.assertIn("delegates through ``workflow_call``", content)


if __name__ == "__main__":
    unittest.main()
