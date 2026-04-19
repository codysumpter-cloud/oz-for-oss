from __future__ import annotations

import io
import json
import logging
import os
import unittest
from contextlib import redirect_stdout

from oz_workflows.helpers import (
    _strip_workflow_metadata,
    _workflow_metadata_prefix,
    _workflow_run_url,
    append_comment_sections,
    build_comment_body,
    comment_metadata,
    format_enforce_start_line,
    format_implementation_complete_line,
    format_implementation_start_line,
    format_pr_comment_start_line,
    format_respond_to_triaged_start_line,
    format_review_start_line,
    format_spec_complete_line,
    format_spec_start_line,
    format_triage_session_line,
    format_triage_start_line,
    issue_has_prior_triage,
    POWERED_BY_SUFFIX,
    WorkflowProgressComment,
)


class CommentUpdateTest(unittest.TestCase):
    def test_appends_instead_of_replacing(self) -> None:
        metadata = "<!-- meta -->"
        existing = build_comment_body("@alice\n\nI'm working on this issue.\n\nYou can follow along in [the session on Warp](https://example.test/session/123).", metadata)
        updated = append_comment_sections(existing, metadata, ["I created a [spec PR](https://example.test/pr/1) for this issue."])
        self.assertIn("You can follow along in [the session on Warp](https://example.test/session/123).", updated)
        self.assertIn("I created a [spec PR](https://example.test/pr/1) for this issue.", updated)
        self.assertTrue(updated.endswith(metadata))
        # Suffix is present exactly once and sits immediately above the metadata.
        self.assertEqual(updated.count(POWERED_BY_SUFFIX), 1)
        self.assertIn(f"{POWERED_BY_SUFFIX}\n\n{metadata}", updated)
    def test_replaces_existing_session_link_when_url_changes(self) -> None:
        metadata = "<!-- meta -->"
        existing = build_comment_body("@alice\n\nI'm working on this issue.\n\nYou can follow along in [the session on Warp](https://example.test/session/123).", metadata)
        updated = append_comment_sections(existing, metadata, ["You can view [the conversation on Warp](https://example.test/conversation/456)."])
        self.assertNotIn("https://example.test/session/123", updated)
        self.assertIn("You can view [the conversation on Warp](https://example.test/conversation/456).", updated)
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
        progress.start("I'm starting work on product and tech specs for this issue.")
        progress.record_session_link("https://example.test/session/123")
        progress.complete("I created a new [spec PR](https://example.test/pr/1) for this issue.")

        self.assertEqual(len(github.comments), 1)
        body = github.comments[0]["body"]
        self.assertIn("@alice", body)
        self.assertIn("I'm starting work on product and tech specs for this issue.", body)
        self.assertIn("You can follow along in [the session on Warp](https://example.test/session/123).", body)
        self.assertIn("I created a new [spec PR](https://example.test/pr/1) for this issue.", body)
        # Suffix should appear exactly once even after multiple appends.
        self.assertEqual(body.count(POWERED_BY_SUFFIX), 1)
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
        progress.start("I'm starting work on product and tech specs for this issue.")
        progress.record_session_link("https://example.test/session/123")
        progress.record_session_link("https://example.test/conversation/456")

        self.assertEqual(len(github.comments), 1)
        body = github.comments[0]["body"]
        self.assertNotIn("https://example.test/session/123", body)
        self.assertIn("You can view [the conversation on Warp](https://example.test/conversation/456).", body)

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
        run1.start("I've started triaging this issue.")
        run1.record_session_link("https://example.test/session/run1")

        run2 = WorkflowProgressComment(
            github,
            "acme",
            "widgets",
            42,
            workflow="triage-new-issues",
            requester_login="alice",
        )
        run2.start("I've started triaging this issue.")
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
        progress.start("I'm working on changes requested in this PR.")

        # No issue-level comments should have been created.
        self.assertEqual(github.comments, [])
        # A reply was posted within the review thread.
        replies = [c for c in pr.review_comments if c.get("in_reply_to_id") == 100]
        self.assertEqual(len(replies), 1)
        self.assertIn("I'm working on changes", replies[0]["body"])

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
        progress.start("I'm working on changes requested in this PR.")
        progress.record_session_link("https://example.test/session/123")
        progress.complete("I pushed changes to this PR based on the comment.")

        replies = [c for c in pr.review_comments if c.get("in_reply_to_id") == 100]
        self.assertEqual(len(replies), 1)
        body = replies[0]["body"]
        self.assertIn("@alice", body)
        self.assertIn("I'm working on changes", body)
        self.assertIn("You can follow along in [the session on Warp](https://example.test/session/123).", body)
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
        progress.start("I'm starting to work on this.")
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
        progress.start("I'm starting.")
        progress.complete("I finished.")

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
        progress.start("I'm working on changes requested in this PR.")

        replies = [c for c in pr.review_comments if c.get("in_reply_to_id") == 100]
        self.assertEqual(len(replies), 1)
        self.assertIn("I'm working on changes", replies[0]["body"])

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
        progress.start("I'm working.")
        pr.fail_next_edit = True
        progress.record_session_link("https://example.test/session/abc")
        # The first attempt failed, so the session link should not be
        # recorded yet, but the workflow is expected to continue running.
        replies = [c for c in pr.review_comments if c.get("in_reply_to_id") == 100]
        self.assertNotIn("https://example.test/session/abc", replies[0]["body"])
        # The next poll retries with the same link and succeeds.
        progress.record_session_link("https://example.test/session/abc")
        replies = [c for c in pr.review_comments if c.get("in_reply_to_id") == 100]
        self.assertIn("You can follow along in [the session on Warp](https://example.test/session/abc).", replies[0]["body"])

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
        progress.start("I'm working.")
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
            progress.start("I'm starting to work on this.")
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
            progress.start("I'm starting.")
            progress.record_session_link("https://example.test/conversation/abc")
            progress.report_error()

            self.assertEqual(len(github.comments), 1)
            body = github.comments[0]["body"]
            self.assertIn("unexpected error", body)
            self.assertIn("You can view [the conversation on Warp](https://example.test/conversation/abc).", body)
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
        progress.start("I'm starting.")
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
            progress.start("I'm starting.")
            progress.report_error()

            body = github.comments[0]["body"]
            self.assertIn("<!-- oz-agent-metadata:", body)
        finally:
            for key in env:
                os.environ.pop(key, None)

    def test_report_error_uses_cached_requester_without_api_lookup(self) -> None:
        # Simulate the bug's trigger: no requester_login provided at
        # construction (so resolve_progress_requester_login would normally
        # fall back to resolve_oz_assigner_login/_list_issue_events) and
        # the underlying GitHub API refuses issue-events lookups. The
        # initial start() populates the requester from the event payload
        # and caches it, and a later GitHub API outage during report_error
        # must not re-trigger the failing events lookup.
        github = FailingEventsGitHubClient()
        progress = WorkflowProgressComment(
            github,
            "acme",
            "widgets",
            7,
            workflow="test-workflow",
            event_payload={"sender": {"login": "alice"}},
        )
        progress.start("I'm starting.")
        # The requester should have been cached from the event payload on
        # the successful first update.
        self.assertEqual(progress.requester_login, "alice")
        # Now clear the event payload as if only the cached value remains
        # (e.g. a fresh object reconstructed from run state).
        progress.event_payload = {}

        # The API is still healthy for comment CRUD, so report_error
        # should succeed using the cached login, and it must not attempt
        # to re-resolve the requester via list_issue_events.
        with self.assertLogs("oz_workflows.helpers", level="ERROR") as captured:
            progress.report_error()
            # assertLogs requires at least one record; emit a synthetic
            # one so we can still assert no ERROR was emitted by the SUT.
            logging.getLogger("oz_workflows.helpers").error("sentinel")
        self.assertEqual(
            [rec.getMessage() for rec in captured.records if rec.levelno >= logging.ERROR and rec.getMessage() != "sentinel"],
            [],
        )
        self.assertEqual(github.events_calls, 0)
        self.assertEqual(len(github.comments), 1)
        body = github.comments[0]["body"]
        self.assertIn("@alice", body)
        self.assertIn("unexpected error", body)

    def test_report_error_logs_and_emits_annotation_when_comment_write_fails(self) -> None:
        # When the GitHub API outage also prevents posting the fallback
        # user-facing error comment, report_error must not silently
        # swallow the exception: it should log the traceback via
        # logger.exception and emit an `::error::` annotation so the
        # Actions run is visibly marked failed.
        github = CommentWriteFailsGitHubClient()
        progress = WorkflowProgressComment(
            github,
            "acme",
            "widgets",
            7,
            workflow="test-workflow",
            requester_login="alice",
        )

        buf = io.StringIO()
        with self.assertLogs("oz_workflows.helpers", level="ERROR") as captured, redirect_stdout(buf):
            progress.report_error()

        # The simulated outage message should appear in the logged
        # traceback so operators can see the root cause.
        self.assertTrue(
            any("Failed to post workflow error comment" in rec.getMessage() for rec in captured.records),
            msg=f"Expected error log not found in records: {[rec.getMessage() for rec in captured.records]}",
        )
        self.assertTrue(
            any("simulated GitHub API outage" in (rec.exc_text or "") for rec in captured.records),
            msg="Expected swallowed exception traceback to be logged",
        )
        # An ::error:: annotation should have been emitted to stdout so
        # the Actions UI marks the step as failed.
        self.assertIn("::error::", buf.getvalue())
        self.assertIn("test-workflow", buf.getvalue())

    def test_report_error_does_not_raise_when_everything_fails(self) -> None:
        # report_error is the last-chance hook before the caller re-raises
        # the underlying workflow exception; it must never itself raise.
        github = CommentWriteFailsGitHubClient()
        progress = WorkflowProgressComment(
            github,
            "acme",
            "widgets",
            7,
            workflow="test-workflow",
            requester_login="alice",
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            # Should not raise.
            progress.report_error()


class FakeIssueComment:
    """A minimal stand-in for ``github.IssueComment.IssueComment``."""

    def __init__(self, repo: "FakeGitHubClient", data: dict[str, object]) -> None:
        self._repo = repo
        self._data = data

    @property
    def id(self) -> int:
        return int(self._data["id"])  # type: ignore[arg-type]

    @property
    def body(self) -> str:
        return str(self._data.get("body") or "")

    def edit(self, body: str) -> None:
        self._data["body"] = body

    def delete(self) -> None:
        self._repo.comments = [
            c for c in self._repo.comments if int(c["id"]) != self.id  # type: ignore[arg-type]
        ]


class FakeIssue:
    """A minimal stand-in for ``github.Issue.Issue``."""

    def __init__(self, repo: "FakeGitHubClient", issue_number: int) -> None:
        self._repo = repo
        self._issue_number = issue_number

    def get_comments(self) -> list[FakeIssueComment]:
        return [FakeIssueComment(self._repo, c) for c in self._repo.comments]

    def create_comment(self, body: str) -> FakeIssueComment:
        data: dict[str, object] = {"id": len(self._repo.comments) + 1, "body": body}
        self._repo.comments.append(data)
        return FakeIssueComment(self._repo, data)

    def get_comment(self, comment_id: int) -> FakeIssueComment:
        for c in self._repo.comments:
            if int(c["id"]) == comment_id:  # type: ignore[arg-type]
                return FakeIssueComment(self._repo, c)
        raise AssertionError(f"Missing comment {comment_id}")

    def get_events(self) -> list[object]:
        return []


class FakeGitHubClient:
    """A minimal stand-in for ``github.Repository.Repository``."""

    def __init__(self) -> None:
        self.comments: list[dict[str, object]] = []

    def get_issue(self, issue_number: int) -> FakeIssue:
        return FakeIssue(self, issue_number)


class FailingEventsGitHubClient(FakeGitHubClient):
    """A FakeGitHubClient whose issue-events endpoint is broken.

    Simulates the scenario in issue #220: the workflow is triggered by a
    GitHub API outage that specifically takes down the issue-events
    endpoint used by ``resolve_oz_assigner_login``. Any attempt to
    resolve the requester login via that fallback must surface as a
    failure so we can assert the error path never reaches it.
    """

    def __init__(self) -> None:
        super().__init__()
        self.events_calls = 0

    def list_issue_events(self, owner: str, repo: str, issue_number: int) -> list[dict[str, object]]:
        self.events_calls += 1
        raise RuntimeError("simulated GitHub API outage on events endpoint")


class CommentWriteFailsIssueComment(FakeIssueComment):
    """A FakeIssueComment whose edit endpoint is broken."""

    def edit(self, body: str) -> None:
        raise RuntimeError("simulated GitHub API outage on update_comment")


class CommentWriteFailsIssue(FakeIssue):
    """A FakeIssue whose comment write endpoints are broken."""

    def create_comment(self, body: str) -> FakeIssueComment:
        raise RuntimeError("simulated GitHub API outage on create_comment")

    def get_comment(self, comment_id: int) -> FakeIssueComment:
        for c in self._repo.comments:
            if int(c["id"]) == comment_id:  # type: ignore[arg-type]
                return CommentWriteFailsIssueComment(self._repo, c)
        raise AssertionError(f"Missing comment {comment_id}")


class CommentWriteFailsGitHubClient(FakeGitHubClient):
    """A FakeGitHubClient whose comment write endpoints are broken.

    Simulates a GitHub outage that also prevents the fallback error
    comment from being posted. ``report_error`` must catch the failure,
    log it, and emit an ``::error::`` annotation rather than silently
    swallow it.
    """

    def get_issue(self, issue_number: int) -> CommentWriteFailsIssue:
        return CommentWriteFailsIssue(self, issue_number)


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
            progress.start("I'm starting to triage this issue.")
            progress.record_oz_run_id("oz-run-xyz")

            self.assertEqual(len(github.comments), 1)
            body = str(github.comments[0]["body"])
            self.assertIn('"oz_run_id":"oz-run-xyz"', body)
            self.assertIn('"github_run_id":"555"', body)
            # Body content is preserved alongside the refreshed marker.
            self.assertIn("I'm starting to triage this issue.", body)
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
        progress.start("I'm starting.")
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
        progress.start("I'm starting.")
        progress.record_oz_run_id("oz-run-xyz")
        progress.complete("I finished triaging.")

        self.assertEqual(len(github.comments), 1)
        body = str(github.comments[0]["body"])
        self.assertIn("I'm starting.", body)
        self.assertIn("I finished triaging.", body)
        self.assertIn('"oz_run_id":"oz-run-xyz"', body)
        self.assertEqual(body.count("<!-- oz-agent-metadata:"), 1)


class StateAwareStartLineTest(unittest.TestCase):
    def test_triage_first_pass_and_retriage(self) -> None:
        self.assertEqual(
            format_triage_start_line(is_retriage=False),
            "I'm starting to work on triaging this issue.",
        )
        self.assertIn(
            "re-triaging",
            format_triage_start_line(is_retriage=True),
        )

    def test_triage_session_line_reflects_retriage(self) -> None:
        first = format_triage_session_line(
            is_retriage=False, session_link_markdown="[link](https://x)"
        )
        self.assertIn("I'm triaging this issue.", first)
        self.assertIn("[link](https://x)", first)
        again = format_triage_session_line(
            is_retriage=True, session_link_markdown="[link](https://x)"
        )
        self.assertIn("re-triaging", again)

    def test_issue_has_prior_triage_detects_triaged_label(self) -> None:
        self.assertTrue(issue_has_prior_triage([{"name": "triaged"}]))
        self.assertTrue(issue_has_prior_triage(["triaged"]))
        # Case-insensitive match on the triaged label.
        self.assertTrue(issue_has_prior_triage([{"name": "Triaged"}]))

    def test_issue_has_prior_triage_ignores_non_triage_labels(self) -> None:
        self.assertFalse(issue_has_prior_triage([]))
        self.assertFalse(issue_has_prior_triage([{"name": "repro:unknown"}]))
        self.assertFalse(issue_has_prior_triage(["area:workflow"]))
        # Labels commonly applied by reporters or maintainers before any
        # triage run must not be treated as prior-triage evidence.
        self.assertFalse(issue_has_prior_triage([{"name": "bug"}]))
        self.assertFalse(issue_has_prior_triage(["enhancement"]))
        self.assertFalse(issue_has_prior_triage([{"name": "documentation"}]))
        self.assertFalse(issue_has_prior_triage(["needs-info"]))
        self.assertFalse(issue_has_prior_triage([{"name": "duplicate"}]))

    def test_respond_to_triaged_start_line_describes_analytical_path(self) -> None:
        line = format_respond_to_triaged_start_line()
        self.assertIn("already triaged", line)
        self.assertIn("inline", line)
        self.assertIn("without changing labels", line)

    def test_spec_start_line_distinguishes_new_and_update(self) -> None:
        self.assertIn(
            "starting work on product and tech specs",
            format_spec_start_line(is_update=False),
        )
        self.assertIn(
            "updating the existing spec PR",
            format_spec_start_line(is_update=True),
        )

    def test_spec_complete_line_distinguishes_new_and_update(self) -> None:
        self.assertIn(
            "I created a new [spec PR](https://x)",
            format_spec_complete_line(is_update=False, pr_url="https://x"),
        )
        self.assertIn(
            "I updated the existing [spec PR](https://x)",
            format_spec_complete_line(is_update=True, pr_url="https://x"),
        )

    def test_implementation_start_line_approved_pr(self) -> None:
        line = format_implementation_start_line(
            spec_context_source="approved-pr",
            should_noop=False,
            existing_implementation_pr=False,
        )
        self.assertIn("approved spec PR's branch", line)
        self.assertNotIn("updating the existing draft PR", line)

    def test_implementation_start_line_directory_spec(self) -> None:
        line = format_implementation_start_line(
            spec_context_source="directory",
            should_noop=False,
            existing_implementation_pr=False,
        )
        self.assertIn("directory specs", line)

    def test_implementation_start_line_no_spec(self) -> None:
        line = format_implementation_start_line(
            spec_context_source="",
            should_noop=False,
            existing_implementation_pr=False,
        )
        self.assertIn("no spec context", line)

    def test_implementation_start_line_noop_mentions_unapproved_prs(self) -> None:
        line = format_implementation_start_line(
            spec_context_source="",
            should_noop=True,
            existing_implementation_pr=False,
            unapproved_spec_pr_numbers=[7, 9],
        )
        self.assertIn("not starting implementation", line)
        self.assertIn("`plan-approved`", line)
        self.assertIn("#7", line)
        self.assertIn("#9", line)

    def test_implementation_start_line_existing_draft_pr(self) -> None:
        line = format_implementation_start_line(
            spec_context_source="",
            should_noop=False,
            existing_implementation_pr=True,
        )
        self.assertIn("updating the existing draft PR", line)

    def test_implementation_complete_line_variants(self) -> None:
        self.assertIn(
            "approved [spec PR](https://x)",
            format_implementation_complete_line(
                updated_spec_pr=True,
                existing_implementation_pr=False,
                pr_url="https://x",
            ),
        )
        self.assertIn(
            "I updated the existing draft [implementation PR](https://x)",
            format_implementation_complete_line(
                updated_spec_pr=False,
                existing_implementation_pr=True,
                pr_url="https://x",
            ),
        )
        self.assertIn(
            "I created a new draft [implementation PR](https://x)",
            format_implementation_complete_line(
                updated_spec_pr=False,
                existing_implementation_pr=False,
                pr_url="https://x",
            ),
        )

    def test_review_start_line_distinguishes_spec_and_code(self) -> None:
        self.assertIn(
            "spec-only pull request",
            format_review_start_line(spec_only=True, is_rereview=False),
        )
        self.assertIn(
            "first review of this pull request",
            format_review_start_line(spec_only=False, is_rereview=False),
        )

    def test_review_start_line_distinguishes_rereview(self) -> None:
        self.assertIn(
            "re-reviewing",
            format_review_start_line(spec_only=False, is_rereview=True),
        )

    def test_review_start_line_includes_focus(self) -> None:
        self.assertIn(
            "Focus: security",
            format_review_start_line(
                spec_only=False, is_rereview=True, focus="security"
            ),
        )

    def test_pr_comment_start_line_distinguishes_thread_source(self) -> None:
        self.assertIn(
            "an inline review-thread comment",
            format_pr_comment_start_line(
                is_review_reply=True, has_spec_context=False
            ),
        )
        self.assertIn(
            "a PR conversation comment",
            format_pr_comment_start_line(
                is_review_reply=False, has_spec_context=False
            ),
        )

    def test_pr_comment_start_line_mentions_spec_context(self) -> None:
        self.assertIn(
            "Spec context was found",
            format_pr_comment_start_line(
                is_review_reply=False, has_spec_context=True
            ),
        )

    def test_enforce_start_line_distinguishes_match_paths(self) -> None:
        self.assertIn(
            "explicitly linked issue",
            format_enforce_start_line(
                explicit_issue=True, change_kind="implementation"
            ),
        )
        self.assertIn(
            "likely matching ready issue",
            format_enforce_start_line(
                explicit_issue=False, change_kind="spec"
            ),
        )
        self.assertIn(
            "spec PR",
            format_enforce_start_line(
                explicit_issue=False, change_kind="spec"
            ),
        )


if __name__ == "__main__":
    unittest.main()
