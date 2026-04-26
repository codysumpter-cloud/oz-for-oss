from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import update_dedupe
import update_pr_review
import update_triage


class UpdateScriptsTest(unittest.TestCase):
    def _assert_main_does_not_pass_hardcoded_reviewer(self, module: object) -> None:
        with patch.object(module, "build_agent_config", return_value={}), patch.object(
            module, "run_agent", return_value=SimpleNamespace(run_id="run-123")
        ), patch.object(module, "workspace", return_value="/tmp"), patch.object(
            module, "repo_parts", return_value=("warpdotdev", "oz-for-oss")
        ), patch.object(module, "optional_env", return_value=""), patch.object(
            module, "maybe_push_update_branch"
        ) as mock_push:
            module.main()
        _args, kwargs = mock_push.call_args
        self.assertNotIn("reviewer", kwargs)
        self.assertNotIn("base_branch", kwargs)

    def _assert_main_passes_pr_metadata(self, module: object) -> None:
        metadata = {
            "branch_name": getattr(module, "UPDATE_BRANCH"),
            "pr_title": "chore: refresh companion skill guidance",
            "pr_summary": "## Summary\nUpdated the companion skill from recent evidence.",
        }
        with patch.object(module, "build_agent_config", return_value={}), patch.object(
            module, "run_agent", return_value=SimpleNamespace(run_id="run-123")
        ), patch.object(module, "workspace", return_value="/tmp"), patch.object(
            module, "repo_parts", return_value=("warpdotdev", "oz-for-oss")
        ), patch.object(module, "optional_env", return_value=""), patch.object(
            module, "load_pr_metadata_artifact", return_value=metadata
        ) as mock_load_metadata, patch.object(
            module, "maybe_push_update_branch"
        ) as mock_push:
            module.main()
            # The metadata supplier must NOT be called eagerly; it is only invoked
            # inside maybe_push_update_branch when there are actual changed files.
            mock_load_metadata.assert_not_called()
            _args, kwargs = mock_push.call_args
            supplier = kwargs.get("metadata_supplier")
            self.assertIsNotNone(supplier, "metadata_supplier kwarg must be passed")
            self.assertTrue(callable(supplier))
            # Calling the supplier should delegate to load_pr_metadata_artifact.
            result = supplier()
            mock_load_metadata.assert_called_once_with("run-123")
            self.assertEqual(result, metadata)

    def test_update_pr_review_relies_on_shared_resolution(self) -> None:
        self._assert_main_does_not_pass_hardcoded_reviewer(update_pr_review)

    def test_update_triage_relies_on_shared_resolution(self) -> None:
        self._assert_main_does_not_pass_hardcoded_reviewer(update_triage)

    def test_update_dedupe_relies_on_shared_resolution(self) -> None:
        self._assert_main_does_not_pass_hardcoded_reviewer(update_dedupe)

    def test_update_pr_review_uses_uploaded_pr_metadata(self) -> None:
        self._assert_main_passes_pr_metadata(update_pr_review)

    def test_update_triage_uses_uploaded_pr_metadata(self) -> None:
        self._assert_main_passes_pr_metadata(update_triage)

    def test_update_dedupe_uses_uploaded_pr_metadata(self) -> None:
        self._assert_main_passes_pr_metadata(update_dedupe)


if __name__ == "__main__":
    unittest.main()
