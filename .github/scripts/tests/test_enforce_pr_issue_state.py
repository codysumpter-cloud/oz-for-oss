from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

from enforce_pr_issue_state import (
    _is_pr_author_org_member,
    _normalize_reviewer_logins,
    main,
)


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


class NormalizeReviewerLoginsTest(unittest.TestCase):
    def test_strips_at_signs_and_deduplicates(self) -> None:
        result = _normalize_reviewer_logins(
            ["@alice", "alice", " bob ", "@@carol"],
            pr_author_login="dave",
        )
        self.assertEqual(result, ["alice", "bob", "carol"])

    def test_caps_to_max_reviewers(self) -> None:
        # The default cap is 3; extras must be dropped in first-seen order.
        result = _normalize_reviewer_logins(
            ["a", "b", "c", "d", "e"],
            pr_author_login="",
        )
        self.assertEqual(result, ["a", "b", "c"])

    def test_removes_pr_author_case_insensitive(self) -> None:
        # GitHub rejects self-review requests, so the PR author must be
        # removed regardless of the casing the agent returns.
        result = _normalize_reviewer_logins(
            ["Alice", "@BOB", "carol"],
            pr_author_login="bob",
        )
        self.assertEqual(result, ["Alice", "carol"])

    def test_drops_non_string_and_empty_entries(self) -> None:
        result = _normalize_reviewer_logins(
            ["", None, 42, "@", "alice"],
            pr_author_login="",
        )
        self.assertEqual(result, ["alice"])

    def test_non_list_returns_empty(self) -> None:
        self.assertEqual(
            _normalize_reviewer_logins(None, pr_author_login=""), []
        )
        self.assertEqual(
            _normalize_reviewer_logins("alice", pr_author_login=""), []
        )

    def test_custom_limit(self) -> None:
        result = _normalize_reviewer_logins(
            ["a", "b", "c"],
            pr_author_login="",
            limit=2,
        )
        self.assertEqual(result, ["a", "b"])


class MainTest(unittest.TestCase):
    def _build_basic_pr(
        self,
        *,
        filename: str = "README.md",
        pr_labels: list[str] | None = None,
        body: str = "",
        author_login: str = "external-contributor",
    ) -> MagicMock:
        pr = MagicMock()
        pr.state = "open"
        pr.author_association = "CONTRIBUTOR"
        pr.title = "Some PR"
        pr.body = body
        pr.head.ref = "feature-branch"
        pr.base.ref = "main"
        pr.user = SimpleNamespace(login=author_login)
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
            patch(
                "enforce_pr_issue_state._run_non_member_pr_review"
            ) as mock_review_gate,
        ):
            main()

        # Markdown-only PRs should bypass the issue-association check and
        # the agent review gate entirely.
        github.get_issues.assert_not_called()
        mock_run_agent.assert_not_called()
        mock_poll_for_artifact.assert_not_called()
        mock_review_gate.assert_not_called()
        progress_instance.start.assert_not_called()
        progress_instance.cleanup.assert_called_once_with()
        progress_instance.complete.assert_not_called()
        mock_set_output.assert_has_calls(
            [call("allow_review", "true"), call("agent_verdict", "")]
        )

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
            patch(
                "enforce_pr_issue_state._run_non_member_pr_review"
            ) as mock_review_gate,
            patch("enforce_pr_issue_state.set_output") as mock_set_output,
        ):
            main()

        pr.edit.assert_not_called()
        mock_review_gate.assert_not_called()
        progress_instance.start.assert_not_called()
        progress_instance.cleanup.assert_called_once_with()
        progress_instance.complete.assert_not_called()
        mock_set_output.assert_has_calls(
            [call("allow_review", "true"), call("agent_verdict", "")]
        )

    def test_explicit_issue_allow_path_runs_review_gate(self) -> None:
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
            patch(
                "enforce_pr_issue_state._run_non_member_pr_review",
                return_value="APPROVE",
            ) as mock_review_gate,
            patch("enforce_pr_issue_state.set_output") as mock_set_output,
        ):
            main()

        mock_review_gate.assert_called_once()
        progress_instance.start.assert_not_called()
        progress_instance.cleanup.assert_called_once_with()
        mock_set_output.assert_has_calls(
            [call("allow_review", "true"), call("agent_verdict", "APPROVE")]
        )

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
            patch(
                "enforce_pr_issue_state._run_non_member_pr_review"
            ) as mock_review_gate,
            patch("enforce_pr_issue_state.set_output") as mock_set_output,
        ):
            main()

        progress_instance.start.assert_called_once()
        progress_instance.complete.assert_called_once()
        progress_instance.cleanup.assert_not_called()
        mock_review_gate.assert_not_called()
        pr.edit.assert_called_once_with(state="closed")
        mock_set_output.assert_has_calls(
            [call("allow_review", "false"), call("agent_verdict", "")]
        )

    def test_agent_matched_allow_path_runs_review_gate(self) -> None:
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
            patch(
                "enforce_pr_issue_state._run_non_member_pr_review",
                return_value="REQUEST_CHANGES",
            ) as mock_review_gate,
            patch("enforce_pr_issue_state.set_output") as mock_set_output,
        ):
            main()

        progress_instance.start.assert_called_once()
        # ``cleanup`` runs before the review gate to drop the association
        # progress comment; the review gate posts its own completion line
        # via ``progress.complete`` inside the helper (mocked out here).
        progress_instance.cleanup.assert_called_once_with()
        mock_review_gate.assert_called_once()
        mock_set_output.assert_has_calls(
            [call("allow_review", "true"), call("agent_verdict", "REQUEST_CHANGES")]
        )


class RunNonMemberPrReviewTest(unittest.TestCase):
    def _build_pr(self, *, author_login: str = "contributor") -> MagicMock:
        pr = MagicMock()
        pr.title = "Fix bug"
        pr.body = "Body"
        pr.head.ref = "feature"
        pr.base.ref = "main"
        pr.user = SimpleNamespace(login=author_login)
        return pr

    def _run(
        self,
        *,
        artifact: dict,
        pr: MagicMock | None = None,
    ) -> tuple[MagicMock, str]:
        from enforce_pr_issue_state import _run_non_member_pr_review

        pr = pr or self._build_pr()
        progress = MagicMock()
        with (
            patch("enforce_pr_issue_state.build_agent_config", return_value=MagicMock()),
            patch(
                "enforce_pr_issue_state.run_agent",
                return_value=SimpleNamespace(run_id="run-xyz"),
            ),
            patch(
                "enforce_pr_issue_state.poll_for_artifact",
                return_value=artifact,
            ),
            patch("enforce_pr_issue_state.workspace", return_value="/tmp/workspace"),
        ):
            verdict = _run_non_member_pr_review(
                MagicMock(),
                pr,
                owner="owner",
                repo="repo",
                pr_number=7,
                changed_files=["src/app.py"],
                progress=progress,
            )
        return pr, verdict

    def test_approve_posts_review_and_requests_reviewers(self) -> None:
        artifact = {
            "verdict": "APPROVE",
            "summary": "Looks good.",
            "recommended_reviewers": ["alice", "@bob", "contributor", "carol", "dave"],
        }
        pr, verdict = self._run(artifact=artifact)
        self.assertEqual(verdict, "APPROVE")
        pr.create_review.assert_called_once()
        kwargs = pr.create_review.call_args.kwargs
        self.assertEqual(kwargs["event"], "APPROVE")
        self.assertIn("Looks good.", kwargs["body"])
        # PR author (``contributor``) must be dropped and list capped at 3.
        pr.create_review_request.assert_called_once_with(
            reviewers=["alice", "bob", "carol"]
        )

    def test_request_changes_does_not_request_reviewers(self) -> None:
        artifact = {
            "verdict": "REQUEST_CHANGES",
            "summary": "Needs work.",
            "recommended_reviewers": ["alice"],
        }
        pr, verdict = self._run(artifact=artifact)
        self.assertEqual(verdict, "REQUEST_CHANGES")
        pr.create_review.assert_called_once()
        self.assertEqual(pr.create_review.call_args.kwargs["event"], "REQUEST_CHANGES")
        pr.create_review_request.assert_not_called()

    def test_approve_with_empty_reviewers_skips_request(self) -> None:
        artifact = {
            "verdict": "APPROVE",
            "summary": "Looks good.",
            "recommended_reviewers": [],
        }
        pr, verdict = self._run(artifact=artifact)
        self.assertEqual(verdict, "APPROVE")
        pr.create_review.assert_called_once()
        pr.create_review_request.assert_not_called()

    def test_invalid_verdict_raises(self) -> None:
        artifact = {
            "verdict": "COMMENT",
            "summary": "x",
            "recommended_reviewers": [],
        }
        with self.assertRaises(RuntimeError):
            self._run(artifact=artifact)

    def test_empty_summary_raises(self) -> None:
        artifact = {
            "verdict": "APPROVE",
            "summary": "   ",
            "recommended_reviewers": [],
        }
        with self.assertRaises(RuntimeError):
            self._run(artifact=artifact)

    def test_request_reviewers_github_failure_is_swallowed(self) -> None:
        from enforce_pr_issue_state import _run_non_member_pr_review
        from github.GithubException import GithubException

        pr = self._build_pr()
        pr.create_review_request.side_effect = GithubException(
            422, {"message": "boom"}, {}
        )
        progress = MagicMock()

        artifact = {
            "verdict": "APPROVE",
            "summary": "Looks good.",
            "recommended_reviewers": ["alice"],
        }
        with (
            patch("enforce_pr_issue_state.build_agent_config", return_value=MagicMock()),
            patch(
                "enforce_pr_issue_state.run_agent",
                return_value=SimpleNamespace(run_id="run-xyz"),
            ),
            patch(
                "enforce_pr_issue_state.poll_for_artifact",
                return_value=artifact,
            ),
            patch("enforce_pr_issue_state.workspace", return_value="/tmp/workspace"),
        ):
            verdict = _run_non_member_pr_review(
                MagicMock(),
                pr,
                owner="owner",
                repo="repo",
                pr_number=7,
                changed_files=["src/app.py"],
                progress=progress,
            )

        # The review itself succeeded and the verdict was returned even
        # though requesting reviewers raised a GithubException.
        self.assertEqual(verdict, "APPROVE")
        pr.create_review.assert_called_once()
        pr.create_review_request.assert_called_once()

    def test_review_creation_failure_propagates(self) -> None:
        from enforce_pr_issue_state import _run_non_member_pr_review
        from github.GithubException import GithubException

        pr = self._build_pr()
        pr.create_review.side_effect = GithubException(500, {"message": "x"}, {})
        progress = MagicMock()

        artifact = {
            "verdict": "APPROVE",
            "summary": "Looks good.",
            "recommended_reviewers": [],
        }
        with (
            patch("enforce_pr_issue_state.build_agent_config", return_value=MagicMock()),
            patch(
                "enforce_pr_issue_state.run_agent",
                return_value=SimpleNamespace(run_id="run-xyz"),
            ),
            patch(
                "enforce_pr_issue_state.poll_for_artifact",
                return_value=artifact,
            ),
            patch("enforce_pr_issue_state.workspace", return_value="/tmp/workspace"),
        ):
            with self.assertRaises(GithubException):
                _run_non_member_pr_review(
                    MagicMock(),
                    pr,
                    owner="owner",
                    repo="repo",
                    pr_number=7,
                    changed_files=["src/app.py"],
                    progress=progress,
                )


if __name__ == "__main__":
    unittest.main()
