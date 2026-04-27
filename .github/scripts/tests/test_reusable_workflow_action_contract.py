from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
MIGRATED_WORKFLOWS = (
    "comment-on-unready-assigned-issue.yml",
    "create-implementation-from-issue.yml",
    "create-spec-from-issue.yml",
    "enforce-pr-issue-state.yml",
    "remove-stale-issue-labels-on-plan-approved.yml",
    "respond-to-pr-comment.yml",
    "respond-to-triaged-issue-comment.yml",
    "review-pull-request.yml",
    "triage-new-issues.yml",
    "trigger-implementation-on-plan-approved.yml",
    "update-dedupe.yml",
    "update-pr-review.yml",
    "update-triage.yml",
)


class ReusableWorkflowActionContractTest(unittest.TestCase):
    def test_migrated_workflows_no_longer_use_workflow_code_checkout_contract(self) -> None:
        for workflow_name in MIGRATED_WORKFLOWS:
            with self.subTest(workflow=workflow_name):
                workflow = (WORKFLOWS_DIR / workflow_name).read_text(encoding="utf-8")
                self.assertNotIn("WORKFLOW_CODE_REPOSITORY", workflow)
                self.assertNotIn("WORKFLOW_CODE_REF", workflow)
                self.assertNotIn("WORKFLOW_CODE_PATH", workflow)
                self.assertNotIn("repository: ${{ env.WORKFLOW_CODE_REPOSITORY }}", workflow)
                self.assertNotIn(".github/scripts/requirements.txt", workflow)

    def test_migrated_workflows_use_composite_actions_for_script_execution(self) -> None:
        for workflow_name in MIGRATED_WORKFLOWS:
            with self.subTest(workflow=workflow_name):
                workflow = (WORKFLOWS_DIR / workflow_name).read_text(encoding="utf-8")
                self.assertIn(
                    "warpdotdev/oz-for-oss/.github/actions/run-oz-python-script@main",
                    workflow,
                )

    def test_triage_workflows_use_triage_image_action(self) -> None:
        for workflow_name in ("triage-new-issues.yml", "respond-to-triaged-issue-comment.yml"):
            with self.subTest(workflow=workflow_name):
                workflow = (WORKFLOWS_DIR / workflow_name).read_text(encoding="utf-8")
                self.assertIn(
                    "warpdotdev/oz-for-oss/.github/actions/build-triage-image@main",
                    workflow,
                )
                self.assertNotIn("docker build \\", workflow)


if __name__ == "__main__":
    unittest.main()
