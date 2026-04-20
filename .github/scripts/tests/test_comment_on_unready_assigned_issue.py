from __future__ import annotations

import unittest

from comment_on_unready_assigned_issue import (
    DEFAULT_ASSIGNEE_LOGIN,
    resolve_assignee_login,
)


class ResolveAssigneeLoginTest(unittest.TestCase):
    """Tests for resolve_assignee_login, which must tolerate null/missing values."""

    def test_assignee_shapes(self) -> None:
        # GitHub webhook payloads can set "assignee" to null (e.g. on an
        # unassignment event). That and other shapes must not raise
        # AttributeError and should fall back to ``DEFAULT_ASSIGNEE_LOGIN``
        # except when a concrete login is present.
        cases = [
            ("login_present", {"assignee": {"login": "alice"}}, "alice"),
            ("missing_key", {}, DEFAULT_ASSIGNEE_LOGIN),
            ("assignee_none", {"assignee": None}, DEFAULT_ASSIGNEE_LOGIN),
            ("no_login_key", {"assignee": {}}, DEFAULT_ASSIGNEE_LOGIN),
            (
                "empty_login_string",
                {"assignee": {"login": ""}},
                DEFAULT_ASSIGNEE_LOGIN,
            ),
        ]
        for label, event, expected in cases:
            with self.subTest(label=label):
                self.assertEqual(resolve_assignee_login(event), expected)


if __name__ == "__main__":
    unittest.main()
