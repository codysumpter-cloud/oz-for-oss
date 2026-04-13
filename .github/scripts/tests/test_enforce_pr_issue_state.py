from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from enforce_pr_issue_state import _is_pr_author_org_member, main
from oz_workflows.helpers import ORG_MEMBER_ASSOCIATIONS


class IsOrgMemberAssociationsTest(unittest.TestCase):
    def test_member_association_is_recognized(self) -> None:
        self.assertIn("MEMBER", ORG_MEMBER_ASSOCIATIONS)

    def test_owner_association_is_recognized(self) -> None:
        self.assertIn("OWNER", ORG_MEMBER_ASSOCIATIONS)

    def test_collaborator_association_is_recognized(self) -> None:
        self.assertIn("COLLABORATOR", ORG_MEMBER_ASSOCIATIONS)

    def test_contributor_is_not_recognized(self) -> None:
        self.assertNotIn("CONTRIBUTOR", ORG_MEMBER_ASSOCIATIONS)

    def test_none_is_not_recognized(self) -> None:
        self.assertNotIn("NONE", ORG_MEMBER_ASSOCIATIONS)


class IsPrAuthorOrgMemberTest(unittest.TestCase):
    def test_member_returns_true(self) -> None:
        pr = {"author_association": "MEMBER"}
        self.assertTrue(_is_pr_author_org_member(pr))

    def test_owner_returns_true(self) -> None:
        pr = {"author_association": "OWNER"}
        self.assertTrue(_is_pr_author_org_member(pr))

    def test_contributor_returns_false(self) -> None:
        pr = {"author_association": "CONTRIBUTOR"}
        self.assertFalse(_is_pr_author_org_member(pr))

    def test_none_association_returns_false(self) -> None:
        pr = {"author_association": "NONE"}
        self.assertFalse(_is_pr_author_org_member(pr))

    def test_collaborator_returns_true(self) -> None:
        pr = {"author_association": "COLLABORATOR"}
        self.assertTrue(_is_pr_author_org_member(pr))

    def test_missing_field_returns_false(self) -> None:
        pr: dict[str, str] = {}
        self.assertFalse(_is_pr_author_org_member(pr))

    def test_empty_string_returns_false(self) -> None:
        pr = {"author_association": ""}
        self.assertFalse(_is_pr_author_org_member(pr))

    def test_first_timer_returns_false(self) -> None:
        pr = {"author_association": "FIRST_TIMER"}
        self.assertFalse(_is_pr_author_org_member(pr))

class MainTest(unittest.TestCase):
    def test_markdown_only_pr_queries_ready_issues_with_label_list(self) -> None:
        client = MagicMock()
        client.close = MagicMock()
        github = MagicMock()
        client.get_repo.return_value = github

        pr = MagicMock()
        pr.state = "open"
        pr.author_association = "CONTRIBUTOR"
        pr.title = "Docs only"
        pr.body = ""
        pr.head.ref = "docs-only"
        pr.as_issue.return_value = SimpleNamespace(labels=[])
        pr.get_files.return_value = [SimpleNamespace(filename="README.md")]
        github.get_pull.return_value = pr

        ready_issue = SimpleNamespace(
            pull_request=None,
            number=123,
            title="Ready spec issue",
            body="",
            html_url="https://github.com/owner/repo/issues/123",
            labels=[SimpleNamespace(name="ready-to-spec")],
        )
        github.get_issues.return_value = [ready_issue]

        with (
            patch("enforce_pr_issue_state.require_env", side_effect=["7", "token"]),
            patch("enforce_pr_issue_state.optional_env", return_value=None),
            patch("enforce_pr_issue_state.repo_parts", return_value=("owner", "repo")),
            patch("enforce_pr_issue_state.repo_slug", return_value="owner/repo"),
            patch("enforce_pr_issue_state.workspace", return_value="/tmp/workspace"),
            patch("enforce_pr_issue_state.Auth.Token", return_value="token"),
            patch("enforce_pr_issue_state.Github", return_value=client),
            patch("enforce_pr_issue_state.WorkflowProgressComment"),
            patch("enforce_pr_issue_state.extract_issue_numbers_from_text", return_value=[]),
            patch("enforce_pr_issue_state.build_agent_config", return_value=MagicMock()),
            patch("enforce_pr_issue_state.run_agent", return_value=SimpleNamespace(run_id="run-123")),
            patch(
                "enforce_pr_issue_state.poll_for_artifact",
                return_value={"matched": True, "issue_number": 123},
            ),
            patch("enforce_pr_issue_state.set_output") as mock_set_output,
        ):
            main()

        github.get_issues.assert_called_once_with(state="open", labels=["ready-to-spec"])
        mock_set_output.assert_called_once_with("allow_review", "true")


if __name__ == "__main__":
    unittest.main()
