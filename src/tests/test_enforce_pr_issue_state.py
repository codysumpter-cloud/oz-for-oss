from __future__ import annotations

import unittest

from enforce_pr_issue_state import _is_pr_author_org_member
from oz_workflows.helpers import ORG_MEMBER_ASSOCIATIONS


class IsOrgMemberAssociationsTest(unittest.TestCase):
    def test_member_association_is_recognized(self) -> None:
        self.assertIn("MEMBER", ORG_MEMBER_ASSOCIATIONS)

    def test_owner_association_is_recognized(self) -> None:
        self.assertIn("OWNER", ORG_MEMBER_ASSOCIATIONS)

    def test_contributor_is_not_recognized(self) -> None:
        self.assertNotIn("CONTRIBUTOR", ORG_MEMBER_ASSOCIATIONS)

    def test_none_is_not_recognized(self) -> None:
        self.assertNotIn("NONE", ORG_MEMBER_ASSOCIATIONS)


class IsPrAuthorOrgMemberTest(unittest.TestCase):
    def test_member_returns_true(self) -> None:
        pr = {"author_association": "MEMBER"}
        self.assertTrue(_is_pr_author_org_member(pr))

    def test_owner_returns_true(self) -> None:
        pr = {"author_association": "OWNER"}
        self.assertTrue(_is_pr_author_org_member(pr))

    def test_contributor_returns_false(self) -> None:
        pr = {"author_association": "CONTRIBUTOR"}
        self.assertFalse(_is_pr_author_org_member(pr))

    def test_none_association_returns_false(self) -> None:
        pr = {"author_association": "NONE"}
        self.assertFalse(_is_pr_author_org_member(pr))

    def test_collaborator_returns_false(self) -> None:
        pr = {"author_association": "COLLABORATOR"}
        self.assertFalse(_is_pr_author_org_member(pr))

    def test_missing_field_returns_false(self) -> None:
        pr: dict[str, str] = {}
        self.assertFalse(_is_pr_author_org_member(pr))

    def test_empty_string_returns_false(self) -> None:
        pr = {"author_association": ""}
        self.assertFalse(_is_pr_author_org_member(pr))

    def test_first_timer_returns_false(self) -> None:
        pr = {"author_association": "FIRST_TIMER"}
        self.assertFalse(_is_pr_author_org_member(pr))


if __name__ == "__main__":
    unittest.main()
