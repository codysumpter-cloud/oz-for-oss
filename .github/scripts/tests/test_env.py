from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from oz_workflows.env import optional_env, require_env, resolve_issue_number


class EnvHelpersTest(unittest.TestCase):
    def test_require_env_trims_value(self) -> None:
        with patch.dict(os.environ, {"EXAMPLE_VAR": "  value  "}):
            self.assertEqual(require_env("EXAMPLE_VAR"), "value")

    def test_optional_env_returns_trimmed_string(self) -> None:
        with patch.dict(os.environ, {"EXAMPLE_VAR": "  value  "}):
            self.assertEqual(optional_env("EXAMPLE_VAR"), "value")

    def test_resolve_issue_number_prefers_event_payload(self) -> None:
        self.assertEqual(resolve_issue_number({"issue": {"number": 42}}), 42)

    def test_resolve_issue_number_falls_back_to_env_override(self) -> None:
        with patch.dict(os.environ, {"ISSUE_NUMBER": "366"}):
            self.assertEqual(resolve_issue_number({}), 366)

    def test_resolve_issue_number_raises_when_missing(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                resolve_issue_number({})


if __name__ == "__main__":
    unittest.main()
