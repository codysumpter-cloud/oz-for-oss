from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from oz_workflows.oz_client import skill_spec


class SkillSpecTest(unittest.TestCase):
    @patch.dict(os.environ, {"GITHUB_REPOSITORY": "warpdotdev/oz-oss-testbed"}, clear=False)
    def test_resolves_short_skill_name_to_full_skill_path(self) -> None:
        self.assertEqual(
            skill_spec("implement-issue"),
            "warpdotdev/oz-oss-testbed:.agents/skills/implement-issue/SKILL.md",
        )

    @patch.dict(os.environ, {"GITHUB_REPOSITORY": "warpdotdev/oz-oss-testbed"}, clear=False)
    def test_preserves_relative_skill_file_path(self) -> None:
        self.assertEqual(
            skill_spec(".agents/skills/review-pr/SKILL.md"),
            "warpdotdev/oz-oss-testbed:.agents/skills/review-pr/SKILL.md",
        )

    def test_preserves_already_qualified_skill_spec(self) -> None:
        qualified = "warpdotdev/oz-oss-testbed:.agents/skills/create-plan/SKILL.md"
        self.assertEqual(skill_spec(qualified), qualified)


if __name__ == "__main__":
    unittest.main()
