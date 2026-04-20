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


# Each entry declares a self-improvement loop, its allowed prefix list,
# and the file paths that should be allowed or rejected by
# ``assert_write_surface``. Any shared rejected paths (e.g.
# ``.github/scripts/*``) apply to all loops.
_GUARD_CASES = [
    {
        "loop_name": "update-pr-review",
        "allowed_prefixes": list(update_pr_review.ALLOWED_PREFIXES),
        "allowed_paths": [
            ".agents/skills/review-pr-local/SKILL.md",
            ".agents/skills/review-spec-local/SKILL.md",
        ],
        "rejected_paths": [
            # Core review-pr skill is owned by the shared skill definition,
            # not the local companion.
            ".agents/skills/review-pr/SKILL.md",
            # Workflow scripts are out of scope for every self-improvement
            # loop.
            ".github/scripts/review_pr.py",
            # ``.github/issue-triage/`` is owned by ``update-triage``;
            # allowing ``update-pr-review`` to edit it would create
            # dual-ownership.
            ".github/issue-triage/config.json",
        ],
    },
    {
        "loop_name": "update-triage",
        "allowed_prefixes": list(update_triage.ALLOWED_PREFIXES),
        "allowed_paths": [
            ".agents/skills/triage-issue-local/SKILL.md",
            ".github/issue-triage/config.json",
        ],
        "rejected_paths": [
            ".agents/skills/triage-issue/SKILL.md",
            # Dedupe companion belongs to the ``update-dedupe`` loop, not
            # triage.
            ".agents/skills/dedupe-issue-local/SKILL.md",
        ],
    },
    {
        "loop_name": "update-dedupe",
        "allowed_prefixes": list(update_dedupe.ALLOWED_PREFIXES),
        "allowed_paths": [
            ".agents/skills/dedupe-issue-local/SKILL.md",
        ],
        "rejected_paths": [
            ".agents/skills/dedupe-issue/SKILL.md",
            ".agents/skills/triage-issue-local/SKILL.md",
            # Dedupe is scoped tighter than triage; it does not own
            # ``.github/issue-triage/*``.
            ".github/issue-triage/config.json",
        ],
    },
]


class SelfImprovementGuardTest(unittest.TestCase):
    def test_allowed_paths_pass_write_surface_check(self) -> None:
        for case in _GUARD_CASES:
            with self.subTest(loop_name=case["loop_name"]):
                assert_write_surface(
                    case["allowed_paths"],
                    allowed_prefixes=case["allowed_prefixes"],
                    loop_name=case["loop_name"],
                )

    def test_rejected_paths_raise_write_surface_violation(self) -> None:
        for case in _GUARD_CASES:
            for path in case["rejected_paths"]:
                with self.subTest(loop_name=case["loop_name"], path=path):
                    with self.assertRaises(WriteSurfaceViolation):
                        assert_write_surface(
                            [path],
                            allowed_prefixes=case["allowed_prefixes"],
                            loop_name=case["loop_name"],
                        )


if __name__ == "__main__":
    unittest.main()
