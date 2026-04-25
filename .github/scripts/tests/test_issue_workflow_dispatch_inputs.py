"""workflow_dispatch coverage for issue-driven spec and implementation entrypoints."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def _write_event(event: dict) -> str:
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(event, handle)
    return path


def _workflow_dispatch_event() -> dict:
    return {
        "inputs": {"issue_number": "317"},
        "repository": {"default_branch": "main", "full_name": "owner/repo"},
        "sender": {"login": "alice", "type": "User"},
    }


def _mock_issue_data(*, title: str, body: str, labels: list[str]) -> MagicMock:
    issue = MagicMock()
    issue.title = title
    issue.body = body
    issue.labels = [SimpleNamespace(name=name) for name in labels]
    issue.assignees = [SimpleNamespace(login="oz-agent")]
    issue.get_comments.return_value = []
    return issue


class WorkflowDispatchIssueInputsTest(unittest.TestCase):
    def test_create_spec_uses_issue_number_input_when_event_has_no_issue(self) -> None:
        event_path = _write_event(_workflow_dispatch_event())
        captured: dict[str, str] = {}

        def _capture(**kwargs):
            captured["prompt"] = kwargs.get("prompt", "")
            return SimpleNamespace(
                run_id="run-spec",
                created_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            )

        issue_data = _mock_issue_data(
            title="Dispatchable spec issue",
            body="Spec body",
            labels=["enhancement", "ready-to-spec"],
        )

        try:
            with (
                patch.dict(
                    os.environ,
                    {
                        "GITHUB_EVENT_PATH": event_path,
                        "GITHUB_EVENT_NAME": "workflow_dispatch",
                        "GITHUB_REPOSITORY": "owner/repo",
                        "GH_TOKEN": "token",
                        "ISSUE_NUMBER": "317",
                    },
                ),
                patch("create_spec_from_issue.Github") as mock_github_cls,
                patch("create_spec_from_issue.Auth.Token", return_value="token"),
                patch("create_spec_from_issue.WorkflowProgressComment"),
                patch("create_spec_from_issue.resolve_coauthor_line", return_value=""),
                patch("create_spec_from_issue.build_agent_config", return_value=MagicMock()),
                patch("create_spec_from_issue.run_agent", side_effect=_capture),
                patch("create_spec_from_issue.branch_updated_since", return_value=False),
                patch(
                    "create_spec_from_issue.skill_file_path",
                    side_effect=lambda name: f".agents/skills/{name}/SKILL.md",
                ),
            ):
                client = MagicMock()
                client.close = MagicMock()
                github = MagicMock()
                github.default_branch = "main"
                github.get_issue.return_value = issue_data
                github.get_pulls.return_value = []
                client.get_repo.return_value = github
                mock_github_cls.return_value = client

                from create_spec_from_issue import main

                main()
        finally:
            os.unlink(event_path)

        prompt = captured.get("prompt", "")
        self.assertIn("GitHub issue #317", prompt)
        self.assertIn("Dispatchable spec issue", prompt)
        self.assertIn("enhancement, ready-to-spec", prompt)

    def test_create_implementation_uses_issue_number_input_when_event_has_no_issue(self) -> None:
        event_path = _write_event(_workflow_dispatch_event())
        captured: dict[str, str] = {}

        def _capture(**kwargs):
            captured["prompt"] = kwargs.get("prompt", "")
            return SimpleNamespace(
                run_id="run-impl",
                created_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            )

        spec_context = {
            "selected_spec_pr": None,
            "approved_spec_prs": [],
            "unapproved_spec_prs": [],
            "spec_context_source": "",
            "spec_entries": [],
        }
        issue_data = _mock_issue_data(
            title="Dispatchable implementation issue",
            body="Implementation body",
            labels=["enhancement", "ready-to-implement"],
        )

        try:
            with (
                patch.dict(
                    os.environ,
                    {
                        "GITHUB_EVENT_PATH": event_path,
                        "GITHUB_EVENT_NAME": "workflow_dispatch",
                        "GITHUB_REPOSITORY": "owner/repo",
                        "GH_TOKEN": "token",
                        "ISSUE_NUMBER": "317",
                    },
                ),
                patch("create_implementation_from_issue.Github") as mock_github_cls,
                patch("create_implementation_from_issue.Auth.Token", return_value="token"),
                patch(
                    "create_implementation_from_issue.resolve_spec_context_for_issue",
                    return_value=spec_context,
                ),
                patch("create_implementation_from_issue.WorkflowProgressComment"),
                patch("create_implementation_from_issue.resolve_coauthor_line", return_value=""),
                patch(
                    "create_implementation_from_issue.build_agent_config",
                    return_value=MagicMock(),
                ),
                patch("create_implementation_from_issue.run_agent", side_effect=_capture),
                patch("create_implementation_from_issue.branch_updated_since", return_value=False),
                patch(
                    "create_implementation_from_issue.load_pr_metadata_artifact",
                    return_value=None,
                ),
                patch(
                    "create_implementation_from_issue.skill_file_path",
                    side_effect=lambda name: f".agents/skills/{name}/SKILL.md",
                ),
            ):
                client = MagicMock()
                client.close = MagicMock()
                github = MagicMock()
                github.default_branch = "main"
                github.get_issue.return_value = issue_data
                github.get_pulls.return_value = []
                client.get_repo.return_value = github
                mock_github_cls.return_value = client

                from create_implementation_from_issue import main

                main()
        finally:
            os.unlink(event_path)

        prompt = captured.get("prompt", "")
        self.assertIn("GitHub issue #317", prompt)
        self.assertIn("Dispatchable implementation issue", prompt)
        self.assertIn("enhancement, ready-to-implement", prompt)


if __name__ == "__main__":
    unittest.main()
