from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
RUN_OZ_PYTHON_SCRIPT_ACTION = (
    REPO_ROOT / ".github" / "actions" / "run-oz-python-script" / "action.yml"
)


class RunOzPythonScriptActionTest(unittest.TestCase):
    def test_setup_uv_uses_action_repository_root_as_working_directory(self) -> None:
        action = RUN_OZ_PYTHON_SCRIPT_ACTION.read_text(encoding="utf-8")
        self.assertIn("working-directory:", action)
        self.assertIn(
            "working-directory: ${{ github.action_path }}/../../..",
            action,
        )


if __name__ == "__main__":
    unittest.main()
