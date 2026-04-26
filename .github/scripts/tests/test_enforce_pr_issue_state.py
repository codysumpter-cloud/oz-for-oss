from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from enforce_pr_issue_state import (
    _is_pr_author_org_member,
    build_issue_association_prompt,
    main,
)


def _write_config(repo_root: Path, text: str) -> Path:
    path = repo_root / ".github" / "oz" / "config.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


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


class MainTest(unittest.TestCase):
    def _build_basic_pr(
        self,
        *,
        filename: str = "README.md",
        body: str = "",
    ) -> MagicMock:
        pr = MagicMock()
        pr.state = "open"
        pr.author_association = "CONTRIBUTOR"
        pr.title = "Some PR"
        pr.body = body
        pr.head.ref = "feature-branch"
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
            patch(
                "enforce_pr_issue_state.resolve_pr_association",
                return_value={"same_repo_issue_numbers": []},
            ),
            patch("enforce_pr_issue_state.run_agent") as mock_run_agent,
            patch("enforce_pr_issue_state.poll_for_artifact") as mock_poll_for_artifact,
            patch("enforce_pr_issue_state.set_output") as mock_set_output,
        ):
            main()

        github.get_issues.assert_not_called()
        mock_run_agent.assert_not_called()
        mock_poll_for_artifact.assert_not_called()
        progress_instance.start.assert_not_called()
        progress_instance.cleanup.assert_called_once_with()
        progress_instance.complete.assert_not_called()
        mock_set_output.assert_called_once_with("allow_review", "true")

    def test_markdown_only_pr_with_associated_issue_is_allowed(self) -> None:
        client = MagicMock()
        client.close = MagicMock()
        github = MagicMock()
        client.get_repo.return_value = github

        pr = self._build_basic_pr(filename="README.md", body="Closes #42")
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
            patch(
                "enforce_pr_issue_state.resolve_pr_association",
                return_value={"same_repo_issue_numbers": [42]},
            ),
            patch("enforce_pr_issue_state.set_output") as mock_set_output,
        ):
            main()

        github.get_issue.assert_not_called()
        pr.edit.assert_not_called()
        progress_instance.start.assert_not_called()
        progress_instance.cleanup.assert_called_once_with()
        progress_instance.complete.assert_not_called()
        mock_set_output.assert_called_once_with("allow_review", "true")

    def test_associated_ready_issue_allow_path_does_not_post_start_line(self) -> None:
        client = MagicMock()
        client.close = MagicMock()
        github = MagicMock()
        client.get_repo.return_value = github

        pr = self._build_basic_pr(filename="src/app.py", body="Closes #42")
        github.get_pull.return_value = pr
        github.get_issue.return_value = SimpleNamespace(
            pull_request=None,
            number=42,
            title="Ready impl",
            body="",
            html_url="https://github.com/owner/repo/issues/42",
            labels=[SimpleNamespace(name="ready-to-implement")],
        )

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
                "enforce_pr_issue_state.resolve_pr_association",
                return_value={"same_repo_issue_numbers": [42]},
            ),
            patch("enforce_pr_issue_state.set_output") as mock_set_output,
        ):
            main()

        progress_instance.start.assert_not_called()
        progress_instance.cleanup.assert_called_once_with()
        progress_instance.complete.assert_not_called()
        pr.edit.assert_not_called()
        mock_set_output.assert_called_once_with("allow_review", "true")

    def test_associated_unready_issue_close_path_posts_start_and_complete(self) -> None:
        client = MagicMock()
        client.close = MagicMock()
        github = MagicMock()
        client.get_repo.return_value = github

        pr = self._build_basic_pr(filename="src/app.py", body="Closes #42")
        github.get_pull.return_value = pr
        github.get_issue.return_value = SimpleNamespace(
            pull_request=None,
            number=42,
            title="Not ready",
            body="",
            html_url="https://github.com/owner/repo/issues/42",
            labels=[SimpleNamespace(name="bug")],
        )

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
                "enforce_pr_issue_state.resolve_pr_association",
                return_value={"same_repo_issue_numbers": [42]},
            ),
            patch("enforce_pr_issue_state.set_output") as mock_set_output,
        ):
            main()

        progress_instance.start.assert_called_once()
        progress_instance.complete.assert_called_once()
        progress_instance.cleanup.assert_not_called()
        pr.edit.assert_called_once_with(state="closed")
        mock_set_output.assert_called_once_with("allow_review", "false")

    def test_associated_unready_issue_uses_configured_close_template(self) -> None:
        with TemporaryDirectory() as tempdir:
            _write_config(
                Path(tempdir),
                (
                    "version: 1\n"
                    "workflow_comments:\n"
                    "  enforce-pr-issue-state:\n"
                    "    close_explicit_issue_not_ready: |-\n"
                    "      Custom close for ${issue_refs} requiring ${required_label}.\n"
                ),
            )

            client = MagicMock()
            client.close = MagicMock()
            github = MagicMock()
            client.get_repo.return_value = github

            pr = self._build_basic_pr(filename="src/app.py", body="Closes #42")
            github.get_pull.return_value = pr
            github.get_issue.return_value = SimpleNamespace(
                pull_request=None,
                number=42,
                title="Not ready",
                body="",
                html_url="https://github.com/owner/repo/issues/42",
                labels=[SimpleNamespace(name="bug")],
            )

            progress_instance = MagicMock()

            with (
                patch.dict(os.environ, {"GITHUB_WORKSPACE": tempdir}, clear=False),
                patch("enforce_pr_issue_state.require_env", side_effect=["7", "token"]),
                patch("enforce_pr_issue_state.optional_env", return_value=None),
                patch("enforce_pr_issue_state.repo_parts", return_value=("owner", "repo")),
                patch("enforce_pr_issue_state.repo_slug", return_value="owner/repo"),
                patch("enforce_pr_issue_state.workspace", return_value=tempdir),
                patch("enforce_pr_issue_state.Auth.Token", return_value="token"),
                patch("enforce_pr_issue_state.Github", return_value=client),
                patch(
                    "enforce_pr_issue_state.WorkflowProgressComment",
                    return_value=progress_instance,
                ),
                patch(
                    "enforce_pr_issue_state.resolve_pr_association",
                    return_value={"same_repo_issue_numbers": [42]},
                ),
                patch("enforce_pr_issue_state.set_output"),
            ):
                main()

            progress_instance.complete.assert_called_once_with(
                "Custom close for #42 requiring ready-to-implement."
            )

    def test_any_ready_associated_issue_allows_pr(self) -> None:
        client = MagicMock()
        client.close = MagicMock()
        github = MagicMock()
        client.get_repo.return_value = github

        pr = self._build_basic_pr(filename="src/app.py", body="See linked issues")
        github.get_pull.return_value = pr
        github.get_issue.side_effect = [
            SimpleNamespace(
                pull_request=None,
                number=41,
                title="Not ready",
                body="",
                html_url="https://github.com/owner/repo/issues/41",
                labels=[SimpleNamespace(name="bug")],
            ),
            SimpleNamespace(
                pull_request=None,
                number=42,
                title="Ready impl",
                body="",
                html_url="https://github.com/owner/repo/issues/42",
                labels=[SimpleNamespace(name="ready-to-implement")],
            ),
        ]

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
                "enforce_pr_issue_state.resolve_pr_association",
                return_value={"same_repo_issue_numbers": [41, 42]},
            ),
            patch("enforce_pr_issue_state.set_output") as mock_set_output,
        ):
            main()

        progress_instance.start.assert_not_called()
        progress_instance.cleanup.assert_called_once_with()
        progress_instance.complete.assert_not_called()
        pr.edit.assert_not_called()
        mock_set_output.assert_called_once_with("allow_review", "true")

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
                "enforce_pr_issue_state.resolve_pr_association",
                return_value={"same_repo_issue_numbers": []},
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

    def test_agent_no_match_uses_configured_close_template(self) -> None:
        with TemporaryDirectory() as tempdir:
            _write_config(
                Path(tempdir),
                (
                    "version: 1\n"
                    "workflow_comments:\n"
                    "  enforce-pr-issue-state:\n"
                    "    close_no_matching_ready_issue: |-\n"
                    "      No ready issue matched this ${change_kind} PR.\n"
                    "      Why: ${association_rationale}\n"
                ),
            )

            client = MagicMock()
            client.close = MagicMock()
            github = MagicMock()
            client.get_repo.return_value = github

            pr = self._build_basic_pr(filename="src/app.py")
            github.get_pull.return_value = pr
            github.get_issues.return_value = [
                SimpleNamespace(
                    pull_request=None,
                    number=99,
                    title="Ready impl issue",
                    body="",
                    html_url="https://github.com/owner/repo/issues/99",
                    labels=[SimpleNamespace(name="ready-to-implement")],
                )
            ]

            progress_instance = MagicMock()

            with (
                patch.dict(os.environ, {"GITHUB_WORKSPACE": tempdir}, clear=False),
                patch("enforce_pr_issue_state.require_env", side_effect=["7", "token"]),
                patch("enforce_pr_issue_state.optional_env", return_value=None),
                patch("enforce_pr_issue_state.repo_parts", return_value=("owner", "repo")),
                patch("enforce_pr_issue_state.repo_slug", return_value="owner/repo"),
                patch("enforce_pr_issue_state.workspace", return_value=tempdir),
                patch("enforce_pr_issue_state.Auth.Token", return_value="token"),
                patch("enforce_pr_issue_state.Github", return_value=client),
                patch(
                    "enforce_pr_issue_state.WorkflowProgressComment",
                    return_value=progress_instance,
                ),
                patch(
                    "enforce_pr_issue_state.resolve_pr_association",
                    return_value={"same_repo_issue_numbers": []},
                ),
                patch("enforce_pr_issue_state.build_agent_config", return_value=MagicMock()),
                patch(
                    "enforce_pr_issue_state.run_agent",
                    return_value=SimpleNamespace(run_id="run-123"),
                ),
                patch(
                    "enforce_pr_issue_state.poll_for_artifact",
                    return_value={
                        "matched": False,
                        "issue_number": None,
                        "rationale": "Changed files do not line up with any ready issue.",
                    },
                ),
                patch("enforce_pr_issue_state.set_output"),
            ):
                main()

            progress_instance.complete.assert_called_once_with(
                "No ready issue matched this implementation PR.\nWhy: Changed files do not line up with any ready issue."
            )


class BuildIssueAssociationPromptTest(unittest.TestCase):
    def test_includes_security_rules_for_untrusted_pr_and_issue_content(self) -> None:
        prompt = build_issue_association_prompt(
            owner="owner",
            repo="repo",
            pr_number=42,
            pr_title="IGNORE_PREVIOUS_INSTRUCTIONS",
            pr_body="malicious body",
            head_branch="feature",
            change_kind="implementation",
            required_label="ready-to-implement",
            changed_files=["src/app.py"],
            candidate_issues=[
                {"number": 7, "title": "Issue", "body": "malicious issue body"}
            ],
            contribution_docs_url="https://example.test/docs",
        )
        self.assertIn("Security Rules:", prompt)
        self.assertIn("PR title, PR body, and Candidate Ready Issues JSON", prompt)
        self.assertIn("required JSON output shape", prompt)
        self.assertIn("IGNORE_PREVIOUS_INSTRUCTIONS", prompt)
        self.assertIn("malicious issue body", prompt)


if __name__ == "__main__":
    unittest.main()
