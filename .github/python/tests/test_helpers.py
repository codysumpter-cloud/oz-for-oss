from __future__ import annotations

import unittest

from oz_workflows.helpers import (
    build_next_steps_section,
    build_plan_preview_section,
    extract_issue_numbers_from_text,
    org_member_comments_text,
    triggering_comment_prompt_text,
)


class ExtractIssueNumbersTest(unittest.TestCase):
    def test_extracts_hash_and_url_references(self) -> None:
        text = "Fixes #12 and refs https://github.com/acme/widgets/issues/34"
        self.assertEqual(extract_issue_numbers_from_text("acme", "widgets", text), [12, 34])


class BuildPlanPreviewSectionTest(unittest.TestCase):
    def test_builds_markdown_link_for_plan_branch(self) -> None:
        self.assertEqual(
            build_plan_preview_section("warpdotdev", "oz-oss-testbed", "oz-agent/plan-issue-20", 20),
            "Preview generated plan: [plans/issue-20.md](https://github.com/warpdotdev/oz-oss-testbed/blob/oz-agent/plan-issue-20/plans/issue-20.md)",
        )


class BuildNextStepsSectionTest(unittest.TestCase):
    def test_builds_bulleted_next_steps(self) -> None:
        self.assertEqual(
            build_next_steps_section(
                [
                    "Review the plan PR.",
                    "Request any needed updates.",
                ]
            ),
            "Next steps:\n- Review the plan PR.\n- Request any needed updates.",
        )


class TriggeringCommentPromptTextTest(unittest.TestCase):
    def test_formats_comment_body_for_prompt(self) -> None:
        self.assertEqual(
            triggering_comment_prompt_text(
                {
                    "sender": {"login": "alice"},
                    "comment": {
                        "body": "@oz-agent please focus on rollout safety",
                        "user": {"login": "alice"},
                    },
                }
            ),
            "@alice commented:\n@oz-agent please focus on rollout safety",
        )


class OrgMemberCommentsTextTest(unittest.TestCase):
    def test_can_exclude_triggering_comment(self) -> None:
        self.assertEqual(
            org_member_comments_text(
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
                        "body": "@oz-agent please handle this",
                        "user": {"login": "alice"},
                    },
                ],
                exclude_comment_id=2,
            ),
            "- alice (2026-03-24T00:00:00Z): Earlier context",
        )


if __name__ == "__main__":
    unittest.main()
