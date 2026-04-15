from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

from remove_stale_issue_labels_on_plan_approved import main, STALE_LABELS


def _make_pr(*, state: str = "open", body: str = "", head_ref: str = "oz-agent/implement-issue-42") -> MagicMock:
    pr = MagicMock()
    pr.state = state
    pr.body = body
    pr.head.ref = head_ref
    pr.get_files.return_value = [SimpleNamespace(filename="src/main.py")]
    return pr


def _make_issue(labels: list[str]) -> MagicMock:
    issue = MagicMock()
    issue.labels = [SimpleNamespace(name=name) for name in labels]
    return issue


class StaleLabelsConstantTest(unittest.TestCase):
    def test_contains_ready_to_spec(self) -> None:
        self.assertIn("ready-to-spec", STALE_LABELS)

    def test_does_not_contain_ready_to_implement(self) -> None:
        self.assertNotIn("ready-to-implement", STALE_LABELS)


class MainTest(unittest.TestCase):
    def _run_main(
        self,
        *,
        pr_state: str = "open",
        pr_body: str = "",
        head_ref: str = "oz-agent/implement-issue-42",
        issue_labels: list[str] | None = None,
        resolved_issue_number: int | None = 42,
    ) -> tuple[MagicMock, MagicMock, MagicMock]:
        client = MagicMock()
        client.close = MagicMock()
        github = MagicMock()
        client.get_repo.return_value = github

        pr = _make_pr(state=pr_state, body=pr_body, head_ref=head_ref)
        github.get_pull.return_value = pr

        issue = _make_issue(issue_labels or [])
        github.get_issue.return_value = issue

        with (
            patch("remove_stale_issue_labels_on_plan_approved.require_env", side_effect=["10", "token"]),
            patch("remove_stale_issue_labels_on_plan_approved.repo_parts", return_value=("owner", "repo")),
            patch("remove_stale_issue_labels_on_plan_approved.repo_slug", return_value="owner/repo"),
            patch("remove_stale_issue_labels_on_plan_approved.Auth.Token", return_value="token"),
            patch("remove_stale_issue_labels_on_plan_approved.Github", return_value=client),
            patch(
                "remove_stale_issue_labels_on_plan_approved.resolve_issue_number_for_pr",
                return_value=resolved_issue_number,
            ),
        ):
            main()

        return github, pr, issue

    def test_removes_ready_to_spec_label(self) -> None:
        github, _, issue = self._run_main(issue_labels=["ready-to-spec", "triaged"])
        issue.remove_from_labels.assert_called_once_with("ready-to-spec")

    def test_does_not_remove_ready_to_implement_label(self) -> None:
        github, _, issue = self._run_main(issue_labels=["ready-to-implement", "triaged"])
        issue.remove_from_labels.assert_not_called()

    def test_removes_only_ready_to_spec_when_both_present(self) -> None:
        github, _, issue = self._run_main(
            issue_labels=["ready-to-spec", "ready-to-implement", "triaged"]
        )
        issue.remove_from_labels.assert_called_once_with("ready-to-spec")

    def test_no_removal_when_no_stale_labels(self) -> None:
        github, _, issue = self._run_main(issue_labels=["triaged", "enhancement"])
        issue.remove_from_labels.assert_not_called()

    def test_skips_closed_pr(self) -> None:
        github, pr, _ = self._run_main(pr_state="closed")
        pr.get_files.assert_not_called()

    def test_skips_when_no_associated_issue(self) -> None:
        github, _, issue = self._run_main(resolved_issue_number=None)
        github.get_issue.assert_not_called()

    def test_resolves_issue_from_branch_name(self) -> None:
        """Verifies the PR's changed files are passed to the resolver."""
        github, pr, issue = self._run_main(
            head_ref="oz-agent/spec-issue-99",
            issue_labels=["ready-to-spec"],
        )
        issue.remove_from_labels.assert_called_once_with("ready-to-spec")


if __name__ == "__main__":
    unittest.main()
