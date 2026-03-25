from __future__ import annotations

import unittest

from oz_workflows.helpers import (
    build_next_steps_section,
    build_plan_preview_section,
    conventional_commit_prefix,
    extract_issue_numbers_from_text,
    org_member_comments_text,
    resolve_progress_requester_login,
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


class ResolveProgressRequesterLoginTest(unittest.TestCase):
    def test_prefers_explicit_requester_login(self) -> None:
        self.assertEqual(
            resolve_progress_requester_login(
                FakeGitHubClient(),
                "acme",
                "widgets",
                12,
                requester_login="@alice",
            ),
            "alice",
        )

    def test_uses_comment_author_when_present(self) -> None:
        self.assertEqual(
            resolve_progress_requester_login(
                FakeGitHubClient(),
                "acme",
                "widgets",
                12,
                event_payload={
                    "sender": {"login": "bob"},
                    "comment": {"user": {"login": "alice"}},
                },
            ),
            "alice",
        )

    def test_falls_back_to_sender_login(self) -> None:
        self.assertEqual(
            resolve_progress_requester_login(
                FakeGitHubClient(),
                "acme",
                "widgets",
                12,
                event_payload={"sender": {"login": "bob"}},
            ),
            "bob",
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

class ConventionalCommitPrefixTest(unittest.TestCase):
    def test_bug_label_returns_fix(self) -> None:
        labels = [{"name": "bug"}, {"name": "ready-to-implement"}]
        self.assertEqual(conventional_commit_prefix(labels), "fix")

    def test_enhancement_label_returns_feat(self) -> None:
        labels = [{"name": "enhancement"}]
        self.assertEqual(conventional_commit_prefix(labels), "feat")

    def test_feature_label_returns_feat(self) -> None:
        labels = [{"name": "feature"}]
        self.assertEqual(conventional_commit_prefix(labels), "feat")

    def test_documentation_label_returns_docs(self) -> None:
        labels = [{"name": "documentation"}]
        self.assertEqual(conventional_commit_prefix(labels), "docs")

    def test_no_matching_label_returns_default(self) -> None:
        labels = [{"name": "ready-to-implement"}, {"name": "area/workflows"}]
        self.assertEqual(conventional_commit_prefix(labels), "feat")

    def test_empty_labels_returns_default(self) -> None:
        self.assertEqual(conventional_commit_prefix([]), "feat")

    def test_custom_default(self) -> None:
        self.assertEqual(conventional_commit_prefix([], default="chore"), "chore")

    def test_string_labels(self) -> None:
        self.assertEqual(conventional_commit_prefix(["bug", "urgent"]), "fix")

    def test_case_insensitive(self) -> None:
        labels = [{"name": "Bug"}]
        self.assertEqual(conventional_commit_prefix(labels), "fix")

    def test_first_match_wins(self) -> None:
        labels = [{"name": "bug"}, {"name": "enhancement"}]
        self.assertEqual(conventional_commit_prefix(labels), "fix")


class FakeGitHubClient:
    def list_issue_events(self, owner: str, repo: str, issue_number: int) -> list[dict[str, object]]:
        return []


if __name__ == "__main__":
    unittest.main()
