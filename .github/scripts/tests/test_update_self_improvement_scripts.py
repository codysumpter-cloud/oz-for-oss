from __future__ import annotations

import unittest
from unittest.mock import patch

import update_dedupe
import update_pr_review
import update_triage


class UpdateScriptsTest(unittest.TestCase):
    def _assert_main_does_not_pass_hardcoded_reviewer(self, module: object) -> None:
        with patch.object(module, "build_agent_config", return_value={}), patch.object(
            module, "run_agent"
        ), patch.object(module, "workspace", return_value="/tmp"), patch.object(
            module, "repo_parts", return_value=("warpdotdev", "oz-for-oss")
        ), patch.object(module, "optional_env", return_value=""), patch.object(
            module, "maybe_push_update_branch"
        ) as mock_push:
            module.main()
        _args, kwargs = mock_push.call_args
        self.assertNotIn("reviewer", kwargs)
        self.assertNotIn("base_branch", kwargs)

    def test_update_pr_review_relies_on_shared_resolution(self) -> None:
        self._assert_main_does_not_pass_hardcoded_reviewer(update_pr_review)

    def test_update_triage_relies_on_shared_resolution(self) -> None:
        self._assert_main_does_not_pass_hardcoded_reviewer(update_triage)

    def test_update_dedupe_relies_on_shared_resolution(self) -> None:
        self._assert_main_does_not_pass_hardcoded_reviewer(update_dedupe)


if __name__ == "__main__":
    unittest.main()
