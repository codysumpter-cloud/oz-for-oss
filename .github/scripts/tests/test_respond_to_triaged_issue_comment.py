from __future__ import annotations

import unittest

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
        self.assertEqual(rendered, "- @alice [MEMBER] (2026-03-24T00:00:00Z): Earlier context")

    def test_skips_managed_oz_comments(self) -> None:
        rendered = format_visible_issue_comments(
            [
                {
                    "id": 1,
                    "author_association": "NONE",
                    "created_at": "2026-03-24T00:00:00Z",
                    "body": "Visible reporter comment",
                    "user": {"login": "alice"},
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
        self.assertEqual(rendered, "- @alice [NONE] (2026-03-24T00:00:00Z): Visible reporter comment")


class ExtractAnalysisCommentTest(unittest.TestCase):
    def test_returns_stripped_comment(self) -> None:
        self.assertEqual(
            extract_analysis_comment({"analysis_comment": "  Thanks for the ping.  "}),
            "Thanks for the ping.",
        )

    def test_returns_empty_string_when_missing(self) -> None:
        self.assertEqual(extract_analysis_comment({}), "")


if __name__ == "__main__":
    unittest.main()
