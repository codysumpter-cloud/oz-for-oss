from __future__ import annotations

import json
import os
import unittest

from oz_workflows.helpers import (
    _strip_workflow_metadata,
    _workflow_metadata_prefix,
    _workflow_run_url,
    append_comment_sections,
    build_comment_body,
    comment_metadata,
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

    def test_dedupes_duplicate_replies_from_retried_post(self) -> None:
        # Simulate PyGitHub's default retry policy retrying POST on a 5xx
        # response where GitHub actually processed each attempt and created
        # multiple duplicate review-comment replies server-side.
        github = FakeGitHubClient()
        pr = FakePullRequest(trigger_comment_id=100, duplicate_reply_count=3)
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

        replies = [c for c in pr.review_comments if c.get("in_reply_to_id") == 100]
        self.assertEqual(len(replies), 1)
        self.assertIn("Oz is working on changes", replies[0]["body"])

    def test_session_link_update_survives_transient_patch_failure(self) -> None:
        # The poll loop calls record_session_link every tick. If a single
        # PATCH fails with a transient error the run must continue so the
        # next poll has a chance to record the link.
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
        progress.start("Oz is working.")
        pr.fail_next_edit = True
        progress.record_session_link("https://example.test/session/abc")
        # The first attempt failed, so the session link should not be
        # recorded yet, but the workflow is expected to continue running.
        replies = [c for c in pr.review_comments if c.get("in_reply_to_id") == 100]
        self.assertNotIn("https://example.test/session/abc", replies[0]["body"])
        # The next poll retries with the same link and succeeds.
        progress.record_session_link("https://example.test/session/abc")
        replies = [c for c in pr.review_comments if c.get("in_reply_to_id") == 100]
        self.assertIn("Sharing session at: https://example.test/session/abc", replies[0]["body"])

    def test_session_link_skips_patch_when_link_unchanged(self) -> None:
        # Poll loops call record_session_link on every tick with the same
        # link. Subsequent identical calls should be a no-op so the bot
        # doesn't spam PATCH requests at GitHub.
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
        progress.start("Oz is working.")
        progress.record_session_link("https://example.test/session/abc")
        edits_after_first = pr.edit_count
        progress.record_session_link("https://example.test/session/abc")
        self.assertEqual(pr.edit_count, edits_after_first)


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
        if self._pr.fail_next_edit:
            self._pr.fail_next_edit = False
            raise RuntimeError("simulated transient PATCH failure")
        self._pr.edit_count += 1
        self._data["body"] = body

    def delete(self) -> None:
        self._pr.review_comments = [
            c for c in self._pr.review_comments if int(c["id"]) != self.id  # type: ignore[arg-type]
        ]


class FakePullRequest:
    """A minimal stand-in for ``github.PullRequest.PullRequest`` review-comment APIs."""

    def __init__(
        self,
        *,
        trigger_comment_id: int = 100,
        duplicate_reply_count: int = 1,
    ) -> None:
        self.review_comments: list[dict[str, object]] = [
            {
                "id": trigger_comment_id,
                "in_reply_to_id": None,
                "body": "@oz-agent please take a look at this.",
                "user": {"login": "triggerer"},
            }
        ]
        # When >1, ``create_review_comment_reply`` simulates PyGitHub's
        # retry-on-5xx behavior by inserting extra duplicate replies that
        # the server created but never returned successfully to the client.
        self.duplicate_reply_count = max(1, duplicate_reply_count)
        # When True, the next ``edit`` call raises to simulate a transient
        # GitHub API failure on PATCH.
        self.fail_next_edit = False
        # Tracks successful ``edit`` calls for tests that assert on PATCH
        # frequency.
        self.edit_count = 0

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
        last: FakeReviewComment | None = None
        for _ in range(self.duplicate_reply_count):
            new_id = self._next_id()
            data: dict[str, object] = {
                "id": new_id,
                "in_reply_to_id": comment_id,
                "body": body,
                "user": {"login": "oz-agent"},
            }
            self.review_comments.append(data)
            last = FakeReviewComment(self, data)
        assert last is not None
        return last


class CommentMetadataTest(unittest.TestCase):
    def _parse_metadata(self, marker: str) -> dict[str, object]:
        prefix = "<!-- oz-agent-metadata: "
        suffix = " -->"
        self.assertTrue(marker.startswith(prefix))
        self.assertTrue(marker.endswith(suffix))
        return json.loads(marker[len(prefix):-len(suffix)])

    def test_includes_only_type_workflow_issue_when_no_run_ids(self) -> None:
        marker = comment_metadata("triage-new-issues", 42)
        parsed = self._parse_metadata(marker)
        self.assertEqual(
            parsed,
            {"type": "issue-status", "workflow": "triage-new-issues", "issue": 42},
        )

    def test_includes_run_id_when_provided(self) -> None:
        marker = comment_metadata("triage-new-issues", 42, run_id="abc123")
        parsed = self._parse_metadata(marker)
        self.assertEqual(parsed["run_id"], "abc123")
        self.assertNotIn("oz_run_id", parsed)
        self.assertNotIn("github_run_id", parsed)

    def test_includes_oz_run_id_when_provided(self) -> None:
        marker = comment_metadata(
            "triage-new-issues",
            42,
            run_id="abc",
            oz_run_id="oz-run-xyz",
            github_run_id="99",
        )
        parsed = self._parse_metadata(marker)
        self.assertEqual(parsed["oz_run_id"], "oz-run-xyz")
        self.assertEqual(parsed["github_run_id"], "99")
        self.assertEqual(parsed["run_id"], "abc")

    def test_omits_empty_run_ids(self) -> None:
        marker = comment_metadata(
            "triage-new-issues",
            42,
            run_id="",
            oz_run_id="",
            github_run_id="",
        )
        parsed = self._parse_metadata(marker)
        self.assertNotIn("run_id", parsed)
        self.assertNotIn("oz_run_id", parsed)
        self.assertNotIn("github_run_id", parsed)

    def test_marker_starts_with_workflow_prefix(self) -> None:
        marker = comment_metadata(
            "triage-new-issues",
            42,
            run_id="abc",
            oz_run_id="oz",
            github_run_id="99",
        )
        prefix = _workflow_metadata_prefix("triage-new-issues", 42)
        self.assertTrue(marker.startswith(prefix))


class StripWorkflowMetadataTest(unittest.TestCase):
    def test_strips_marker_matching_prefix(self) -> None:
        prefix = _workflow_metadata_prefix("triage-new-issues", 42)
        metadata = comment_metadata("triage-new-issues", 42, run_id="abc")
        body = f"Some content\n\n{metadata}"
        self.assertEqual(_strip_workflow_metadata(body, prefix), "Some content")

    def test_returns_body_when_prefix_absent(self) -> None:
        prefix = _workflow_metadata_prefix("triage-new-issues", 42)
        body = "Some content without metadata"
        self.assertEqual(_strip_workflow_metadata(body, prefix), body)

    def test_returns_empty_for_empty_body(self) -> None:
        prefix = _workflow_metadata_prefix("triage-new-issues", 42)
        self.assertEqual(_strip_workflow_metadata("", prefix), "")

    def test_ignores_marker_from_other_workflow(self) -> None:
        prefix = _workflow_metadata_prefix("triage-new-issues", 42)
        other = comment_metadata("create-spec-from-issue", 42, run_id="abc")
        body = f"Content\n\n{other}"
        self.assertEqual(_strip_workflow_metadata(body, prefix), body)


class WorkflowProgressCommentMetadataTest(unittest.TestCase):
    def test_initial_metadata_includes_github_run_id_from_env(self) -> None:
        os.environ["GITHUB_RUN_ID"] = "555"
        try:
            github = FakeGitHubClient()
            progress = WorkflowProgressComment(
                github,
                "acme",
                "widgets",
                42,
                workflow="triage-new-issues",
                requester_login="alice",
            )
            self.assertIn('"github_run_id":"555"', progress.metadata)
            self.assertNotIn("oz_run_id", progress.metadata)
        finally:
            os.environ.pop("GITHUB_RUN_ID", None)

    def test_initial_metadata_omits_github_run_id_when_env_missing(self) -> None:
        os.environ.pop("GITHUB_RUN_ID", None)
        github = FakeGitHubClient()
        progress = WorkflowProgressComment(
            github,
            "acme",
            "widgets",
            42,
            workflow="triage-new-issues",
            requester_login="alice",
        )
        self.assertNotIn("github_run_id", progress.metadata)

    def test_record_oz_run_id_refreshes_comment_metadata(self) -> None:
        os.environ["GITHUB_RUN_ID"] = "555"
        try:
            github = FakeGitHubClient()
            progress = WorkflowProgressComment(
                github,
                "acme",
                "widgets",
                42,
                workflow="triage-new-issues",
                requester_login="alice",
            )
            progress.start("Oz is starting to triage this issue.")
            progress.record_oz_run_id("oz-run-xyz")

            self.assertEqual(len(github.comments), 1)
            body = str(github.comments[0]["body"])
            self.assertIn('"oz_run_id":"oz-run-xyz"', body)
            self.assertIn('"github_run_id":"555"', body)
            # Body content is preserved alongside the refreshed marker.
            self.assertIn("Oz is starting to triage this issue.", body)
            # Only one metadata marker remains after the refresh.
            self.assertEqual(body.count("<!-- oz-agent-metadata:"), 1)
        finally:
            os.environ.pop("GITHUB_RUN_ID", None)

    def test_record_oz_run_id_is_idempotent(self) -> None:
        github = FakeGitHubClient()
        progress = WorkflowProgressComment(
            github,
            "acme",
            "widgets",
            42,
            workflow="triage-new-issues",
            requester_login="alice",
        )
        progress.start("Oz is starting.")
        progress.record_oz_run_id("oz-run-xyz")
        body_first = str(github.comments[0]["body"])
        progress.record_oz_run_id("oz-run-xyz")
        body_second = str(github.comments[0]["body"])
        self.assertEqual(body_first, body_second)

    def test_record_oz_run_id_noop_when_no_comment_yet(self) -> None:
        github = FakeGitHubClient()
        progress = WorkflowProgressComment(
            github,
            "acme",
            "widgets",
            42,
            workflow="triage-new-issues",
            requester_login="alice",
        )
        # Calling record_oz_run_id before any comment exists should just
        # update in-memory state and not create a GitHub comment.
        progress.record_oz_run_id("oz-run-xyz")
        self.assertEqual(github.comments, [])
        self.assertEqual(progress.oz_run_id, "oz-run-xyz")
        self.assertIn('"oz_run_id":"oz-run-xyz"', progress.metadata)

    def test_subsequent_append_preserves_refreshed_metadata(self) -> None:
        github = FakeGitHubClient()
        progress = WorkflowProgressComment(
            github,
            "acme",
            "widgets",
            42,
            workflow="triage-new-issues",
            requester_login="alice",
        )
        progress.start("Oz is starting.")
        progress.record_oz_run_id("oz-run-xyz")
        progress.complete("Oz finished triaging.")

        self.assertEqual(len(github.comments), 1)
        body = str(github.comments[0]["body"])
        self.assertIn("Oz is starting.", body)
        self.assertIn("Oz finished triaging.", body)
        self.assertIn('"oz_run_id":"oz-run-xyz"', body)
        self.assertEqual(body.count("<!-- oz-agent-metadata:"), 1)


if __name__ == "__main__":
    unittest.main()
