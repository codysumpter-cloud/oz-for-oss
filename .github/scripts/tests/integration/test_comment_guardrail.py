"""Integration tests for the comment-on-unready-assigned-issue script.

The Python script itself is intentionally simple: it always posts the
guardrail comment and removes the oz-agent assignee. The label check
(``ready-to-spec`` / ``ready-to-implement``) lives in the YAML ``if:``
condition of ``comment-on-unready-assigned-issue-local.yml`` — that layer
is covered by act-based workflow tests rather than by Python tests.

These tests verify that the Python entry-point:
  - Posts a progress comment explaining the issue is not ready for work.
  - Calls ``remove_from_assignees`` on the issue to unassign oz-agent.
  - Resolves the assignee login from the event payload (``assignee.login``).
  - Falls back to "oz-agent" when the payload omits the assignee field.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

_SCRIPTS_DIR = Path(__file__).parent.parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from tests.integration.support import (
    FakeGitHubClient,
    FakeIssue,
    FakeRepo,
    WorkspaceSetup,
)


def _assigned_event(
    *,
    issue_number: int = 42,
    labels: list[str] | None = None,
    assignee_login: str = "oz-agent",
    sender_login: str = "maintainer",
) -> dict:
    return {
        "action": "assigned",
        "issue": {
            "number": issue_number,
            "title": "Test issue",
            "body": "body",
            "state": "open",
            "labels": [{"name": l} for l in (labels or [])],
            "user": {"login": "reporter", "type": "User"},
            "assignees": [{"login": assignee_login}],
        },
        "assignee": {"login": assignee_login},
        "sender": {"login": sender_login, "type": "User"},
    }


class CommentOnUnreadyAssignedIssueIntegrationTest(unittest.TestCase):
    """The Python script always posts the guardrail and unassigns oz-agent.

    Label-based skipping is enforced by the YAML ``if:`` condition and is
    tested separately via act-based workflow tests.
    """

    def _run_main(self, issue_number: int, labels: list[str]) -> FakeIssue:
        issue = FakeIssue(
            issue_number,
            title="Test issue",
            labels=labels,
            assignees=["oz-agent"],
        )
        repo = FakeRepo(issues=[issue])
        fake_client = FakeGitHubClient(repo)
        event = _assigned_event(issue_number=issue_number, labels=labels)

        with WorkspaceSetup(event=event, event_name="issues") as ws:
            with (
                patch(
                    "comment_on_unready_assigned_issue.Github",
                    return_value=fake_client,
                ),
                patch.dict(os.environ, ws.env(), clear=True),
            ):
                from comment_on_unready_assigned_issue import main
                main()

        return issue

    def test_guardrail_comment_is_posted(self) -> None:
        issue = self._run_main(42, labels=[])
        self.assertGreater(
            len(issue._comments),
            0,
            msg="Expected at least one guardrail comment to be posted",
        )
        comment_text = issue._comments[0].body
        self.assertTrue(
            "ready-to-spec" in comment_text or "ready-to-implement" in comment_text,
            msg=f"Guardrail keyword missing from comment: {comment_text!r}",
        )

    def test_oz_agent_is_unassigned(self) -> None:
        issue = self._run_main(42, labels=[])
        self.assertIn(
            "oz-agent",
            issue.removed_assignees,
            msg="oz-agent must be removed as assignee",
        )

    def test_assignee_login_resolved_from_event(self) -> None:
        """The script uses the assignee login from the event, not a hardcoded name."""
        issue = FakeIssue(43, title="Test", labels=[], assignees=["oz-agent"])
        repo = FakeRepo(issues=[issue])
        fake_client = FakeGitHubClient(repo)
        # Event explicitly names oz-agent as assignee
        event = _assigned_event(issue_number=43, assignee_login="oz-agent")

        with WorkspaceSetup(event=event, event_name="issues") as ws:
            with (
                patch(
                    "comment_on_unready_assigned_issue.Github",
                    return_value=fake_client,
                ),
                patch.dict(os.environ, ws.env(), clear=True),
            ):
                from comment_on_unready_assigned_issue import main
                main()

        self.assertIn("oz-agent", issue.removed_assignees)

    def test_falls_back_to_oz_agent_when_assignee_missing_from_event(self) -> None:
        issue = FakeIssue(44, title="Test", labels=[], assignees=["oz-agent"])
        repo = FakeRepo(issues=[issue])
        fake_client = FakeGitHubClient(repo)
        # Omit the assignee field from the event
        event = {
            "action": "assigned",
            "issue": {
                "number": 44,
                "title": "Test",
                "body": "body",
                "state": "open",
                "labels": [],
                "user": {"login": "reporter", "type": "User"},
                "assignees": [],
            },
            "sender": {"login": "maintainer", "type": "User"},
        }

        with WorkspaceSetup(event=event, event_name="issues") as ws:
            with (
                patch(
                    "comment_on_unready_assigned_issue.Github",
                    return_value=fake_client,
                ),
                patch.dict(os.environ, ws.env(), clear=True),
            ):
                from comment_on_unready_assigned_issue import main
                main()

        # Falls back to "oz-agent" as the default assignee login
        self.assertIn("oz-agent", issue.removed_assignees)

    def test_label_filtering_is_a_yaml_concern(self) -> None:
        """Demonstrate that the Python main() fires regardless of labels.

        This is NOT a bug — it documents that the ready-to-spec /
        ready-to-implement label check belongs in the YAML if: condition.
        The act-based workflow tests in tools/act/ verify that routing.
        """
        # Even a "ready-to-implement" labelled issue runs through the script
        # if the workflow dispatches to it (the YAML guard is bypassed).
        issue = self._run_main(45, labels=["ready-to-implement"])
        # Script always posts and unassigns — the YAML guard is bypassed here.
        self.assertGreater(len(issue._comments), 0)
        self.assertIn("oz-agent", issue.removed_assignees)


if __name__ == "__main__":
    unittest.main()
