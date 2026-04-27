from __future__ import annotations

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def _make_pr(*, number: int = 10, head_ref: str = "oz-agent/spec-issue-42") -> MagicMock:
    pr = MagicMock()
    pr.number = number
    pr.title = "spec: add retry logic"
    pr.body = "Closes #42\n\nSpec for retry logic."
    pr.head = SimpleNamespace(ref=head_ref)
    pr.base = SimpleNamespace(ref="main")
    return pr


def _base_patches(tmp_path: str = "/tmp/workspace"):
    """Common patches shared across respond-to-pr-comment tests."""
    spec_context = {
        "issue_number": 42,
        "spec_context_source": "approved-pr",
        "selected_spec_pr": {"number": 10, "url": "https://example.test/pr/10"},
        "spec_entries": [{"path": "specs/GH42/product.md", "content": "Product spec"}],
        "changed_files": ["specs/GH42/product.md"],
        "pr_files": [],
    }
    run = SimpleNamespace(
        run_id="run-xyz",
        created_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
    )
    return spec_context, run


class RunImplementationPrRefreshTest(unittest.TestCase):
    """Tests for _run_implementation's PR title/body refresh behavior.

    The bug: when the agent pushed implementation commits onto a PR that
    previously only contained spec changes, the PR description was never
    updated and became stale. The fix expects the agent to upload
    pr-metadata.json when its changes materially change the PR's scope,
    and the workflow updates the PR from that metadata.
    """

    def _run(
        self,
        *,
        branch_updated: bool,
        pr_metadata: dict | None,
        resolved_review_comments: list | None = None,
    ) -> tuple[MagicMock, MagicMock]:
        from respond_to_pr_comment import _run_implementation

        client = MagicMock()
        github = MagicMock()
        pr = _make_pr()
        spec_context, run = _base_patches()

        with (
            patch("respond_to_pr_comment.workspace", return_value="/tmp/workspace"),
            patch(
                "respond_to_pr_comment.resolve_spec_context_for_pr",
                return_value=spec_context,
            ),
            patch("respond_to_pr_comment.WorkflowProgressComment") as progress_cls,
            patch("respond_to_pr_comment.resolve_coauthor_line", return_value=""),
            patch(
                "respond_to_pr_comment.build_agent_config",
                return_value=MagicMock(),
            ),
            patch("respond_to_pr_comment.run_agent", return_value=run),
            patch(
                "respond_to_pr_comment.branch_updated_since",
                return_value=branch_updated,
            ),
            patch(
                "respond_to_pr_comment.try_load_pr_metadata_artifact",
                return_value=pr_metadata,
            ) as mock_load_metadata,
            patch(
                "respond_to_pr_comment.try_load_resolved_review_comments_artifact",
                return_value=(resolved_review_comments or []),
            ),
            patch(
                "respond_to_pr_comment.post_resolved_review_comment_replies",
            ),
        ):
            progress_instance = MagicMock()
            progress_cls.return_value = progress_instance
            _run_implementation(
                client,
                github,
                "owner",
                "repo",
                pr,
                event={
                    "comment": {
                        "user": {"login": "alice"},
                        "body": "Please implement this spec",
                    },
                    "sender": {"login": "alice"},
                },
                trigger_comment_id=9001,
                trigger_kind="conversation",
                requester="alice",
            )
            return pr, mock_load_metadata

    def test_updates_pr_title_and_body_when_metadata_present(self) -> None:
        metadata = {
            "branch_name": "oz-agent/spec-issue-42",
            "pr_title": "feat: implement retry logic on top of spec",
            "pr_summary": (
                "Closes #42\n\n## Summary\nAdded retry logic implementation "
                "on top of the existing spec.\n\n## Validation\nUnit tests pass."
            ),
        }
        pr, mock_load_metadata = self._run(
            branch_updated=True,
            pr_metadata=metadata,
        )
        pr.edit.assert_called_once_with(
            title=metadata["pr_title"],
            body=metadata["pr_summary"],
        )
        mock_load_metadata.assert_called_once()

    def test_leaves_pr_description_untouched_when_metadata_absent(self) -> None:
        # Agent pushed a minor tweak and did not upload pr-metadata.json.
        # The workflow must leave the PR title and body alone so small
        # fix-ups don't churn the existing description.
        pr, mock_load_metadata = self._run(
            branch_updated=True,
            pr_metadata=None,
        )
        pr.edit.assert_not_called()
        mock_load_metadata.assert_called_once()

    def test_does_not_load_metadata_when_branch_not_updated(self) -> None:
        # The agent didn't push any changes, so there's nothing to reflect
        # in a refreshed description and we should not attempt to load the
        # artifact at all.
        pr, mock_load_metadata = self._run(
            branch_updated=False,
            pr_metadata=None,
        )
        pr.edit.assert_not_called()
        mock_load_metadata.assert_not_called()

    def test_raises_when_metadata_branch_does_not_match_head_branch(self) -> None:
        # Guard against the agent uploading pr-metadata.json for the
        # wrong branch. If branch_name doesn't match the PR's head ref,
        # something is off -- refuse to refresh the PR title/body rather
        # than overwriting it with content that may not describe what the
        # head branch actually contains.
        metadata = {
            "branch_name": "oz-agent/some-other-branch",
            "pr_title": "feat: implement retry logic on top of spec",
            "pr_summary": "Closes #42\n\n## Summary\nMismatched branch.",
        }
        with self.assertRaises(RuntimeError) as ctx:
            self._run(
                branch_updated=True,
                pr_metadata=metadata,
            )
        self.assertIn("branch_name", str(ctx.exception))
        self.assertIn("oz-agent/some-other-branch", str(ctx.exception))
        self.assertIn("oz-agent/spec-issue-42", str(ctx.exception))



class MainTrustGateTest(unittest.TestCase):
    """Verify ``main`` resolves commenter trust before the agent runs.

    The bug (issue #311): the prompt asked the agent to infer trust from
    the presence of the triggering comment in ``fetch_github_context.py``
    output. Any missing output (script path issue, transient API failure,
    pagination edge case, truncation, ...) looked identical to "author
    was filtered as untrusted", which silently no-op'd legitimate org-
    member comments. The fix moves trust evaluation into Python so the
    decision is deterministic and cannot be confused with fetch failures.
    """

    def _patches(
        self,
        *,
        event: dict,
        event_name: str,
        is_trusted: bool,
    ):
        """Patch ``main`` dependencies so we can assert dispatch behavior.

        The patches cover: env helpers, the GitHub/Auth constructors, the
        trust helper, and the two event-kind handlers. Callers enter the
        resulting ``contextlib.ExitStack`` via ``with`` and inspect the
        returned MagicMocks.
        """
        from contextlib import ExitStack

        stack = ExitStack()
        stack.enter_context(
            patch("respond_to_pr_comment.repo_parts", return_value=("acme", "widgets"))
        )
        stack.enter_context(patch("respond_to_pr_comment.load_event", return_value=event))
        stack.enter_context(patch("respond_to_pr_comment.optional_env", return_value=event_name))
        stack.enter_context(patch("respond_to_pr_comment.require_env", return_value="token"))
        stack.enter_context(patch("respond_to_pr_comment.Auth.Token"))
        stack.enter_context(patch("respond_to_pr_comment.Github"))
        stack.enter_context(patch("respond_to_pr_comment.repo_slug", return_value="acme/widgets"))
        trust_mock = stack.enter_context(
            patch(
                "respond_to_pr_comment.is_trusted_commenter",
                return_value=is_trusted,
            )
        )
        notice_mock = stack.enter_context(
            patch("respond_to_pr_comment.notice")
        )
        review_handler = stack.enter_context(
            patch("respond_to_pr_comment._handle_review_comment")
        )
        issue_handler = stack.enter_context(
            patch("respond_to_pr_comment._handle_issue_comment")
        )
        return stack, trust_mock, notice_mock, review_handler, issue_handler

    def test_untrusted_commenter_skips_handler_and_emits_notice(self) -> None:
        """Untrusted commenters must NOT reach ``_handle_*`` or the agent."""
        from respond_to_pr_comment import main

        event = {
            "comment": {
                "id": 999,
                "user": {"login": "outsider", "type": "User"},
                "author_association": "NONE",
            },
            "issue": {"number": 7, "pull_request": {}},
        }
        stack, trust_mock, notice_mock, review_handler, issue_handler = self._patches(
            event=event, event_name="issue_comment", is_trusted=False
        )
        with stack:
            main()
        trust_mock.assert_called_once()
        notice_mock.assert_called_once()
        message = notice_mock.call_args.args[0]
        self.assertIn("outsider", message)
        self.assertIn("NONE", message)
        review_handler.assert_not_called()
        issue_handler.assert_not_called()

    def test_trusted_issue_commenter_dispatches_to_issue_handler(self) -> None:
        """A trusted commenter on a PR conversation comment reaches the agent."""
        from respond_to_pr_comment import main

        event = {
            "comment": {
                "id": 42,
                "user": {"login": "alice", "type": "User"},
                "author_association": "MEMBER",
            },
            "issue": {"number": 7, "pull_request": {}},
        }
        stack, trust_mock, notice_mock, review_handler, issue_handler = self._patches(
            event=event, event_name="issue_comment", is_trusted=True
        )
        with stack:
            main()
        trust_mock.assert_called_once()
        notice_mock.assert_not_called()
        review_handler.assert_not_called()
        issue_handler.assert_called_once()

    def test_trusted_review_commenter_dispatches_to_review_handler(self) -> None:
        """A trusted inline review comment reaches ``_handle_review_comment``."""
        from respond_to_pr_comment import main

        event = {
            "comment": {
                "id": 42,
                "user": {"login": "alice", "type": "User"},
                "author_association": "MEMBER",
            },
            "pull_request": {"number": 9},
        }
        stack, trust_mock, notice_mock, review_handler, issue_handler = self._patches(
            event=event,
            event_name="pull_request_review_comment",
            is_trusted=True,
        )
        with stack:
            main()
        trust_mock.assert_called_once()
        review_handler.assert_called_once()
        issue_handler.assert_not_called()

    def test_automation_user_short_circuits_before_trust_check(self) -> None:
        """Bot authors are dropped without even probing org membership."""
        from respond_to_pr_comment import main

        event = {
            "comment": {
                "id": 1,
                "user": {"login": "dependabot[bot]", "type": "Bot"},
                "author_association": "NONE",
            },
            "issue": {"number": 7, "pull_request": {}},
        }
        stack, trust_mock, notice_mock, review_handler, issue_handler = self._patches(
            event=event, event_name="issue_comment", is_trusted=False
        )
        with stack:
            main()
        # Automation user bailed BEFORE we constructed the Github
        # client, so the trust check must not have been consulted.
        trust_mock.assert_not_called()
        notice_mock.assert_not_called()
        review_handler.assert_not_called()
        issue_handler.assert_not_called()


class HandleReviewBodyTest(unittest.TestCase):
    """Tests for pull_request_review event dispatch and _handle_review_body."""

    def _run_main_for_review_event(
        self,
        *,
        review_body: str = "@oz-agent address the comment",
        author_login: str = "seemeroland",
        is_bot: bool = False,
    ) -> dict:
        from respond_to_pr_comment import main

        event = {
            "review": {
                "id": 4158886048,
                "user": {"login": author_login, "type": "Bot" if is_bot else "User"},
                "body": review_body,
                "state": "COMMENTED",
                "author_association": "MEMBER",
                "submitted_at": "2026-04-23T01:05:22Z",
            },
            "pull_request": {"number": 1064},
            "sender": {"login": author_login},
        }
        called: dict = {}

        def fake_handle_review_body(client, github, owner, repo, ev):
            called["handled"] = True

        with (
            patch.dict(
                "os.environ",
                {
                    "GITHUB_EVENT_NAME": "pull_request_review",
                    "GITHUB_REPOSITORY": "warpdotdev/warp-external",
                    "GH_TOKEN": "fake-token",
                },
            ),
            patch("respond_to_pr_comment.load_event", return_value=event),
            patch("respond_to_pr_comment.repo_parts", return_value=("warpdotdev", "warp-external")),
            patch("respond_to_pr_comment.repo_slug", return_value="warpdotdev/warp-external"),
            patch("respond_to_pr_comment.require_env", return_value="fake-token"),
            patch("respond_to_pr_comment.optional_env", return_value="pull_request_review"),
            patch("respond_to_pr_comment._handle_review_body", side_effect=fake_handle_review_body),
            patch("respond_to_pr_comment.Github"),
            patch("respond_to_pr_comment.is_trusted_commenter", return_value=True),
        ):
            main()
        return called

    def test_dispatches_to_handle_review_body_for_review_event(self) -> None:
        called = self._run_main_for_review_event()
        self.assertTrue(called.get("handled"), "Expected _handle_review_body to be called")

    def test_skips_bot_review_authors(self) -> None:
        called = self._run_main_for_review_event(is_bot=True)
        self.assertFalse(called.get("handled"), "Expected bot review to be skipped")


if __name__ == "__main__":
    unittest.main()
