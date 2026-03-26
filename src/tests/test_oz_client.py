from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from oz_workflows.oz_client import build_oz_client, skill_spec


class BuildOzClientTest(unittest.TestCase):
    @patch.dict(
        os.environ,
        {"WARP_API_KEY": "fake-key", "STAGING_ORIGIN_TOKEN": "fake-token"},
        clear=False,
    )
    @patch("oz_workflows.oz_client.OzAPI")
    def test_default_headers_include_api_source(self, mock_oz_api: unittest.mock.MagicMock) -> None:
        build_oz_client()
        _args, kwargs = mock_oz_api.call_args
        headers = kwargs["default_headers"]
        self.assertEqual(headers["x-oz-api-source"], "GITHUB_ACTION")
        self.assertEqual(headers["X-Warp-Origin-Token"], "fake-token")


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
        qualified = "warpdotdev/oz-oss-testbed:.agents/skills/create-tech-spec/SKILL.md"
        self.assertEqual(skill_spec(qualified), qualified)


if __name__ == "__main__":
    unittest.main()
