from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from remove_stale_issue_labels_on_plan_approved import main


class MainTest(unittest.TestCase):
    def test_closed_pr_is_ignored(self) -> None:
        client = MagicMock()
        client.close = MagicMock()
        github = MagicMock()
        client.get_repo.return_value = github

        pr = MagicMock()
        pr.state = "closed"
        github.get_pull.return_value = pr

        with (
            patch("remove_stale_issue_labels_on_plan_approved.require_env", side_effect=["7", "token"]),
            patch("remove_stale_issue_labels_on_plan_approved.repo_parts", return_value=("owner", "repo")),
            patch("remove_stale_issue_labels_on_plan_approved.repo_slug", return_value="owner/repo"),
            patch("remove_stale_issue_labels_on_plan_approved.Auth.Token", return_value="token"),
            patch("remove_stale_issue_labels_on_plan_approved.Github", return_value=client),
        ):
            main()

        pr.get_files.assert_not_called()
        github.get_issue.assert_not_called()

    def test_no_primary_issue_means_no_label_mutation(self) -> None:
        client = MagicMock()
        client.close = MagicMock()
        github = MagicMock()
        client.get_repo.return_value = github

        pr = MagicMock()
        pr.state = "open"
        pr.get_files.return_value = [SimpleNamespace(filename="specs/GH337/product.md")]
        github.get_pull.return_value = pr

        with (
            patch("remove_stale_issue_labels_on_plan_approved.require_env", side_effect=["7", "token"]),
            patch("remove_stale_issue_labels_on_plan_approved.repo_parts", return_value=("owner", "repo")),
            patch("remove_stale_issue_labels_on_plan_approved.repo_slug", return_value="owner/repo"),
            patch("remove_stale_issue_labels_on_plan_approved.Auth.Token", return_value="token"),
            patch("remove_stale_issue_labels_on_plan_approved.Github", return_value=client),
            patch(
                "remove_stale_issue_labels_on_plan_approved.resolve_pr_association",
                return_value={"primary_issue_number": None, "same_repo_issue_numbers": [337, 323], "ambiguous": True},
            ),
        ):
            main()

        github.get_issue.assert_not_called()

    def test_removes_ready_to_spec_from_primary_issue_only(self) -> None:
        client = MagicMock()
        client.close = MagicMock()
        github = MagicMock()
        client.get_repo.return_value = github

        pr = MagicMock()
        pr.state = "open"
        pr.get_files.return_value = [SimpleNamespace(filename="specs/GH337/product.md")]
        github.get_pull.return_value = pr

        issue = MagicMock()
        issue.labels = [SimpleNamespace(name="ready-to-spec"), SimpleNamespace(name="bug")]
        github.get_issue.return_value = issue

        with (
            patch("remove_stale_issue_labels_on_plan_approved.require_env", side_effect=["7", "token"]),
            patch("remove_stale_issue_labels_on_plan_approved.repo_parts", return_value=("owner", "repo")),
            patch("remove_stale_issue_labels_on_plan_approved.repo_slug", return_value="owner/repo"),
            patch("remove_stale_issue_labels_on_plan_approved.Auth.Token", return_value="token"),
            patch("remove_stale_issue_labels_on_plan_approved.Github", return_value=client),
            patch(
                "remove_stale_issue_labels_on_plan_approved.resolve_pr_association",
                return_value={"primary_issue_number": 337, "same_repo_issue_numbers": [337, 323], "ambiguous": False},
            ),
        ):
            main()

        github.get_issue.assert_called_once_with(337)
        issue.remove_from_labels.assert_called_once_with("ready-to-spec")


if __name__ == "__main__":
    unittest.main()
