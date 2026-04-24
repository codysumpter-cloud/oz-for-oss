"""Integration tests for the triage-new-issues workflow script.

These tests call ``triage_new_issues.main()`` directly with:
  - a temporary workspace containing the required config files
  - a fake PyGitHub client (``FakeGitHubClient``) that records all mutations
  - patched ``run_agent`` / ``poll_for_artifact`` returning canned payloads

What is being tested (beyond the existing unit tests):
  - The full execution path from environment variable / event JSON ingestion
    through prompt construction to label application and comment posting.
  - That the ``triaged`` label is appended for successful runs and omitted
    when ``needs-info`` is present.
  - That automation-authored comments are silently skipped.
  - That the ``needs-info`` + ``repro:unknown`` pair is applied when the
    agent returns follow-up questions.
  - That ``TRIAGE_ISSUE_NUMBER`` overrides the lookback scan.
  - That duplicate issues receive the ``duplicate`` label and NOT ``triaged``.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

# Ensure .github/scripts is on the path so the entrypoint module is importable.
_SCRIPTS_DIR = Path(__file__).parent.parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from tests.integration.support import (
    FakeGitHubClient,
    FakeIssue,
    FakeRepo,
    FakeRunItem,
    WorkspaceSetup,
    issue_comment_event,
    issue_opened_event,
    triage_result_bug,
    triage_result_needs_info,
)


class TriageNewIssueIntegrationTest(unittest.TestCase):
    """Happy-path: a new issue is triaged, labelled, and a comment is posted."""

    def test_new_issue_receives_bug_label_and_triaged(self) -> None:
        issue = FakeIssue(42, title="Widget crashes", body="It crashes every time")
        repo = FakeRepo(issues=[issue])
        fake_client = FakeGitHubClient(repo)
        run_item = FakeRunItem()
        result = triage_result_bug()

        with WorkspaceSetup(event=issue_opened_event(number=42)) as ws:
            with (
                patch("triage_new_issues.Github", return_value=fake_client),
                patch("triage_new_issues.run_agent", return_value=run_item),
                patch("triage_new_issues.poll_for_artifact", return_value=result),
                patch.dict(
                    os.environ,
                    ws.env({"TRIAGE_ISSUE_NUMBER": "42"}),
                    clear=True,
                ),
            ):
                from triage_new_issues import main
                main()

        self.assertIn("bug", issue.added_labels)
        self.assertIn("repro:high", issue.added_labels)
        self.assertIn("triaged", issue.added_labels)
        self.assertEqual(len(issue._comments), 1)

    def test_needs_info_result_skips_triaged_and_adds_needs_info(self) -> None:
        issue = FakeIssue(43, title="Sometimes crashes", body="Unclear repro")
        repo = FakeRepo(issues=[issue])
        fake_client = FakeGitHubClient(repo)
        run_item = FakeRunItem(run_id="needs-info-run")
        result = triage_result_needs_info()

        with WorkspaceSetup(event=issue_opened_event(number=43)) as ws:
            with (
                patch("triage_new_issues.Github", return_value=fake_client),
                patch("triage_new_issues.run_agent", return_value=run_item),
                patch("triage_new_issues.poll_for_artifact", return_value=result),
                patch.dict(
                    os.environ,
                    ws.env({"TRIAGE_ISSUE_NUMBER": "43"}),
                    clear=True,
                ),
            ):
                from triage_new_issues import main
                main()

        self.assertIn("needs-info", issue.added_labels)
        self.assertIn("bug", issue.added_labels)
        self.assertIn("repro:unknown", issue.added_labels)
        self.assertNotIn("triaged", issue.added_labels)
        # Follow-up questions trigger a progress comment
        self.assertEqual(len(issue._comments), 1)
        comment_body = issue._comments[0].body
        self.assertIn("What OS version", comment_body)

    def test_duplicate_result_adds_duplicate_label(self) -> None:
        issue = FakeIssue(44, title="Widget crash again", body="Same as another issue")
        repo = FakeRepo(issues=[issue])
        fake_client = FakeGitHubClient(repo)
        run_item = FakeRunItem(run_id="duplicate-run")
        result = triage_result_bug(
            labels=["duplicate", "bug"],
            duplicate_of=[
                {
                    "issue_number": 10,
                    "title": "Original widget crash",
                    "similarity_reason": "Same stack trace",
                }
            ],
        )

        with WorkspaceSetup(event=issue_opened_event(number=44)) as ws:
            with (
                patch("triage_new_issues.Github", return_value=fake_client),
                patch("triage_new_issues.run_agent", return_value=run_item),
                patch("triage_new_issues.poll_for_artifact", return_value=result),
                patch.dict(
                    os.environ,
                    ws.env({"TRIAGE_ISSUE_NUMBER": "44"}),
                    clear=True,
                ),
            ):
                from triage_new_issues import main
                main()

        self.assertIn("duplicate", issue.added_labels)
        self.assertIn("bug", issue.added_labels)
        self.assertIn("triaged", issue.added_labels)
        self.assertEqual(len(issue._comments), 1)
        comment_body = issue._comments[0].body
        self.assertIn("#10", comment_body)
        self.assertIn("Original widget crash", comment_body)

    def test_progress_comment_contains_session_link(self) -> None:
        issue = FakeIssue(45, title="Session link test", body="body")
        repo = FakeRepo(issues=[issue])
        fake_client = FakeGitHubClient(repo)
        run_item = FakeRunItem(
            run_id="session-link-run",
            session_link="https://app.warp.dev/session/abc123",
        )
        result = triage_result_bug()

        with WorkspaceSetup(event=issue_opened_event(number=45)) as ws:
            with (
                patch("triage_new_issues.Github", return_value=fake_client),
                patch("triage_new_issues.run_agent", return_value=run_item),
                patch("triage_new_issues.poll_for_artifact", return_value=result),
                patch.dict(
                    os.environ,
                    ws.env({"TRIAGE_ISSUE_NUMBER": "45"}),
                    clear=True,
                ),
            ):
                from triage_new_issues import main
                main()

        self.assertEqual(len(issue._comments), 1)
        comment_body = issue._comments[0].body
        # The session link is included in the comment
        self.assertIn("app.warp.dev/session/abc123", comment_body)

    def test_step_summary_records_triage_result(self) -> None:
        issue = FakeIssue(46, title="Summary test", body="body")
        repo = FakeRepo(issues=[issue])
        fake_client = FakeGitHubClient(repo)
        run_item = FakeRunItem()
        result = triage_result_bug()

        with WorkspaceSetup(event=issue_opened_event(number=46)) as ws:
            with (
                patch("triage_new_issues.Github", return_value=fake_client),
                patch("triage_new_issues.run_agent", return_value=run_item),
                patch("triage_new_issues.poll_for_artifact", return_value=result),
                patch.dict(
                    os.environ,
                    ws.env({"TRIAGE_ISSUE_NUMBER": "46"}),
                    clear=True,
                ),
            ):
                from triage_new_issues import main
                main()

            summary = ws.read_summary()

        self.assertIn("#46", summary)


class TriageIssueCommentIntegrationTest(unittest.TestCase):
    """Tests for comment-triggered triage (re-triage on needs-info reply)."""

    def test_reporter_reply_to_needs_info_triggers_retriage(self) -> None:
        issue = FakeIssue(
            50,
            title="Widget crash",
            body="It crashes",
            labels=["needs-info", "bug", "repro:unknown"],
        )
        repo = FakeRepo(issues=[issue])
        fake_client = FakeGitHubClient(repo)
        run_item = FakeRunItem()
        result = triage_result_bug()

        # Simulate: reporter (issue author) replies to a needs-info question
        event = issue_comment_event(
            issue_number=50,
            issue_labels=["needs-info", "bug", "repro:unknown"],
            comment_body="I'm on macOS 14.2 and it crashes every time.",
            commenter_login="reporter",
            issue_user_login="reporter",
        )

        with WorkspaceSetup(event=event, event_name="issue_comment") as ws:
            with (
                patch("triage_new_issues.Github", return_value=fake_client),
                patch("triage_new_issues.run_agent", return_value=run_item),
                patch("triage_new_issues.poll_for_artifact", return_value=result),
                patch.dict(os.environ, ws.env(), clear=True),
            ):
                from triage_new_issues import main
                main()

        self.assertIn("bug", issue.added_labels)
        self.assertIn("repro:high", issue.added_labels)
        self.assertIn("triaged", issue.added_labels)

    def test_bot_comment_is_silently_skipped(self) -> None:
        issue = FakeIssue(51, title="Widget crash", body="It crashes", labels=[])
        repo = FakeRepo(issues=[issue])
        fake_client = FakeGitHubClient(repo)
        run_agent_mock = unittest.mock.MagicMock()

        # The comment sender is a GitHub App bot
        event = issue_comment_event(
            issue_number=51,
            issue_labels=[],
            comment_body="Automated scan complete.",
            commenter_login="github-actions[bot]",
            author_association="NONE",
        )
        # Bot type signalled in the comment user object
        event["comment"]["user"]["type"] = "Bot"

        with WorkspaceSetup(event=event, event_name="issue_comment") as ws:
            with (
                patch("triage_new_issues.Github", return_value=fake_client),
                patch("triage_new_issues.run_agent", side_effect=run_agent_mock),
                patch.dict(os.environ, ws.env(), clear=True),
            ):
                from triage_new_issues import main
                main()

        # run_agent must not be called when the comment is from a bot
        run_agent_mock.assert_not_called()
        # No labels should be applied
        self.assertEqual(issue.added_labels, [])

    def test_triage_skipped_for_pr_comment(self) -> None:
        """Comments on pull requests (not issues) must be ignored."""
        issue = FakeIssue(
            52,
            title="PR that looks like issue",
            body="body",
            pull_request={"url": "https://github.com/testorg/testrepo/pull/52"},
        )
        repo = FakeRepo(issues=[issue])
        fake_client = FakeGitHubClient(repo)
        run_agent_mock = unittest.mock.MagicMock()

        event = issue_comment_event(
            issue_number=52,
            issue_labels=[],
            comment_body="@oz-agent triage this please",
            commenter_login="contributor",
            pull_request={"url": "https://github.com/testorg/testrepo/pull/52"},
        )
        event["issue"]["pull_request"] = {
            "url": "https://github.com/testorg/testrepo/pull/52"
        }

        with WorkspaceSetup(event=event, event_name="issue_comment") as ws:
            with (
                patch("triage_new_issues.Github", return_value=fake_client),
                patch("triage_new_issues.run_agent", side_effect=run_agent_mock),
                patch.dict(os.environ, ws.env(), clear=True),
            ):
                from triage_new_issues import main
                main()

        run_agent_mock.assert_not_called()


class TriageLookbackScanIntegrationTest(unittest.TestCase):
    """Tests for the lookback scan mode (no explicit TRIAGE_ISSUE_NUMBER)."""

    def test_lookback_scan_triages_recent_untriaged_issue(self) -> None:
        from datetime import timezone

        issue = FakeIssue(
            60,
            title="Recent issue",
            body="Recent report",
            labels=[],
            created_at=__import__("datetime").datetime.now(timezone.utc)
            - __import__("datetime").timedelta(minutes=30),
        )
        repo = FakeRepo(issues=[issue])
        fake_client = FakeGitHubClient(repo)
        run_item = FakeRunItem()
        result = triage_result_bug()

        # Use a workflow_dispatch event so the lookback scan is used
        dispatch_event: dict = {"action": "workflow_dispatch"}

        with WorkspaceSetup(
            event=dispatch_event, event_name="workflow_dispatch"
        ) as ws:
            with (
                patch("triage_new_issues.Github", return_value=fake_client),
                patch("triage_new_issues.run_agent", return_value=run_item),
                patch("triage_new_issues.poll_for_artifact", return_value=result),
                patch.dict(
                    os.environ,
                    ws.env({"LOOKBACK_MINUTES": "60"}),
                    clear=True,
                ),
            ):
                from triage_new_issues import main
                main()

        self.assertIn("triaged", issue.added_labels)

    def test_lookback_scan_skips_already_triaged_issues(self) -> None:
        from datetime import timezone

        issue = FakeIssue(
            61,
            title="Already triaged issue",
            body="body",
            labels=["triaged", "bug"],
            created_at=__import__("datetime").datetime.now(timezone.utc)
            - __import__("datetime").timedelta(minutes=30),
        )
        repo = FakeRepo(issues=[issue])
        fake_client = FakeGitHubClient(repo)
        run_agent_mock = unittest.mock.MagicMock()

        # Use a workflow_dispatch event (no issue.number) so the lookback
        # scan path is used rather than the issue-number-override path.
        dispatch_event: dict = {"action": "workflow_dispatch"}

        with WorkspaceSetup(
            event=dispatch_event, event_name="workflow_dispatch"
        ) as ws:
            with (
                patch("triage_new_issues.Github", return_value=fake_client),
                patch("triage_new_issues.run_agent", side_effect=run_agent_mock),
                patch.dict(
                    os.environ,
                    ws.env({"LOOKBACK_MINUTES": "60"}),
                    clear=True,
                ),
            ):
                from triage_new_issues import main
                main()

        run_agent_mock.assert_not_called()


import unittest.mock  # noqa: E402 (needed for side_effect type reference above)

if __name__ == "__main__":
    unittest.main()
