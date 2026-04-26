from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
PR_HOOKS_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "pr-hooks.yml"
RESPOND_LOCAL_WORKFLOW = (
    REPO_ROOT / ".github" / "workflows" / "respond-to-pr-comment-local.yml"
)
RESPOND_REUSABLE_WORKFLOW = (
    REPO_ROOT / ".github" / "workflows" / "respond-to-pr-comment.yml"
)


class WorkflowConcurrencyGuardTest(unittest.TestCase):
    def test_local_pr_comment_adapter_has_no_workflow_level_concurrency(self) -> None:
        workflow = RESPOND_LOCAL_WORKFLOW.read_text(encoding="utf-8")
        self.assertNotIn(
            "group: respond-to-pr-comment-${{ github.event.pull_request.number || github.event.issue.number }}",
            workflow,
        )
        self.assertIn(
            "Mention, bot, event-type, and trust gates all live in the reusable",
            workflow,
        )

    def test_reusable_pr_comment_workflow_serializes_only_trusted_runs(self) -> None:
        workflow = RESPOND_REUSABLE_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("needs: check_trust", workflow)
        self.assertIn("if: needs.check_trust.outputs.trusted == 'true'", workflow)
        self.assertIn(
            "group: respond-to-pr-comment-${{ github.event.pull_request.number || github.event.issue.number }}",
            workflow,
        )
        self.assertIn("cancel-in-progress: false", workflow)

    def test_pr_hooks_has_no_workflow_level_concurrency(self) -> None:
        workflow = PR_HOOKS_WORKFLOW.read_text(encoding="utf-8")
        self.assertNotIn(
            "group: pr-hooks-${{ github.event.pull_request.number || github.event.issue.number || inputs.pr_number || github.run_id }}",
            workflow,
        )

    def test_pr_hooks_serializes_only_review_jobs_after_gates(self) -> None:
        workflow = PR_HOOKS_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("review_pr_after_enforcement:", workflow)
        self.assertIn(
            "group: pr-review-${{ github.event.pull_request.number }}",
            workflow,
        )
        self.assertIn("review_pr_on_demand:", workflow)
        self.assertIn(
            "group: pr-review-${{ needs.resolve_review_context.outputs.pr_number }}",
            workflow,
        )


if __name__ == "__main__":
    unittest.main()
