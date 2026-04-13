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


if __name__ == "__main__":
    unittest.main()
