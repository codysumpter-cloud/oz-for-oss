from __future__ import annotations

import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def _make_event(
    *,
    pr_number: int = 10,
    pr_state: str = "open",
    sender_login: str = "alice",
    sender_type: str = "User",
) -> dict:
    return {
        "pull_request": {
            "number": pr_number,
            "state": pr_state,
        },
        "sender": {"login": sender_login, "type": sender_type},
        "repository": {"default_branch": "main", "full_name": "owner/repo"},
    }


def _write_event(event: dict) -> str:
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(event, handle)
    return path


def _make_issue(
    *,
    number: int = 42,
    title: str = "Test issue",
    body: str = "Issue body",
    labels: list[str] | None = None,
    assignees: list[str] | None = None,
) -> MagicMock:
    issue = MagicMock()
    issue.number = number
    issue.title = title
    issue.body = body
    issue.pull_request = None
    issue.labels = [SimpleNamespace(name=name) for name in (labels or [])]
    issue.assignees = [SimpleNamespace(login=login) for login in (assignees or [])]
    return issue


class TriggerImplementationOnPlanApprovedTest(unittest.TestCase):
    def test_exits_silently_when_pr_is_closed(self) -> None:
        event = _make_event(pr_state="closed")
        event_path = _write_event(event)
        try:
            with (
                patch.dict(os.environ, {"GITHUB_EVENT_PATH": event_path, "GITHUB_REPOSITORY": "owner/repo", "GH_TOKEN": "token"}),
                patch("trigger_implementation_on_plan_approved.Github") as mock_github_cls,
            ):
                from trigger_implementation_on_plan_approved import main
                main()
                mock_github_cls.assert_not_called()
        finally:
            os.unlink(event_path)

    def test_exits_silently_when_sender_is_bot(self) -> None:
        event = _make_event(sender_login="dependabot[bot]", sender_type="Bot")
        event_path = _write_event(event)
        try:
            with (
                patch.dict(os.environ, {"GITHUB_EVENT_PATH": event_path, "GITHUB_REPOSITORY": "owner/repo", "GH_TOKEN": "token"}),
                patch("trigger_implementation_on_plan_approved.Github") as mock_github_cls,
            ):
                from trigger_implementation_on_plan_approved import main
                main()
                mock_github_cls.assert_not_called()
        finally:
            os.unlink(event_path)

    def test_exits_silently_when_no_associated_issue(self) -> None:
        event = _make_event()
        event_path = _write_event(event)
        try:
            client = MagicMock()
            client.close = MagicMock()
            github = MagicMock()
            client.get_repo.return_value = github

            pr_obj = MagicMock()
            pr_obj.get_files.return_value = [SimpleNamespace(filename="specs/GH42/product.md")]
            github.get_pull.return_value = pr_obj

            with (
                patch.dict(os.environ, {"GITHUB_EVENT_PATH": event_path, "GITHUB_REPOSITORY": "owner/repo", "GH_TOKEN": "token"}),
                patch("trigger_implementation_on_plan_approved.Github", return_value=client),
                patch("trigger_implementation_on_plan_approved.Auth.Token", return_value="token"),
                patch("trigger_implementation_on_plan_approved.resolve_issue_number_for_pr", return_value=None),
            ):
                from trigger_implementation_on_plan_approved import main
                main()
                github.get_issue.assert_not_called()
        finally:
            os.unlink(event_path)

    def test_exits_silently_when_issue_lacks_ready_to_implement(self) -> None:
        event = _make_event()
        event_path = _write_event(event)
        try:
            client = MagicMock()
            client.close = MagicMock()
            github = MagicMock()
            client.get_repo.return_value = github

            pr_obj = MagicMock()
            pr_obj.get_files.return_value = [SimpleNamespace(filename="specs/GH42/product.md")]
            github.get_pull.return_value = pr_obj

            issue = _make_issue(labels=["ready-to-spec"], assignees=["oz-agent"])
            github.get_issue.return_value = issue

            with (
                patch.dict(os.environ, {"GITHUB_EVENT_PATH": event_path, "GITHUB_REPOSITORY": "owner/repo", "GH_TOKEN": "token"}),
                patch("trigger_implementation_on_plan_approved.Github", return_value=client),
                patch("trigger_implementation_on_plan_approved.Auth.Token", return_value="token"),
                patch("trigger_implementation_on_plan_approved.resolve_issue_number_for_pr", return_value=42),
            ):
                from trigger_implementation_on_plan_approved import main
                main()
                # Should not proceed to calling the implementation workflow
        finally:
            os.unlink(event_path)

    def test_exits_silently_when_oz_agent_not_assigned(self) -> None:
        event = _make_event()
        event_path = _write_event(event)
        try:
            client = MagicMock()
            client.close = MagicMock()
            github = MagicMock()
            client.get_repo.return_value = github

            pr_obj = MagicMock()
            pr_obj.get_files.return_value = [SimpleNamespace(filename="specs/GH42/product.md")]
            github.get_pull.return_value = pr_obj

            issue = _make_issue(labels=["ready-to-implement"], assignees=["some-human"])
            github.get_issue.return_value = issue

            with (
                patch.dict(os.environ, {"GITHUB_EVENT_PATH": event_path, "GITHUB_REPOSITORY": "owner/repo", "GH_TOKEN": "token"}),
                patch("trigger_implementation_on_plan_approved.Github", return_value=client),
                patch("trigger_implementation_on_plan_approved.Auth.Token", return_value="token"),
                patch("trigger_implementation_on_plan_approved.resolve_issue_number_for_pr", return_value=42),
            ):
                from trigger_implementation_on_plan_approved import main
                main()
                # Should not proceed to calling the implementation workflow
        finally:
            os.unlink(event_path)

    def test_calls_implementation_when_conditions_met(self) -> None:
        event = _make_event()
        event_path = _write_event(event)
        captured_events: list[dict] = []

        def _capture_synthetic_event() -> None:
            """Read the synthetic event file during the mocked implementation call."""
            path = os.environ.get("GITHUB_EVENT_PATH", "")
            if path and os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    captured_events.append(json.load(f))

        try:
            client = MagicMock()
            client.close = MagicMock()
            github = MagicMock()
            client.get_repo.return_value = github

            pr_obj = MagicMock()
            pr_obj.get_files.return_value = [SimpleNamespace(filename="specs/GH42/product.md")]
            github.get_pull.return_value = pr_obj

            issue = _make_issue(
                number=42,
                title="Test issue",
                body="Issue body",
                labels=["ready-to-implement", "enhancement"],
                assignees=["oz-agent"],
            )
            github.get_issue.return_value = issue

            with (
                patch.dict(os.environ, {"GITHUB_EVENT_PATH": event_path, "GITHUB_REPOSITORY": "owner/repo", "GH_TOKEN": "token"}),
                patch("trigger_implementation_on_plan_approved.Github", return_value=client),
                patch("trigger_implementation_on_plan_approved.Auth.Token", return_value="token"),
                patch("trigger_implementation_on_plan_approved.resolve_issue_number_for_pr", return_value=42),
                patch("create_implementation_from_issue.main", side_effect=_capture_synthetic_event) as mock_impl_main,
            ):
                from trigger_implementation_on_plan_approved import main
                main()
                mock_impl_main.assert_called_once()

                # Verify the synthetic event captured during the implementation call
                self.assertEqual(len(captured_events), 1)
                synthetic_event = captured_events[0]
                self.assertEqual(synthetic_event["issue"]["number"], 42)
                self.assertEqual(synthetic_event["issue"]["title"], "Test issue")
                self.assertIn(
                    {"name": "ready-to-implement"},
                    synthetic_event["issue"]["labels"],
                )
                self.assertIn(
                    {"login": "oz-agent"},
                    synthetic_event["issue"]["assignees"],
                )
                self.assertEqual(synthetic_event["repository"]["default_branch"], "main")
                self.assertEqual(synthetic_event["sender"]["login"], "alice")
        finally:
            if os.path.exists(event_path):
                os.unlink(event_path)


if __name__ == "__main__":
    unittest.main()
