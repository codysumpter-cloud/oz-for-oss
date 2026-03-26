from __future__ import annotations

import unittest

from oz_workflows.helpers import (
    _summarize_commits,
    all_review_comments_text,
    build_next_steps_section,
    build_plan_preview_section,
    build_pr_body,
    coauthor_prompt_lines,
    conventional_commit_prefix,
    extract_issue_numbers_from_text,
    org_member_comments_text,
    resolve_coauthor_line,
    resolve_progress_requester_login,
    review_thread_comments_text,
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


class ReviewThreadCommentsTextTest(unittest.TestCase):
    def test_extracts_thread_for_trigger_comment(self) -> None:
        comments = [
            {"id": 10, "author_association": "MEMBER", "user": {"login": "alice"}, "created_at": "2026-01-01T00:00:00Z", "body": "Root comment", "path": "src/main.py"},
            {"id": 11, "in_reply_to_id": 10, "author_association": "MEMBER", "user": {"login": "bob"}, "created_at": "2026-01-01T01:00:00Z", "body": "Reply in thread", "path": "src/main.py"},
            {"id": 20, "author_association": "MEMBER", "user": {"login": "carol"}, "created_at": "2026-01-01T02:00:00Z", "body": "Different thread", "path": "src/other.py"},
        ]
        result = review_thread_comments_text(comments, trigger_comment_id=11)
        self.assertIn("alice", result)
        self.assertIn("bob", result)
        self.assertNotIn("carol", result)

    def test_filters_non_org_members(self) -> None:
        comments = [
            {"id": 10, "author_association": "MEMBER", "user": {"login": "alice"}, "created_at": "2026-01-01T00:00:00Z", "body": "Root", "path": "f.py"},
            {"id": 11, "in_reply_to_id": 10, "author_association": "NONE", "user": {"login": "outsider"}, "created_at": "2026-01-01T01:00:00Z", "body": "External reply", "path": "f.py"},
        ]
        result = review_thread_comments_text(comments, trigger_comment_id=10)
        self.assertIn("alice", result)
        self.assertNotIn("outsider", result)

    def test_returns_empty_when_no_org_members(self) -> None:
        comments = [
            {"id": 10, "author_association": "NONE", "user": {"login": "outsider"}, "created_at": "2026-01-01T00:00:00Z", "body": "Comment", "path": "f.py"},
        ]
        self.assertEqual(review_thread_comments_text(comments, trigger_comment_id=10), "")


class AllReviewCommentsTextTest(unittest.TestCase):
    def test_groups_by_file_path(self) -> None:
        comments = [
            {"id": 1, "author_association": "MEMBER", "user": {"login": "alice"}, "created_at": "2026-01-01T00:00:00Z", "body": "Fix here", "path": "src/a.py"},
            {"id": 2, "author_association": "MEMBER", "user": {"login": "bob"}, "created_at": "2026-01-01T01:00:00Z", "body": "And here", "path": "src/b.py"},
        ]
        result = all_review_comments_text(comments)
        self.assertIn("File: src/a.py", result)
        self.assertIn("File: src/b.py", result)
        self.assertIn("alice", result)
        self.assertIn("bob", result)

    def test_filters_non_org_members(self) -> None:
        comments = [
            {"id": 1, "author_association": "MEMBER", "user": {"login": "alice"}, "created_at": "2026-01-01T00:00:00Z", "body": "Good", "path": "f.py"},
            {"id": 2, "author_association": "NONE", "user": {"login": "outsider"}, "created_at": "2026-01-01T01:00:00Z", "body": "Bad", "path": "f.py"},
        ]
        result = all_review_comments_text(comments)
        self.assertIn("alice", result)
        self.assertNotIn("outsider", result)

    def test_returns_empty_when_no_org_members(self) -> None:
        comments = [
            {"id": 1, "author_association": "CONTRIBUTOR", "user": {"login": "ext"}, "created_at": "2026-01-01T00:00:00Z", "body": "Hi", "path": "f.py"},
        ]
        self.assertEqual(all_review_comments_text(comments), "")


class SummarizeCommitsTest(unittest.TestCase):
    def test_extracts_first_line_of_each_commit(self) -> None:
        commits = [
            {"commit": {"message": "Add feature X\n\nMore details here"}},
            {"commit": {"message": "Fix typo in docs"}},
        ]
        self.assertEqual(
            _summarize_commits(commits),
            "- Add feature X\n- Fix typo in docs",
        )

    def test_skips_merge_commits(self) -> None:
        commits = [
            {"commit": {"message": "Merge branch 'main' into feature"}},
            {"commit": {"message": "Real change"}},
        ]
        self.assertEqual(_summarize_commits(commits), "- Real change")

    def test_skips_empty_messages(self) -> None:
        commits = [
            {"commit": {"message": ""}},
            {"commit": {"message": "Valid commit"}},
        ]
        self.assertEqual(_summarize_commits(commits), "- Valid commit")

    def test_returns_empty_string_for_no_commits(self) -> None:
        self.assertEqual(_summarize_commits([]), "")


class BuildPrBodyTest(unittest.TestCase):
    def test_implementation_pr_includes_closing_keyword(self) -> None:
        github = FakeGitHubClientWithCompare([
            {"commit": {"message": "Implement the thing"}},
        ])
        body = build_pr_body(
            github, "acme", "widgets",
            issue_number=42,
            head="feature-branch",
            base="main",
            closing_keyword="Closes",
        )
        self.assertIn("Closes #42", body)
        self.assertIn("- Implement the thing", body)

    def test_plan_pr_omits_closing_keyword(self) -> None:
        github = FakeGitHubClientWithCompare([
            {"commit": {"message": "Add plan"}},
        ])
        body = build_pr_body(
            github, "acme", "widgets",
            issue_number=42,
            head="plan-branch",
            base="main",
            closing_keyword="",
        )
        self.assertNotIn("Closes", body)
        self.assertIn("Related issue: #42", body)
        self.assertIn("- Add plan", body)

    def test_includes_session_link(self) -> None:
        github = FakeGitHubClientWithCompare([])
        body = build_pr_body(
            github, "acme", "widgets",
            issue_number=7,
            head="branch",
            base="main",
            session_link="https://example.com/session",
            closing_keyword="Fixes",
        )
        self.assertIn("Session: https://example.com/session", body)

    def test_no_changes_section_when_no_commits(self) -> None:
        github = FakeGitHubClientWithCompare([])
        body = build_pr_body(
            github, "acme", "widgets",
            issue_number=7,
            head="branch",
            base="main",
            closing_keyword="Closes",
        )
        self.assertNotIn("## Changes", body)
        self.assertIn("Closes #7", body)


class FakeGitHubClient:
    def __init__(self, *, users: dict[str, dict[str, object]] | None = None) -> None:
        self._users = users or {}

    def list_issue_events(self, owner: str, repo: str, issue_number: int) -> list[dict[str, object]]:
        return []

    def get_user(self, username: str) -> dict[str, object] | None:
        return self._users.get(username)


class ResolveCoauthorLineTest(unittest.TestCase):
    def test_resolves_from_comment_author_with_name(self) -> None:
        github = FakeGitHubClient(users={"alice": {"name": "Alice Smith", "login": "alice"}})
        event = {"comment": {"user": {"login": "alice"}}, "sender": {"login": "bot"}}
        self.assertEqual(
            resolve_coauthor_line(github, event),
            "Co-Authored-By: Alice Smith <alice@users.noreply.github.com>",
        )

    def test_resolves_from_sender_when_no_comment(self) -> None:
        github = FakeGitHubClient(users={"bob": {"name": "Bob Jones", "login": "bob"}})
        event = {"sender": {"login": "bob"}}
        self.assertEqual(
            resolve_coauthor_line(github, event),
            "Co-Authored-By: Bob Jones <bob@users.noreply.github.com>",
        )

    def test_falls_back_to_login_when_name_is_none(self) -> None:
        github = FakeGitHubClient(users={"alice": {"name": None, "login": "alice"}})
        event = {"comment": {"user": {"login": "alice"}}}
        self.assertEqual(
            resolve_coauthor_line(github, event),
            "Co-Authored-By: alice <alice@users.noreply.github.com>",
        )

    def test_falls_back_to_login_when_get_user_returns_none(self) -> None:
        github = FakeGitHubClient(users={})
        event = {"sender": {"login": "unknown-user"}}
        self.assertEqual(
            resolve_coauthor_line(github, event),
            "Co-Authored-By: unknown-user <unknown-user@users.noreply.github.com>",
        )

    def test_returns_empty_when_no_login_available(self) -> None:
        github = FakeGitHubClient()
        event: dict[str, object] = {}
        self.assertEqual(resolve_coauthor_line(github, event), "")

    def test_handles_get_user_exception(self) -> None:
        class ErrorClient(FakeGitHubClient):
            def get_user(self, username: str) -> dict[str, object] | None:
                raise RuntimeError("API error")

        github = ErrorClient()
        event = {"sender": {"login": "alice"}}
        self.assertEqual(
            resolve_coauthor_line(github, event),
            "Co-Authored-By: alice <alice@users.noreply.github.com>",
        )


class CoauthorPromptLinesTest(unittest.TestCase):
    def test_returns_include_directive_when_line_provided(self) -> None:
        result = coauthor_prompt_lines("Co-Authored-By: Alice <alice@users.noreply.github.com>")
        self.assertIn("Co-Authored-By: Alice <alice@users.noreply.github.com>", result)
        self.assertIn("Do not attempt to resolve the co-author identity yourself", result)

    def test_returns_omit_directive_when_empty(self) -> None:
        result = coauthor_prompt_lines("")
        self.assertIn("Do not include any Co-Authored-By lines", result)


class FakeGitHubClientWithCompare:
    def __init__(self, commits: list[dict[str, object]]) -> None:
        self._commits = commits

    def compare_commits(self, owner: str, repo: str, base: str, head: str) -> dict[str, object]:
        return {"commits": self._commits}


if __name__ == "__main__":
    unittest.main()
