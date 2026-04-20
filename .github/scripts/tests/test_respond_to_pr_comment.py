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


class RunImplementationPromptTest(unittest.TestCase):
    """Verify the prompt instructs the agent about pr-metadata.json."""

    def test_prompt_instructs_agent_to_upload_pr_metadata_when_scope_changes(
        self,
    ) -> None:
        from respond_to_pr_comment import _run_implementation

        client = MagicMock()
        github = MagicMock()
        pr = _make_pr()
        spec_context, run = _base_patches()
        captured_prompt: dict[str, str] = {}

        def _capture_prompt(**kwargs):
            captured_prompt["prompt"] = kwargs.get("prompt", "")
            return run

        with (
            patch("respond_to_pr_comment.workspace", return_value="/tmp/workspace"),
            patch(
                "respond_to_pr_comment.resolve_spec_context_for_pr",
                return_value=spec_context,
            ),
            patch("respond_to_pr_comment.WorkflowProgressComment"),
            patch("respond_to_pr_comment.resolve_coauthor_line", return_value=""),
            patch(
                "respond_to_pr_comment.build_agent_config",
                return_value=MagicMock(),
            ),
            patch(
                "respond_to_pr_comment.run_agent",
                side_effect=_capture_prompt,
            ),
            patch(
                "respond_to_pr_comment.branch_updated_since",
                return_value=False,
            ),
            patch(
                "respond_to_pr_comment.try_load_pr_metadata_artifact",
                return_value=None,
            ),
            patch(
                "respond_to_pr_comment.try_load_resolved_review_comments_artifact",
                return_value=[],
            ),
        ):
            unique_body = "ATTACKER_PROMPT_INJECTION_NEEDLE_42"
            _run_implementation(
                client,
                github,
                "owner",
                "repo",
                pr,
                event={
                    "comment": {"user": {"login": "alice"}, "body": unique_body},
                    "sender": {"login": "alice"},
                },
                trigger_comment_id=9001,
                trigger_kind="conversation",
                requester="alice",
            )

        prompt = captured_prompt.get("prompt", "")
        self.assertIn("pr-metadata.json", prompt)
        self.assertIn("pr_title", prompt)
        self.assertIn("pr_summary", prompt)
        self.assertIn("oz-dev artifact upload pr-metadata.json", prompt)
        # The prompt must describe when to write the artifact and when to
        # skip it so small tweaks don't churn the PR description.
        self.assertIn("materially change", prompt)
        # The prompt must instruct the agent to fetch issue/PR content via
        # the supported fetch script rather than have it inlined into the
        # prompt. The triggering comment body must not be inlined.
        self.assertIn("fetch_github_context.py", prompt)
        self.assertIn("pr --repo owner/repo --number 10", prompt)
        self.assertNotIn(unique_body, prompt)
        # The PR body set on the fake PR must also not be inlined.
        self.assertNotIn("Spec for retry logic", prompt)


if __name__ == "__main__":
    unittest.main()
