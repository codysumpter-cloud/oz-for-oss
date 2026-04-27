from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
PR_HOOKS_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "pr-hooks.yml"
REVIEW_PR_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "review-pull-request.yml"
RESPOND_TO_PR_COMMENT_WORKFLOW = (
    REPO_ROOT / ".github" / "workflows" / "respond-to-pr-comment.yml"
)


class PrReviewWorkflowGuardTest(unittest.TestCase):
    def test_pr_hooks_checks_out_default_branch_for_context_resolution(self) -> None:
        workflow = PR_HOOKS_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("ref: ${{ github.event.repository.default_branch }}", workflow)
    def test_pr_hooks_does_not_skip_cherrypick_prefixed_branches(self) -> None:
        workflow = PR_HOOKS_WORKFLOW.read_text(encoding="utf-8")
        self.assertNotIn("!startsWith(github.event.pull_request.head.ref, 'cherrypick')", workflow)

    def test_review_workflow_does_not_special_case_cherrypick_branches(self) -> None:
        workflow = REVIEW_PR_WORKFLOW.read_text(encoding="utf-8")
        self.assertNotIn('head_ref.startswith("cherrypick")', workflow)
        self.assertNotIn("skip_reason=cherrypick-branch", workflow)

    def test_respond_to_pr_comment_checks_out_default_branch(self) -> None:
        workflow = RESPOND_TO_PR_COMMENT_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("ref: ${{ github.event.repository.default_branch }}", workflow)
