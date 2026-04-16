from __future__ import annotations

import os
import unittest

from oz_workflows.helpers import (
    _workflow_run_url,
    append_comment_sections,
    build_comment_body,
    WorkflowProgressComment,
)


class CommentUpdateTest(unittest.TestCase):
    def test_appends_instead_of_replacing(self) -> None:
        metadata = "<!-- meta -->"
        existing = build_comment_body("@alice\n\nOz is working on this issue.\n\nSharing session at: https://example.test/session/123", metadata)
        updated = append_comment_sections(existing, metadata, ["I created a spec PR for this issue: https://example.test/pr/1"])
        self.assertIn("Sharing session at: https://example.test/session/123", updated)
        self.assertIn("I created a spec PR for this issue: https://example.test/pr/1", updated)
        self.assertTrue(updated.endswith(metadata))
    def test_replaces_existing_session_link_when_url_changes(self) -> None:
        metadata = "<!-- meta -->"
        existing = build_comment_body("@alice\n\nOz is working on this issue.\n\nSharing session at: https://example.test/session/123", metadata)
        updated = append_comment_sections(existing, metadata, ["View the Oz conversation: https://example.test/conversation/456"])
        self.assertNotIn("https://example.test/session/123", updated)
        self.assertIn("View the Oz conversation: https://example.test/conversation/456", updated)
        self.assertTrue(updated.endswith(metadata))
    def test_progress_comment_keeps_history_in_single_comment(self) -> None:
        github = FakeGitHubClient()
        progress = WorkflowProgressComment(
            github,
            "acme",
            "widgets",
            42,
            workflow="create-spec-from-issue",
            requester_login="alice",
        )
        progress.start("Oz is starting work on product and tech specs for this issue.")
        progress.record_session_link("https://example.test/session/123")
        progress.complete("I created a spec PR for this issue: https://example.test/pr/1")

        self.assertEqual(len(github.comments), 1)
        body = github.comments[0]["body"]
        self.assertIn("@alice", body)
        self.assertIn("Oz is starting work on product and tech specs for this issue.", body)
        self.assertIn("Sharing session at: https://example.test/session/123", body)
        self.assertIn("I created a spec PR for this issue: https://example.test/pr/1", body)
    def test_progress_comment_replaces_session_link_when_run_moves_to_conversation(self) -> None:
        github = FakeGitHubClient()
        progress = WorkflowProgressComment(
            github,
            "acme",
            "widgets",
            42,
            workflow="create-spec-from-issue",
            requester_login="alice",
        )
        progress.start("Oz is starting work on product and tech specs for this issue.")
        progress.record_session_link("https://example.test/session/123")
        progress.record_session_link("https://example.test/conversation/456")

        self.assertEqual(len(github.comments), 1)
        body = github.comments[0]["body"]
        self.assertNotIn("https://example.test/session/123", body)
        self.assertIn("View the Oz conversation: https://example.test/conversation/456", body)

    def test_separate_runs_create_separate_comments(self) -> None:
        github = FakeGitHubClient()
        run1 = WorkflowProgressComment(
            github,
            "acme",
            "widgets",
            42,
            workflow="triage-new-issues",
            requester_login="alice",
        )
        run1.start("Oz has started triaging this issue.")
        run1.record_session_link("https://example.test/session/run1")

        run2 = WorkflowProgressComment(
            github,
            "acme",
            "widgets",
            42,
            workflow="triage-new-issues",
            requester_login="alice",
        )
        run2.start("Oz has started triaging this issue.")
        run2.record_session_link("https://example.test/session/run2")

        self.assertEqual(len(github.comments), 2)
        body1 = github.comments[0]["body"]
        body2 = github.comments[1]["body"]
        self.assertIn("session/run1", body1)
        self.assertNotIn("session/run2", body1)
        self.assertIn("session/run2", body2)
        self.assertNotIn("session/run1", body2)

    def test_cleanup_deletes_comment_from_any_run(self) -> None:
        github = FakeGitHubClient()
        run1 = WorkflowProgressComment(
            github,
            "acme",
            "widgets",
            42,
            workflow="enforce-pr-issue-state",
            requester_login="alice",
        )
        run1.start("Previous run comment.")
        self.assertEqual(len(github.comments), 1)

        run2 = WorkflowProgressComment(
            github,
            "acme",
            "widgets",
            42,
            workflow="enforce-pr-issue-state",
            requester_login="alice",
        )
        # cleanup without start should still find and delete run1's comment
        run2.cleanup()
        self.assertEqual(len(github.comments), 0)


class ReviewReplyProgressCommentTest(unittest.TestCase):
    def test_creates_reply_in_review_thread_instead_of_issue_comment(self) -> None:
        github = FakeGitHubClient()
        pr = FakePullRequest(trigger_comment_id=100)
        progress = WorkflowProgressComment(
            github,
            "acme",
            "widgets",
            42,
            workflow="respond-to-pr-comment",
            requester_login="alice",
            review_reply_target=(pr, 100),
        )
        progress.start("Oz is working on changes requested in this PR.")

        # No issue-level comments should have been created.
        self.assertEqual(github.comments, [])
        # A reply was posted within the review thread.
        replies = [c for c in pr.review_comments if c.get("in_reply_to_id") == 100]
        self.assertEqual(len(replies), 1)
        self.assertIn("Oz is working on changes", replies[0]["body"])

    def test_keeps_appending_to_same_review_reply(self) -> None:
        github = FakeGitHubClient()
        pr = FakePullRequest(trigger_comment_id=100)
        progress = WorkflowProgressComment(
            github,
            "acme",
            "widgets",
            42,
            workflow="respond-to-pr-comment",
            requester_login="alice",
            review_reply_target=(pr, 100),
        )
        progress.start("Oz is working on changes requested in this PR.")
        progress.record_session_link("https://example.test/session/123")
        progress.complete("I pushed changes to this PR based on the comment.")

        replies = [c for c in pr.review_comments if c.get("in_reply_to_id") == 100]
        self.assertEqual(len(replies), 1)
        body = replies[0]["body"]
        self.assertIn("@alice", body)
        self.assertIn("Oz is working on changes", body)
        self.assertIn("Sharing session at: https://example.test/session/123", body)
        self.assertIn("I pushed changes to this PR based on the comment.", body)

    def test_report_error_updates_reply_within_review_thread(self) -> None:
        github = FakeGitHubClient()
        pr = FakePullRequest(trigger_comment_id=100)
        progress = WorkflowProgressComment(
            github,
            "acme",
            "widgets",
            42,
            workflow="respond-to-pr-comment",
            requester_login="alice",
            review_reply_target=(pr, 100),
        )
        progress.start("Oz is starting to work on this.")
        progress.report_error()

        self.assertEqual(github.comments, [])
        replies = [c for c in pr.review_comments if c.get("in_reply_to_id") == 100]
        self.assertEqual(len(replies), 1)
        self.assertIn("unexpected error", replies[0]["body"])

    def test_does_not_touch_unrelated_review_threads(self) -> None:
        github = FakeGitHubClient()
        pr = FakePullRequest(trigger_comment_id=100)
        # Pre-existing unrelated thread in the same PR.
        pr.review_comments.append(
            {"id": 200, "in_reply_to_id": None, "body": "Other thread root", "user": {"login": "bob"}}
        )
        pr.review_comments.append(
            {"id": 201, "in_reply_to_id": 200, "body": "Other thread reply", "user": {"login": "carol"}}
        )
        progress = WorkflowProgressComment(
            github,
            "acme",
            "widgets",
            42,
            workflow="respond-to-pr-comment",
            requester_login="alice",
            review_reply_target=(pr, 100),
        )
        progress.start("Oz is starting.")
        progress.complete("Oz finished.")

        # Comments in the other thread were not modified or deleted.
        other = [c for c in pr.review_comments if c["id"] in (200, 201)]
        self.assertEqual(len(other), 2)
        self.assertEqual(other[0]["body"], "Other thread root")
        self.assertEqual(other[1]["body"], "Other thread reply")

        # The reply was created in the target thread, not elsewhere.
        replies_in_thread = [c for c in pr.review_comments if c.get("in_reply_to_id") == 100]
        self.assertEqual(len(replies_in_thread), 1)

    def test_separate_runs_create_separate_review_replies(self) -> None:
        github = FakeGitHubClient()
        pr = FakePullRequest(trigger_comment_id=100)
        run1 = WorkflowProgressComment(
            github,
            "acme",
            "widgets",
            42,
            workflow="respond-to-pr-comment",
            requester_login="alice",
            review_reply_target=(pr, 100),
        )
        run1.start("First run start.")
        run2 = WorkflowProgressComment(
            github,
            "acme",
            "widgets",
            42,
            workflow="respond-to-pr-comment",
            requester_login="alice",
            review_reply_target=(pr, 100),
        )
        run2.start("Second run start.")

        replies = [c for c in pr.review_comments if c.get("in_reply_to_id") == 100]
        self.assertEqual(len(replies), 2)
        self.assertIn("First run start.", replies[0]["body"])
        self.assertIn("Second run start.", replies[1]["body"])


class WorkflowRunUrlTest(unittest.TestCase):
    def test_returns_url_when_all_env_vars_set(self) -> None:
        env = {
            "GITHUB_SERVER_URL": "https://github.com",
            "GITHUB_REPOSITORY": "acme/widgets",
            "GITHUB_RUN_ID": "12345",
        }
        for key, value in env.items():
            os.environ[key] = value
        try:
            self.assertEqual(
                _workflow_run_url(),
                "https://github.com/acme/widgets/actions/runs/12345",
            )
        finally:
            for key in env:
                os.environ.pop(key, None)

    def test_returns_empty_when_repository_missing(self) -> None:
        os.environ.pop("GITHUB_REPOSITORY", None)
        os.environ["GITHUB_RUN_ID"] = "12345"
        try:
            self.assertEqual(_workflow_run_url(), "")
        finally:
            os.environ.pop("GITHUB_RUN_ID", None)

    def test_returns_empty_when_run_id_missing(self) -> None:
        os.environ["GITHUB_REPOSITORY"] = "acme/widgets"
        os.environ.pop("GITHUB_RUN_ID", None)
        try:
            self.assertEqual(_workflow_run_url(), "")
        finally:
            os.environ.pop("GITHUB_REPOSITORY", None)

    def test_defaults_server_url_to_github(self) -> None:
        os.environ.pop("GITHUB_SERVER_URL", None)
        os.environ["GITHUB_REPOSITORY"] = "acme/widgets"
        os.environ["GITHUB_RUN_ID"] = "99"
        try:
            self.assertEqual(
                _workflow_run_url(),
                "https://github.com/acme/widgets/actions/runs/99",
            )
        finally:
            os.environ.pop("GITHUB_REPOSITORY", None)
            os.environ.pop("GITHUB_RUN_ID", None)


class ReportErrorTest(unittest.TestCase):
    def test_report_error_updates_comment_with_error_message(self) -> None:
        env = {
            "GITHUB_SERVER_URL": "https://github.com",
            "GITHUB_REPOSITORY": "acme/widgets",
            "GITHUB_RUN_ID": "42",
        }
        for key, value in env.items():
            os.environ[key] = value
        try:
            github = FakeGitHubClient()
            progress = WorkflowProgressComment(
                github, "acme", "widgets", 7,
                workflow="test-workflow",
                requester_login="alice",
            )
            progress.start("Oz is starting to work on this.")
            progress.report_error()

            self.assertEqual(len(github.comments), 1)
            body = github.comments[0]["body"]
            self.assertIn("@alice", body)
            self.assertIn("unexpected error", body)
            self.assertIn("https://github.com/acme/widgets/actions/runs/42", body)
        finally:
            for key in env:
                os.environ.pop(key, None)

    def test_report_error_preserves_session_link(self) -> None:
        env = {
            "GITHUB_SERVER_URL": "https://github.com",
            "GITHUB_REPOSITORY": "acme/widgets",
            "GITHUB_RUN_ID": "42",
        }
        for key, value in env.items():
            os.environ[key] = value
        try:
            github = FakeGitHubClient()
            progress = WorkflowProgressComment(
                github, "acme", "widgets", 7,
                workflow="test-workflow",
                requester_login="alice",
            )
            progress.start("Oz is starting.")
            progress.record_session_link("https://example.test/conversation/abc")
            progress.report_error()

            self.assertEqual(len(github.comments), 1)
            body = github.comments[0]["body"]
            self.assertIn("unexpected error", body)
            self.assertIn("View the Oz conversation: https://example.test/conversation/abc", body)
        finally:
            for key in env:
                os.environ.pop(key, None)

    def test_report_error_without_workflow_run_url(self) -> None:
        os.environ.pop("GITHUB_REPOSITORY", None)
        os.environ.pop("GITHUB_RUN_ID", None)
        os.environ.pop("GITHUB_SERVER_URL", None)
        github = FakeGitHubClient()
        progress = WorkflowProgressComment(
            github, "acme", "widgets", 7,
            workflow="test-workflow",
            requester_login="alice",
        )
        progress.start("Oz is starting.")
        progress.report_error()

        self.assertEqual(len(github.comments), 1)
        body = github.comments[0]["body"]
        self.assertIn("unexpected error", body)
        self.assertNotIn("workflow run", body)

    def test_report_error_creates_comment_when_none_exists(self) -> None:
        env = {
            "GITHUB_SERVER_URL": "https://github.com",
            "GITHUB_REPOSITORY": "acme/widgets",
            "GITHUB_RUN_ID": "42",
        }
        for key, value in env.items():
            os.environ[key] = value
        try:
            github = FakeGitHubClient()
            progress = WorkflowProgressComment(
                github, "acme", "widgets", 7,
                workflow="test-workflow",
                requester_login="alice",
            )
            # No start() call — report_error should still create a comment
            progress.report_error()

            self.assertEqual(len(github.comments), 1)
            body = github.comments[0]["body"]
            self.assertIn("unexpected error", body)
        finally:
            for key in env:
                os.environ.pop(key, None)

    def test_report_error_preserves_metadata_marker(self) -> None:
        env = {
            "GITHUB_SERVER_URL": "https://github.com",
            "GITHUB_REPOSITORY": "acme/widgets",
            "GITHUB_RUN_ID": "42",
        }
        for key, value in env.items():
            os.environ[key] = value
        try:
            github = FakeGitHubClient()
            progress = WorkflowProgressComment(
                github, "acme", "widgets", 7,
                workflow="test-workflow",
                requester_login="alice",
            )
            progress.start("Oz is starting.")
            progress.report_error()

            body = github.comments[0]["body"]
            self.assertIn("<!-- oz-agent-metadata:", body)
        finally:
            for key in env:
                os.environ.pop(key, None)


class FakeGitHubClient:
    def __init__(self) -> None:
        self.comments: list[dict[str, object]] = []

    def list_issue_comments(self, owner: str, repo: str, issue_number: int) -> list[dict[str, object]]:
        return [dict(comment) for comment in self.comments]

    def create_comment(self, owner: str, repo: str, issue_number: int, body: str) -> dict[str, object]:
        comment = {"id": len(self.comments) + 1, "body": body}
        self.comments.append(comment)
        return dict(comment)

    def get_comment(self, owner: str, repo: str, comment_id: int) -> dict[str, object]:
        for comment in self.comments:
            if int(comment["id"]) == comment_id:
                return dict(comment)
        raise AssertionError(f"Missing comment {comment_id}")

    def update_comment(self, owner: str, repo: str, comment_id: int, body: str) -> dict[str, object]:
        for comment in self.comments:
            if int(comment["id"]) == comment_id:
                comment["body"] = body
                return dict(comment)
        raise AssertionError(f"Missing comment {comment_id}")

    def delete_comment(self, owner: str, repo: str, comment_id: int) -> None:
        self.comments = [c for c in self.comments if int(c["id"]) != comment_id]

    def list_issue_events(self, owner: str, repo: str, issue_number: int) -> list[dict[str, object]]:
        return []


class FakeReviewComment:
    """A minimal stand-in for ``github.PullRequestComment.PullRequestComment``."""

    def __init__(self, pr: "FakePullRequest", data: dict[str, object]) -> None:
        self._pr = pr
        self._data = data

    @property
    def id(self) -> int:
        return int(self._data["id"])  # type: ignore[arg-type]

    @property
    def body(self) -> str:
        return str(self._data.get("body") or "")

    @property
    def in_reply_to_id(self) -> object:
        return self._data.get("in_reply_to_id")

    @property
    def user(self) -> object:
        return self._data.get("user")

    def edit(self, body: str) -> None:
        self._data["body"] = body

    def delete(self) -> None:
        self._pr.review_comments = [
            c for c in self._pr.review_comments if int(c["id"]) != self.id  # type: ignore[arg-type]
        ]


class FakePullRequest:
    """A minimal stand-in for ``github.PullRequest.PullRequest`` review-comment APIs."""

    def __init__(self, *, trigger_comment_id: int = 100) -> None:
        self.review_comments: list[dict[str, object]] = [
            {
                "id": trigger_comment_id,
                "in_reply_to_id": None,
                "body": "@oz-agent please take a look at this.",
                "user": {"login": "triggerer"},
            }
        ]

    def _next_id(self) -> int:
        return max(int(c["id"]) for c in self.review_comments) + 1  # type: ignore[arg-type]

    def get_review_comments(self) -> list[FakeReviewComment]:
        return [FakeReviewComment(self, c) for c in self.review_comments]

    def get_review_comment(self, comment_id: int) -> FakeReviewComment:
        for c in self.review_comments:
            if int(c["id"]) == comment_id:  # type: ignore[arg-type]
                return FakeReviewComment(self, c)
        raise AssertionError(f"Missing review comment {comment_id}")

    def create_review_comment_reply(self, comment_id: int, body: str) -> FakeReviewComment:
        new_id = self._next_id()
        data: dict[str, object] = {
            "id": new_id,
            "in_reply_to_id": comment_id,
            "body": body,
            "user": {"login": "oz-agent"},
        }
        self.review_comments.append(data)
        return FakeReviewComment(self, data)


if __name__ == "__main__":
    unittest.main()
