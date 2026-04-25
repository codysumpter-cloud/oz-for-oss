from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from enforce_pr_issue_state import _explicit_issue_search_text, _is_pr_author_org_member, main


class IsPrAuthorOrgMemberTest(unittest.TestCase):
    def test_association_table(self) -> None:
        cases = [
            ("MEMBER", True),
            ("OWNER", True),
            ("COLLABORATOR", True),
            ("CONTRIBUTOR", False),
            ("NONE", False),
            ("FIRST_TIMER", False),
            ("", False),
        ]
        for association, expected in cases:
            with self.subTest(association=association):
                self.assertEqual(
                    _is_pr_author_org_member({"author_association": association}),
                    expected,
                )

    def test_missing_field_returns_false(self) -> None:
        self.assertFalse(_is_pr_author_org_member({}))


class ExplicitIssueSearchTextTest(unittest.TestCase):
    def test_combines_title_and_body(self) -> None:
        self.assertEqual(
            _explicit_issue_search_text(
                {
                    "title": "fix: closes #42",
                    "body": "Implements the widget renderer fix.",
                }
            ),
            "fix: closes #42\n\nImplements the widget renderer fix.",
        )

    def test_omits_empty_segments(self) -> None:
        self.assertEqual(
            _explicit_issue_search_text({"title": "fix: closes #42", "body": ""}),
            "fix: closes #42",
        )

class MainTest(unittest.TestCase):
    def _build_basic_pr(
        self,
        *,
        filename: str = "README.md",
        pr_labels: list[str] | None = None,
        body: str = "",
    ) -> MagicMock:
        pr = MagicMock()
        pr.state = "open"
        pr.author_association = "CONTRIBUTOR"
        pr.title = "Some PR"
        pr.body = body
        pr.head.ref = "feature-branch"
        pr.as_issue.return_value = SimpleNamespace(
            labels=[SimpleNamespace(name=name) for name in (pr_labels or [])],
        )
        pr.get_files.return_value = [SimpleNamespace(filename=filename)]
        return pr

    def test_markdown_only_pr_allowed_without_issue_state_check(self) -> None:
        client = MagicMock()
        client.close = MagicMock()
        github = MagicMock()
        client.get_repo.return_value = github

        pr = self._build_basic_pr(filename="README.md")
        pr.title = "Docs only"
        pr.head.ref = "docs-only"
        github.get_pull.return_value = pr

        progress_instance = MagicMock()

        with (
            patch("enforce_pr_issue_state.require_env", side_effect=["7", "token"]),
            patch("enforce_pr_issue_state.optional_env", return_value=None),
            patch("enforce_pr_issue_state.repo_parts", return_value=("owner", "repo")),
            patch("enforce_pr_issue_state.repo_slug", return_value="owner/repo"),
            patch("enforce_pr_issue_state.workspace", return_value="/tmp/workspace"),
            patch("enforce_pr_issue_state.Auth.Token", return_value="token"),
            patch("enforce_pr_issue_state.Github", return_value=client),
            patch(
                "enforce_pr_issue_state.WorkflowProgressComment",
                return_value=progress_instance,
            ),
            patch("enforce_pr_issue_state.extract_issue_numbers_from_text", return_value=[]),
            patch("enforce_pr_issue_state.run_agent") as mock_run_agent,
            patch("enforce_pr_issue_state.poll_for_artifact") as mock_poll_for_artifact,
            patch("enforce_pr_issue_state.set_output") as mock_set_output,
        ):
            main()

        # Markdown-only PRs should bypass the issue-association check
        # entirely: no ready-issue query, no agent run, just allow.
        github.get_issues.assert_not_called()
        mock_run_agent.assert_not_called()
        mock_poll_for_artifact.assert_not_called()
        progress_instance.start.assert_not_called()
        progress_instance.cleanup.assert_called_once_with()
        progress_instance.complete.assert_not_called()
        mock_set_output.assert_called_once_with("allow_review", "true")

    def test_explicit_issue_searches_title_and_body_for_references(self) -> None:
        client = MagicMock()
        client.close = MagicMock()
        github = MagicMock()
        client.get_repo.return_value = github

        pr = self._build_basic_pr(filename="src/app.py", body="Implementation details")
        pr.title = "fix: closes #42"
        github.get_pull.return_value = pr

        explicit_issue = SimpleNamespace(
            pull_request=None,
            number=42,
            title="Ready impl",
            body="",
            html_url="https://github.com/owner/repo/issues/42",
            labels=[SimpleNamespace(name="ready-to-implement")],
        )
        github.get_issue.return_value = explicit_issue

        progress_instance = MagicMock()

        with (
            patch("enforce_pr_issue_state.require_env", side_effect=["7", "token"]),
            patch("enforce_pr_issue_state.optional_env", return_value=None),
            patch("enforce_pr_issue_state.repo_parts", return_value=("owner", "repo")),
            patch("enforce_pr_issue_state.repo_slug", return_value="owner/repo"),
            patch("enforce_pr_issue_state.workspace", return_value="/tmp/workspace"),
            patch("enforce_pr_issue_state.Auth.Token", return_value="token"),
            patch("enforce_pr_issue_state.Github", return_value=client),
            patch(
                "enforce_pr_issue_state.WorkflowProgressComment",
                return_value=progress_instance,
            ),
            patch(
                "enforce_pr_issue_state.extract_issue_numbers_from_text",
                return_value=[42],
            ) as mock_extract_issue_numbers,
            patch("enforce_pr_issue_state.set_output") as mock_set_output,
        ):
            main()

        mock_extract_issue_numbers.assert_called_once_with(
            "owner",
            "repo",
            "fix: closes #42\n\nImplementation details",
        )
        progress_instance.start.assert_not_called()
        progress_instance.cleanup.assert_called_once_with()
        progress_instance.complete.assert_not_called()
        mock_set_output.assert_called_once_with("allow_review", "true")

    def test_markdown_only_pr_with_explicit_unready_issue_is_allowed(self) -> None:
        client = MagicMock()
        client.close = MagicMock()
        github = MagicMock()
        client.get_repo.return_value = github

        pr = self._build_basic_pr(filename="README.md", body="Closes #42")
        github.get_pull.return_value = pr

        # An associated issue that does NOT have ``ready-to-spec`` would
        # previously close the PR. It should now be ignored for
        # markdown-only PRs.
        explicit_issue = SimpleNamespace(
            pull_request=None,
            number=42,
            title="Not ready",
            body="",
            html_url="https://github.com/owner/repo/issues/42",
            labels=[SimpleNamespace(name="bug")],
        )
        github.get_issue.return_value = explicit_issue

        progress_instance = MagicMock()

        with (
            patch("enforce_pr_issue_state.require_env", side_effect=["7", "token"]),
            patch("enforce_pr_issue_state.optional_env", return_value=None),
            patch("enforce_pr_issue_state.repo_parts", return_value=("owner", "repo")),
            patch("enforce_pr_issue_state.repo_slug", return_value="owner/repo"),
            patch("enforce_pr_issue_state.workspace", return_value="/tmp/workspace"),
            patch("enforce_pr_issue_state.Auth.Token", return_value="token"),
            patch("enforce_pr_issue_state.Github", return_value=client),
            patch(
                "enforce_pr_issue_state.WorkflowProgressComment",
                return_value=progress_instance,
            ),
            patch(
                "enforce_pr_issue_state.extract_issue_numbers_from_text",
                return_value=[42],
            ),
            patch("enforce_pr_issue_state.set_output") as mock_set_output,
        ):
            main()

        pr.edit.assert_not_called()
        progress_instance.start.assert_not_called()
        progress_instance.cleanup.assert_called_once_with()
        progress_instance.complete.assert_not_called()
        mock_set_output.assert_called_once_with("allow_review", "true")

    def test_explicit_issue_allow_path_does_not_post_start_line(self) -> None:
        client = MagicMock()
        client.close = MagicMock()
        github = MagicMock()
        client.get_repo.return_value = github

        pr = self._build_basic_pr(filename="src/app.py", body="Closes #42")
        github.get_pull.return_value = pr

        explicit_issue = SimpleNamespace(
            pull_request=None,
            number=42,
            title="Ready impl",
            body="",
            html_url="https://github.com/owner/repo/issues/42",
            labels=[SimpleNamespace(name="ready-to-implement")],
        )
        github.get_issue.return_value = explicit_issue

        progress_instance = MagicMock()

        with (
            patch("enforce_pr_issue_state.require_env", side_effect=["7", "token"]),
            patch("enforce_pr_issue_state.optional_env", return_value=None),
            patch("enforce_pr_issue_state.repo_parts", return_value=("owner", "repo")),
            patch("enforce_pr_issue_state.repo_slug", return_value="owner/repo"),
            patch("enforce_pr_issue_state.workspace", return_value="/tmp/workspace"),
            patch("enforce_pr_issue_state.Auth.Token", return_value="token"),
            patch("enforce_pr_issue_state.Github", return_value=client),
            patch(
                "enforce_pr_issue_state.WorkflowProgressComment",
                return_value=progress_instance,
            ),
            patch(
                "enforce_pr_issue_state.extract_issue_numbers_from_text",
                return_value=[42],
            ),
            patch("enforce_pr_issue_state.set_output") as mock_set_output,
        ):
            main()

        progress_instance.start.assert_not_called()
        progress_instance.cleanup.assert_called_once_with()
        progress_instance.complete.assert_not_called()
        mock_set_output.assert_called_once_with("allow_review", "true")

    def test_explicit_issue_close_path_posts_start_and_complete(self) -> None:
        client = MagicMock()
        client.close = MagicMock()
        github = MagicMock()
        client.get_repo.return_value = github

        pr = self._build_basic_pr(filename="src/app.py", body="Closes #42")
        github.get_pull.return_value = pr

        explicit_issue = SimpleNamespace(
            pull_request=None,
            number=42,
            title="Not ready",
            body="",
            html_url="https://github.com/owner/repo/issues/42",
            labels=[SimpleNamespace(name="bug")],
        )
        github.get_issue.return_value = explicit_issue

        progress_instance = MagicMock()

        with (
            patch("enforce_pr_issue_state.require_env", side_effect=["7", "token"]),
            patch("enforce_pr_issue_state.optional_env", return_value=None),
            patch("enforce_pr_issue_state.repo_parts", return_value=("owner", "repo")),
            patch("enforce_pr_issue_state.repo_slug", return_value="owner/repo"),
            patch("enforce_pr_issue_state.workspace", return_value="/tmp/workspace"),
            patch("enforce_pr_issue_state.Auth.Token", return_value="token"),
            patch("enforce_pr_issue_state.Github", return_value=client),
            patch(
                "enforce_pr_issue_state.WorkflowProgressComment",
                return_value=progress_instance,
            ),
            patch(
                "enforce_pr_issue_state.extract_issue_numbers_from_text",
                return_value=[42],
            ),
            patch("enforce_pr_issue_state.set_output") as mock_set_output,
        ):
            main()

        progress_instance.start.assert_called_once()
        progress_instance.complete.assert_called_once()
        progress_instance.cleanup.assert_not_called()
        pr.edit.assert_called_once_with(state="closed")
        mock_set_output.assert_called_once_with("allow_review", "false")

    def test_agent_matched_allow_path_posts_start_before_agent_run(self) -> None:
        client = MagicMock()
        client.close = MagicMock()
        github = MagicMock()
        client.get_repo.return_value = github

        pr = self._build_basic_pr(filename="src/app.py")
        github.get_pull.return_value = pr

        ready_issue = SimpleNamespace(
            pull_request=None,
            number=99,
            title="Ready impl issue",
            body="",
            html_url="https://github.com/owner/repo/issues/99",
            labels=[SimpleNamespace(name="ready-to-implement")],
        )
        github.get_issues.return_value = [ready_issue]

        progress_instance = MagicMock()

        with (
            patch("enforce_pr_issue_state.require_env", side_effect=["7", "token"]),
            patch("enforce_pr_issue_state.optional_env", return_value=None),
            patch("enforce_pr_issue_state.repo_parts", return_value=("owner", "repo")),
            patch("enforce_pr_issue_state.repo_slug", return_value="owner/repo"),
            patch("enforce_pr_issue_state.workspace", return_value="/tmp/workspace"),
            patch("enforce_pr_issue_state.Auth.Token", return_value="token"),
            patch("enforce_pr_issue_state.Github", return_value=client),
            patch(
                "enforce_pr_issue_state.WorkflowProgressComment",
                return_value=progress_instance,
            ),
            patch(
                "enforce_pr_issue_state.extract_issue_numbers_from_text",
                return_value=[],
            ),
            patch("enforce_pr_issue_state.build_agent_config", return_value=MagicMock()),
            patch(
                "enforce_pr_issue_state.run_agent",
                return_value=SimpleNamespace(run_id="run-123"),
            ),
            patch(
                "enforce_pr_issue_state.poll_for_artifact",
                return_value={"matched": True, "issue_number": 99},
            ),
            patch("enforce_pr_issue_state.set_output") as mock_set_output,
        ):
            main()

        progress_instance.start.assert_called_once()
        progress_instance.cleanup.assert_called_once_with()
        progress_instance.complete.assert_not_called()
        mock_set_output.assert_called_once_with("allow_review", "true")


if __name__ == "__main__":
    unittest.main()
