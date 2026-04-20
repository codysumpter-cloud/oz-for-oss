"""Tests for the write-surface guards on the narrowed self-improvement loops.

Each ``update-<agent>`` entrypoint runs ``assert_write_surface`` against
the changed files on ``oz-agent/update-<agent>`` before pushing. These
tests exercise the prefix lists declared in each entrypoint to confirm
that a simulated diff inside the allowed surface passes and a simulated
diff that touches a core skill or ``.github/scripts/*`` aborts the run.
"""

from __future__ import annotations

import unittest

import update_dedupe
import update_pr_review
import update_triage
from oz_workflows.repo_local import WriteSurfaceViolation, assert_write_surface


class UpdatePrReviewGuardTest(unittest.TestCase):
    def test_allows_diff_restricted_to_local_companions(self) -> None:
        assert_write_surface(
            [
                ".agents/skills/review-pr-local/SKILL.md",
                ".agents/skills/review-spec-local/SKILL.md",
            ],
            allowed_prefixes=list(update_pr_review.ALLOWED_PREFIXES),
            loop_name="update-pr-review",
        )

    def test_rejects_diff_touching_core_review_pr_skill(self) -> None:
        with self.assertRaises(WriteSurfaceViolation):
            assert_write_surface(
                [".agents/skills/review-pr/SKILL.md"],
                allowed_prefixes=list(update_pr_review.ALLOWED_PREFIXES),
                loop_name="update-pr-review",
            )

    def test_rejects_diff_touching_workflow_scripts(self) -> None:
        with self.assertRaises(WriteSurfaceViolation):
            assert_write_surface(
                [".github/scripts/review_pr.py"],
                allowed_prefixes=list(update_pr_review.ALLOWED_PREFIXES),
                loop_name="update-pr-review",
            )

    def test_rejects_diff_touching_issue_triage_config(self) -> None:
        # ``.github/issue-triage/`` is owned by ``update-triage``; allowing
        # ``update-pr-review`` to edit it would create dual-ownership and
        # could silently mutate triage config from PR-review feedback.
        with self.assertRaises(WriteSurfaceViolation):
            assert_write_surface(
                [".github/issue-triage/config.json"],
                allowed_prefixes=list(update_pr_review.ALLOWED_PREFIXES),
                loop_name="update-pr-review",
            )


class UpdateTriageGuardTest(unittest.TestCase):
    def test_allows_triage_local_and_issue_triage_config(self) -> None:
        assert_write_surface(
            [
                ".agents/skills/triage-issue-local/SKILL.md",
                ".github/issue-triage/config.json",
            ],
            allowed_prefixes=list(update_triage.ALLOWED_PREFIXES),
            loop_name="update-triage",
        )

    def test_rejects_diff_touching_core_triage_skill(self) -> None:
        with self.assertRaises(WriteSurfaceViolation):
            assert_write_surface(
                [".agents/skills/triage-issue/SKILL.md"],
                allowed_prefixes=list(update_triage.ALLOWED_PREFIXES),
                loop_name="update-triage",
            )

    def test_rejects_diff_touching_dedupe_companion(self) -> None:
        # Dedupe companion belongs to the ``update-dedupe`` loop, not triage.
        with self.assertRaises(WriteSurfaceViolation):
            assert_write_surface(
                [".agents/skills/dedupe-issue-local/SKILL.md"],
                allowed_prefixes=list(update_triage.ALLOWED_PREFIXES),
                loop_name="update-triage",
            )


class UpdateDedupeGuardTest(unittest.TestCase):
    def test_allows_dedupe_local_companion(self) -> None:
        assert_write_surface(
            [".agents/skills/dedupe-issue-local/SKILL.md"],
            allowed_prefixes=list(update_dedupe.ALLOWED_PREFIXES),
            loop_name="update-dedupe",
        )

    def test_rejects_diff_touching_core_dedupe_skill(self) -> None:
        with self.assertRaises(WriteSurfaceViolation):
            assert_write_surface(
                [".agents/skills/dedupe-issue/SKILL.md"],
                allowed_prefixes=list(update_dedupe.ALLOWED_PREFIXES),
                loop_name="update-dedupe",
            )

    def test_rejects_diff_touching_triage_companion(self) -> None:
        with self.assertRaises(WriteSurfaceViolation):
            assert_write_surface(
                [".agents/skills/triage-issue-local/SKILL.md"],
                allowed_prefixes=list(update_dedupe.ALLOWED_PREFIXES),
                loop_name="update-dedupe",
            )

    def test_rejects_diff_touching_issue_triage_config(self) -> None:
        # Dedupe is scoped tighter than triage; it does not own
        # ``.github/issue-triage/*``.
        with self.assertRaises(WriteSurfaceViolation):
            assert_write_surface(
                [".github/issue-triage/config.json"],
                allowed_prefixes=list(update_dedupe.ALLOWED_PREFIXES),
                loop_name="update-dedupe",
            )


if __name__ == "__main__":
    unittest.main()
