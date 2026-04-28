from __future__ import annotations

import unittest
from types import SimpleNamespace

from resolve_review_context import (
    MAX_EXPLICIT_INVOCATIONS_PER_PR,
    SLASH_COMMAND_PATTERN,
    _count_explicit_invocations,
    _resolve_comment_match,
)


class SlashCommandPatternTest(unittest.TestCase):
    """Tests for the SLASH_COMMAND_PATTERN regex used in resolve_review_context."""

    def test_matches_oz_review(self) -> None:
        match = SLASH_COMMAND_PATTERN.search("/oz-review")
        self.assertIsNotNone(match)

    def test_matches_oz_review_when_followed_by_text(self) -> None:
        # Trailing text is matched but not captured: any prompt the
        # commenter appends is intentionally discarded so it cannot be
        # forwarded to the review agent.
        match = SLASH_COMMAND_PATTERN.search("/oz-review focus on error handling")
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.groups(), ())

    def test_matches_at_oz_agent_review(self) -> None:
        match = SLASH_COMMAND_PATTERN.search("@oz-agent /review")
        self.assertIsNotNone(match)

    def test_matches_at_oz_agent_review_when_followed_by_text(self) -> None:
        match = SLASH_COMMAND_PATTERN.search("@oz-agent /review check the tests")
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.groups(), ())

    def test_matches_at_oz_agent_review_case_insensitive(self) -> None:
        match = SLASH_COMMAND_PATTERN.search("@OZ-AGENT /REVIEW")
        self.assertIsNotNone(match)

    def test_matches_oz_review_after_whitespace(self) -> None:
        match = SLASH_COMMAND_PATTERN.search("hey team\n/oz-review")
        self.assertIsNotNone(match)

    def test_matches_at_oz_agent_review_after_whitespace(self) -> None:
        match = SLASH_COMMAND_PATTERN.search("please review this\n@oz-agent /review")
        self.assertIsNotNone(match)

    def test_no_match_on_unrelated_comment(self) -> None:
        match = SLASH_COMMAND_PATTERN.search("looks good to me!")
        self.assertIsNone(match)

    def test_no_match_on_partial_command(self) -> None:
        match = SLASH_COMMAND_PATTERN.search("/oz-revi")
        self.assertIsNone(match)

    def test_no_match_at_oz_agent_without_review(self) -> None:
        match = SLASH_COMMAND_PATTERN.search("@oz-agent please help")
        self.assertIsNone(match)


class ResolveCommentMatchTest(unittest.TestCase):
    """``_resolve_comment_match`` removes the org-membership gate.

    Any non-automation user that posts ``/oz-review`` (or
    ``@oz-agent /review``) on a PR comment now matches, regardless of
    their ``author_association``. Any text following the slash command
    is intentionally discarded so a commenter cannot supply a free-form
    prompt to the review agent.
    """

    def _build_issue_comment_event(
        self,
        *,
        body: str,
        association: str,
        is_pr: bool = True,
        user_login: str = "external-contributor",
        user_type: str = "User",
    ) -> dict:
        return {
            "issue": {
                "number": 42,
                "pull_request": {"url": "https://example.test/pulls/42"} if is_pr else None,
            },
            "comment": {
                "id": 100,
                "body": body,
                "author_association": association,
                "user": {"login": user_login, "type": user_type},
            },
        }

    def _build_review_comment_event(
        self,
        *,
        body: str,
        association: str,
        user_login: str = "external-contributor",
        user_type: str = "User",
    ) -> dict:
        return {
            "pull_request": {"number": 7},
            "comment": {
                "id": 200,
                "body": body,
                "author_association": association,
                "user": {"login": user_login, "type": user_type},
            },
        }

    def test_non_collaborator_can_trigger_via_issue_comment(self) -> None:
        event = self._build_issue_comment_event(
            body="/oz-review please re-check",
            association="NONE",
        )
        matched, pr_number, requester, comment_id = _resolve_comment_match(
            event, "issue_comment"
        )
        self.assertTrue(matched)
        self.assertEqual(pr_number, "42")
        self.assertEqual(requester, "external-contributor")
        self.assertEqual(comment_id, "100")

    def test_non_collaborator_can_trigger_via_review_comment(self) -> None:
        event = self._build_review_comment_event(
            body="@oz-agent /review focus on tests",
            association="FIRST_TIME_CONTRIBUTOR",
        )
        matched, pr_number, requester, comment_id = _resolve_comment_match(
            event, "pull_request_review_comment"
        )
        self.assertTrue(matched)
        self.assertEqual(pr_number, "7")
        self.assertEqual(requester, "external-contributor")
        self.assertEqual(comment_id, "200")

    def test_collaborator_still_matches(self) -> None:
        event = self._build_issue_comment_event(
            body="/oz-review",
            association="COLLABORATOR",
            user_login="alice",
        )
        matched, pr_number, requester, _comment_id = _resolve_comment_match(
            event, "issue_comment"
        )
        self.assertTrue(matched)
        self.assertEqual(pr_number, "42")
        self.assertEqual(requester, "alice")

    def test_bot_user_does_not_match(self) -> None:
        event = self._build_issue_comment_event(
            body="/oz-review",
            association="MEMBER",
            user_login="dependabot[bot]",
            user_type="Bot",
        )
        matched, _pr_number, _requester, _comment_id = _resolve_comment_match(
            event, "issue_comment"
        )
        self.assertFalse(matched)

    def test_issue_comment_on_non_pr_does_not_match(self) -> None:
        event = self._build_issue_comment_event(
            body="/oz-review",
            association="MEMBER",
            is_pr=False,
        )
        matched, pr_number, _requester, _comment_id = _resolve_comment_match(
            event, "issue_comment"
        )
        self.assertFalse(matched)
        self.assertEqual(pr_number, "")

    def test_unrelated_event_returns_blank_tuple(self) -> None:
        matched, pr_number, requester, comment_id = _resolve_comment_match(
            {}, "workflow_dispatch"
        )
        self.assertFalse(matched)
        self.assertEqual(pr_number, "")
        self.assertEqual(requester, "")
        self.assertEqual(comment_id, "")

    def test_no_slash_command_does_not_match(self) -> None:
        event = self._build_issue_comment_event(
            body="LGTM, thanks!",
            association="MEMBER",
        )
        matched, _pr_number, requester, comment_id = _resolve_comment_match(
            event, "issue_comment"
        )
        self.assertFalse(matched)
        self.assertEqual(requester, "external-contributor")
        self.assertEqual(comment_id, "100")


class CountExplicitInvocationsTest(unittest.TestCase):
    """``_count_explicit_invocations`` aggregates conversation + review comments."""

    def _build_pr(
        self,
        *,
        issue_comments: list[SimpleNamespace],
        review_comments: list[SimpleNamespace],
    ) -> SimpleNamespace:
        return SimpleNamespace(
            get_issue_comments=lambda: list(issue_comments),
            get_review_comments=lambda: list(review_comments),
        )

    def _build_client(self, pr: SimpleNamespace) -> SimpleNamespace:
        repo = SimpleNamespace(get_pull=lambda _number: pr)
        return SimpleNamespace(get_repo=lambda _slug: repo)

    @staticmethod
    def _human(body: str, *, login: str = "alice") -> SimpleNamespace:
        return SimpleNamespace(
            body=body,
            user=SimpleNamespace(login=login, type="User"),
        )

    @staticmethod
    def _bot(body: str, *, login: str = "oz-agent[bot]") -> SimpleNamespace:
        return SimpleNamespace(
            body=body,
            user=SimpleNamespace(login=login, type="Bot"),
        )

    def test_counts_only_slash_command_comments(self) -> None:
        pr = self._build_pr(
            issue_comments=[
                self._human("/oz-review"),
                self._human("looks good!"),
                self._human("@oz-agent /review focus on errors"),
            ],
            review_comments=[
                self._human("nit: rename this"),
                self._human("/oz-review"),
            ],
        )
        client = self._build_client(pr)
        self.assertEqual(_count_explicit_invocations(client, "owner/repo", 7), 3)

    def test_returns_zero_when_no_matches(self) -> None:
        pr = self._build_pr(
            issue_comments=[
                self._human("lgtm"),
                self._human("thanks for fixing"),
            ],
            review_comments=[self._human("consider extracting this")],
        )
        client = self._build_client(pr)
        self.assertEqual(_count_explicit_invocations(client, "owner/repo", 7), 0)

    def test_ignores_bot_authored_invocations(self) -> None:
        # Comments authored by automation accounts must not count toward
        # the per-PR throttle. A noisy bot replaying ``/oz-review`` in a
        # comment summary should never be able to exhaust the cap on
        # behalf of human reviewers, and bots are also not allowed to
        # trigger the workflow themselves.
        pr = self._build_pr(
            issue_comments=[
                self._human("/oz-review"),
                self._bot("Bot summary mentioning /oz-review"),
                self._bot(
                    "@oz-agent /review please retry",
                    login="oz-helper[bot]",
                ),
            ],
            review_comments=[
                self._bot("/oz-review", login="renovate[bot]"),
                self._human("@oz-agent /review"),
            ],
        )
        client = self._build_client(pr)
        self.assertEqual(_count_explicit_invocations(client, "owner/repo", 7), 2)

    def test_handles_missing_body(self) -> None:
        # ``body`` may be missing/None on some payloads; the helper should
        # handle that gracefully without raising.
        pr = SimpleNamespace(
            get_issue_comments=lambda: [
                SimpleNamespace(
                    body=None,
                    user=SimpleNamespace(login="alice", type="User"),
                )
            ],
            get_review_comments=lambda: [
                SimpleNamespace(
                    user=SimpleNamespace(login="alice", type="User"),
                )
            ],
        )
        client = self._build_client(pr)
        self.assertEqual(_count_explicit_invocations(client, "owner/repo", 7), 0)


class ThrottleConstantTest(unittest.TestCase):
    def test_default_cap_is_three(self) -> None:
        # The product requirement is to cap explicit /oz-review
        # invocations at three per PR; lock the constant in via a test
        # so any future change is intentional.
        self.assertEqual(MAX_EXPLICIT_INVOCATIONS_PER_PR, 3)
