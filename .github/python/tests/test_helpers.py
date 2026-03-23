from __future__ import annotations

import unittest

from oz_workflows.helpers import build_plan_preview_section, extract_issue_numbers_from_text


class ExtractIssueNumbersTest(unittest.TestCase):
    def test_extracts_hash_and_url_references(self) -> None:
        text = "Fixes #12 and refs https://github.com/acme/widgets/issues/34"
        self.assertEqual(extract_issue_numbers_from_text("acme", "widgets", text), [12, 34])


class BuildPlanPreviewSectionTest(unittest.TestCase):
    def test_builds_markdown_link_for_plan_branch(self) -> None:
        self.assertEqual(
            build_plan_preview_section("warpdotdev", "oz-oss-testbed", "oz-agent/plan-issue-20", 20),
            "Preview generated plan: [plans/issue-20.md](https://github.com/warpdotdev/oz-oss-testbed/blob/oz-agent/plan-issue-20/plans/issue-20.md)",
        )


if __name__ == "__main__":
    unittest.main()
