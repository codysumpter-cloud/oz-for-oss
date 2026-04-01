from __future__ import annotations

import unittest

from resolve_review_context import SLASH_COMMAND_PATTERN


class SlashCommandPatternTest(unittest.TestCase):
    """Tests for the SLASH_COMMAND_PATTERN regex used in resolve_review_context."""

    def test_matches_oz_review(self) -> None:
        match = SLASH_COMMAND_PATTERN.search("/oz-review")
        self.assertIsNotNone(match)

    def test_matches_oz_review_with_focus(self) -> None:
        match = SLASH_COMMAND_PATTERN.search("/oz-review focus on error handling")
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.group(1).strip(), "focus on error handling")

    def test_matches_at_oz_agent_review(self) -> None:
        match = SLASH_COMMAND_PATTERN.search("@oz-agent /review")
        self.assertIsNotNone(match)

    def test_matches_at_oz_agent_review_with_focus(self) -> None:
        match = SLASH_COMMAND_PATTERN.search("@oz-agent /review check the tests")
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.group(1).strip(), "check the tests")

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
