from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from respond_to_triaged_issue_comment import (
    extract_analysis_comment,
    format_visible_issue_comments,
)


class FormatVisibleIssueCommentsTest(unittest.TestCase):
    def test_can_exclude_triggering_comment(self) -> None:
        rendered = format_visible_issue_comments(
            [
                {
                    "id": 1,
                    "author_association": "MEMBER",
                    "created_at": "2026-03-24T00:00:00Z",
                    "body": "Earlier context",
                    "user": {"login": "alice"},
                },
                {
                    "id": 2,
                    "author_association": "MEMBER",
                    "created_at": "2026-03-24T01:00:00Z",
                    "body": "@oz-agent what do you think?",
                    "user": {"login": "alice"},
                },
            ],
            exclude_comment_id=2,
        )
        self.assertEqual(rendered, "- alice (2026-03-24T00:00:00Z): Earlier context")

    def test_excludes_non_org_member_comments(self) -> None:
        rendered = format_visible_issue_comments(
            [
                {
                    "id": 1,
                    "author_association": "NONE",
                    "created_at": "2026-03-24T00:00:00Z",
                    "body": "Reporter comment that should be excluded",
                    "user": {"login": "external-user"},
                },
                {
                    "id": 2,
                    "author_association": "NONE",
                    "created_at": "2026-03-24T01:00:00Z",
                    "body": "Managed status\n\n<!-- oz-agent-metadata: {\"type\":\"issue-status\"} -->",
                    "user": {"login": "oz-agent"},
                },
            ]
        )
        self.assertEqual(rendered, "- None")

    def test_includes_org_member_comments(self) -> None:
        rendered = format_visible_issue_comments(
            [
                {
                    "id": 1,
                    "author_association": "NONE",
                    "created_at": "2026-03-24T00:00:00Z",
                    "body": "Reporter comment that should be excluded",
                    "user": {"login": "external-user"},
                },
                {
                    "id": 2,
                    "author_association": "MEMBER",
                    "created_at": "2026-03-24T01:00:00Z",
                    "body": "Org member comment",
                    "user": {"login": "maintainer"},
                },
            ]
        )
        self.assertEqual(rendered, "- maintainer (2026-03-24T01:00:00Z): Org member comment")


class ExtractAnalysisCommentTest(unittest.TestCase):
    def test_returns_stripped_comment(self) -> None:
        self.assertEqual(
            extract_analysis_comment({"analysis_comment": "  Thanks for the ping.  "}),
            "Thanks for the ping.",
        )

    def test_returns_empty_string_when_missing(self) -> None:
        self.assertEqual(extract_analysis_comment({}), "")

class MainTrustGateTest(unittest.TestCase):
    def test_untrusted_commenter_returns_before_repo_lookup(self) -> None:
        from respond_to_triaged_issue_comment import main

        event = {
            "comment": {
                "id": 99,
                "user": {"login": "outsider", "type": "User"},
                "author_association": "NONE",
            },
            "issue": {"number": 7},
        }
        client = MagicMock()
        client.close = MagicMock()

        with (
            patch(
                "respond_to_triaged_issue_comment.repo_parts",
                return_value=("acme", "widgets"),
            ),
            patch("respond_to_triaged_issue_comment.load_event", return_value=event),
            patch("respond_to_triaged_issue_comment.require_env", return_value="token"),
            patch("respond_to_triaged_issue_comment.Auth.Token"),
            patch("respond_to_triaged_issue_comment.Github", return_value=client),
            patch(
                "respond_to_triaged_issue_comment.is_trusted_commenter",
                return_value=False,
            ) as trust_mock,
            patch("respond_to_triaged_issue_comment.notice") as notice_mock,
        ):
            main()

        trust_mock.assert_called_once_with(client, event, org="acme")
        notice_mock.assert_called_once()
        self.assertIn("outsider", notice_mock.call_args.args[0])
        self.assertIn("NONE", notice_mock.call_args.args[0])
        client.get_repo.assert_not_called()


class WorkflowTrustGateRegressionTest(unittest.TestCase):
    def test_reusable_triaged_issue_workflow_contains_check_trust_gate(self) -> None:
        content = Path(
            ".github/workflows/respond-to-triaged-issue-comment.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("check_trust:", content)
        self.assertIn("needs: check_trust", content)
        self.assertIn("needs.check_trust.outputs.trusted == 'true'", content)
        self.assertIn('gh api --silent "/orgs/${ORG}/members/${ACTOR}"', content)

    def test_local_adapter_delegates_gating_to_reusable_workflow(self) -> None:
        content = Path(
            ".github/workflows/respond-to-triaged-issue-comment-local.yml"
        ).read_text(encoding="utf-8")
        self.assertNotIn("contains(github.event.comment.body, '@oz-agent')", content)
        self.assertIn(
            "Mention, bot, event-type, and trust gates all live in the reusable",
            content,
        )


if __name__ == "__main__":
    unittest.main()
