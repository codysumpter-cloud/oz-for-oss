from __future__ import annotations

import unittest

from comment_on_unready_assigned_issue import (
    DEFAULT_ASSIGNEE_LOGIN,
    resolve_assignee_login,
)


class ResolveAssigneeLoginTest(unittest.TestCase):
    """Tests for resolve_assignee_login, which must tolerate null/missing values."""

    def test_returns_login_when_assignee_present(self) -> None:
        event = {"assignee": {"login": "alice"}}
        self.assertEqual(resolve_assignee_login(event), "alice")

    def test_defaults_when_assignee_key_missing(self) -> None:
        self.assertEqual(resolve_assignee_login({}), DEFAULT_ASSIGNEE_LOGIN)

    def test_defaults_when_assignee_is_none(self) -> None:
        # GitHub webhook payloads can set "assignee" to null (e.g. on an
        # unassignment event). This must not raise AttributeError.
        self.assertEqual(
            resolve_assignee_login({"assignee": None}), DEFAULT_ASSIGNEE_LOGIN
        )

    def test_defaults_when_assignee_has_no_login(self) -> None:
        self.assertEqual(
            resolve_assignee_login({"assignee": {}}), DEFAULT_ASSIGNEE_LOGIN
        )

    def test_defaults_when_login_is_empty_string(self) -> None:
        self.assertEqual(
            resolve_assignee_login({"assignee": {"login": ""}}),
            DEFAULT_ASSIGNEE_LOGIN,
        )


if __name__ == "__main__":
    unittest.main()
