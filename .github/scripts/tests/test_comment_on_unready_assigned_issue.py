from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from comment_on_unready_assigned_issue import (
    DEFAULT_ASSIGNEE_LOGIN,
    main,
    resolve_assignee_login,
)


def _write_config(repo_root: Path, text: str) -> Path:
    path = repo_root / ".github" / "oz" / "config.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class ResolveAssigneeLoginTest(unittest.TestCase):
    """Tests for resolve_assignee_login, which must tolerate null/missing values."""

    def test_assignee_shapes(self) -> None:
        # GitHub webhook payloads can set "assignee" to null (e.g. on an
        # unassignment event). That and other shapes must not raise
        # AttributeError and should fall back to ``DEFAULT_ASSIGNEE_LOGIN``
        # except when a concrete login is present.
        cases = [
            ("login_present", {"assignee": {"login": "alice"}}, "alice"),
            ("missing_key", {}, DEFAULT_ASSIGNEE_LOGIN),
            ("assignee_none", {"assignee": None}, DEFAULT_ASSIGNEE_LOGIN),
            ("no_login_key", {"assignee": {}}, DEFAULT_ASSIGNEE_LOGIN),
            (
                "empty_login_string",
                {"assignee": {"login": ""}},
                DEFAULT_ASSIGNEE_LOGIN,
            ),
        ]
        for label, event, expected in cases:
            with self.subTest(label=label):
                self.assertEqual(resolve_assignee_login(event), expected)


class MainTest(unittest.TestCase):
    def test_main_uses_configured_comment_templates(self) -> None:
        with TemporaryDirectory() as tempdir:
            _write_config(
                Path(tempdir),
                (
                    "version: 1\n"
                    "workflow_comments:\n"
                    "  comment-on-unready-assigned-issue:\n"
                    "    start: Custom assignment check.\n"
                    "    complete: Custom unready assignment notice.\n"
                ),
            )

            client = MagicMock()
            client.close = MagicMock()
            github = MagicMock()
            issue = MagicMock()
            client.get_repo.return_value = github
            github.get_issue.return_value = issue
            progress_instance = MagicMock()

            with (
                patch.dict(os.environ, {"GITHUB_WORKSPACE": tempdir}, clear=False),
                patch(
                    "comment_on_unready_assigned_issue.load_event",
                    return_value={
                        "issue": {"number": 42},
                        "assignee": {"login": "alice"},
                    },
                ),
                patch("comment_on_unready_assigned_issue.repo_parts", return_value=("owner", "repo")),
                patch("comment_on_unready_assigned_issue.repo_slug", return_value="owner/repo"),
                patch("comment_on_unready_assigned_issue.require_env", return_value="token"),
                patch("comment_on_unready_assigned_issue.Auth.Token", return_value="token"),
                patch("comment_on_unready_assigned_issue.Github", return_value=client),
                patch(
                    "comment_on_unready_assigned_issue.WorkflowProgressComment",
                    return_value=progress_instance,
                ),
            ):
                main()

            progress_instance.start.assert_called_once_with("Custom assignment check.")
            progress_instance.complete.assert_called_once_with(
                "Custom unready assignment notice."
            )
            issue.remove_from_assignees.assert_called_once_with("alice")


if __name__ == "__main__":
    unittest.main()
