from __future__ import annotations

import unittest

from review_pr import (
    _commentable_lines_for_patch,
    _extract_suggestion_blocks,
    _line_content_for_patch,
    _normalize_review_path,
    _normalize_review_payload,
    _validate_suggestion_blocks,
)


class NormalizeReviewPathTest(unittest.TestCase):
    def test_strips_a_prefix(self) -> None:
        self.assertEqual(_normalize_review_path("a/src/file.py"), "src/file.py")

    def test_strips_b_prefix(self) -> None:
        self.assertEqual(_normalize_review_path("b/src/file.py"), "src/file.py")

    def test_strips_dot_slash_prefix(self) -> None:
        self.assertEqual(_normalize_review_path("./src/file.py"), "src/file.py")

    def test_does_not_double_strip_a_b_path(self) -> None:
        self.assertEqual(_normalize_review_path("a/b/real_dir/file.py"), "b/real_dir/file.py")

    def test_no_prefix(self) -> None:
        self.assertEqual(_normalize_review_path("src/file.py"), "src/file.py")

    def test_none_value(self) -> None:
        self.assertEqual(_normalize_review_path(None), "")

    def test_empty_string(self) -> None:
        self.assertEqual(_normalize_review_path(""), "")

    def test_whitespace_stripped(self) -> None:
        self.assertEqual(_normalize_review_path("  a/src/file.py  "), "src/file.py")


class CommentableLinesForPatchTest(unittest.TestCase):
    def test_tracks_valid_left_and_right_lines_from_patch(self) -> None:
        patch = """@@ -10,3 +10,4 @@
 context
-old_value
+new_value
 unchanged
"""
        result = _commentable_lines_for_patch(patch)
        self.assertEqual(result["LEFT"], {10, 11, 12})
        self.assertEqual(result["RIGHT"], {10, 11, 12})

    def test_context_lines_commentable_on_left(self) -> None:
        patch = """@@ -5,3 +5,3 @@
 context_a
-removed
+added
 context_b
"""
        result = _commentable_lines_for_patch(patch)
        self.assertIn(5, result["LEFT"])
        self.assertIn(7, result["LEFT"])
        self.assertIn(5, result["RIGHT"])
        self.assertIn(7, result["RIGHT"])

    def test_multi_hunk_patch(self) -> None:
        patch = """@@ -1,3 +1,3 @@
 ctx
-old1
+new1
 ctx
@@ -20,3 +20,3 @@
 ctx
-old2
+new2
 ctx
"""
        result = _commentable_lines_for_patch(patch)
        self.assertIn(2, result["LEFT"])
        self.assertIn(2, result["RIGHT"])
        self.assertIn(21, result["LEFT"])
        self.assertIn(21, result["RIGHT"])

    def test_empty_patch(self) -> None:
        result = _commentable_lines_for_patch("")
        self.assertEqual(result["LEFT"], set())
        self.assertEqual(result["RIGHT"], set())

    def test_none_patch(self) -> None:
        result = _commentable_lines_for_patch(None)
        self.assertEqual(result["LEFT"], set())
        self.assertEqual(result["RIGHT"], set())


class NormalizeReviewPayloadTest(unittest.TestCase):
    def test_accepts_comment_on_changed_file_and_line(self) -> None:
        review = {
            "summary": "## Overview\nLooks fine.",
            "comments": [
                {
                    "path": "src/example.py",
                    "line": 12,
                    "side": "RIGHT",
                    "body": "⚠️ [IMPORTANT] Handle the missing branch.",
                }
            ],
        }
        diff_line_map = {"src/example.py": {"LEFT": {11}, "RIGHT": {10, 11, 12}}}

        summary, comments = _normalize_review_payload(review, diff_line_map)

        self.assertEqual(summary, "## Overview\nLooks fine.")
        self.assertEqual(
            comments,
            [
                {
                    "path": "src/example.py",
                    "line": 12,
                    "side": "RIGHT",
                    "body": "⚠️ [IMPORTANT] Handle the missing branch.",
                }
            ],
        )

    def test_drops_comment_for_file_outside_diff(self) -> None:
        review = {
            "summary": "",
            "comments": [
                {
                    "path": "src/missing.py",
                    "line": 12,
                    "side": "RIGHT",
                    "body": "💡 [SUGGESTION] Mentioned file is outside the diff.",
                }
            ],
        }

        summary, comments = _normalize_review_payload(
            review,
            {"src/example.py": {"LEFT": set(), "RIGHT": {1, 2, 3}}},
        )
        self.assertEqual(comments, [])

    def test_drops_comment_for_non_commentable_line(self) -> None:
        review = {
            "summary": "",
            "comments": [
                {
                    "path": "src/example.py",
                    "line": 99,
                    "side": "RIGHT",
                    "body": "⚠️ [IMPORTANT] Wrong line.",
                }
            ],
        }

        summary, comments = _normalize_review_payload(
            review,
            {"src/example.py": {"LEFT": {11}, "RIGHT": {10, 11, 12}}},
        )
        self.assertEqual(comments, [])

    def test_keeps_valid_comments_when_some_are_invalid(self) -> None:
        review = {
            "summary": "Mixed bag.",
            "comments": [
                {
                    "path": "src/example.py",
                    "line": 10,
                    "side": "RIGHT",
                    "body": "Valid comment.",
                },
                {
                    "path": "src/missing.py",
                    "line": 1,
                    "side": "RIGHT",
                    "body": "Invalid file.",
                },
            ],
        }

        summary, comments = _normalize_review_payload(
            review,
            {"src/example.py": {"LEFT": set(), "RIGHT": {10, 11, 12}}},
        )
        self.assertEqual(len(comments), 1)
        self.assertEqual(comments[0]["body"], "Valid comment.")

    def test_rejects_non_dict_payload(self) -> None:
        with self.assertRaisesRegex(ValueError, "JSON object"):
            _normalize_review_payload("not a dict", {})

    def test_rejects_non_string_summary(self) -> None:
        with self.assertRaisesRegex(ValueError, "`summary` must be a string"):
            _normalize_review_payload({"summary": 42}, {})

    def test_rejects_non_list_comments(self) -> None:
        with self.assertRaisesRegex(ValueError, "`comments` must be a list"):
            _normalize_review_payload({"summary": "", "comments": "nope"}, {})

    def test_drops_non_dict_comment_entry(self) -> None:
        review = {
            "summary": "",
            "comments": ["not a dict"],
        }
        summary, comments = _normalize_review_payload(review, {})
        self.assertEqual(comments, [])

    def test_accepts_valid_start_line(self) -> None:
        review = {
            "summary": "",
            "comments": [
                {
                    "path": "src/example.py",
                    "line": 12,
                    "start_line": 10,
                    "side": "RIGHT",
                    "body": "Multi-line comment.",
                }
            ],
        }
        diff_line_map = {"src/example.py": {"LEFT": set(), "RIGHT": {10, 11, 12}}}
        summary, comments = _normalize_review_payload(review, diff_line_map)
        self.assertEqual(len(comments), 1)
        self.assertEqual(comments[0]["start_line"], 10)
        self.assertEqual(comments[0]["start_side"], "RIGHT")

    def test_drops_comment_with_invalid_start_line(self) -> None:
        review = {
            "summary": "",
            "comments": [
                {
                    "path": "src/example.py",
                    "line": 10,
                    "start_line": 15,
                    "side": "RIGHT",
                    "body": "start_line >= line.",
                }
            ],
        }
        diff_line_map = {"src/example.py": {"LEFT": set(), "RIGHT": {10, 11, 12, 15}}}
        summary, comments = _normalize_review_payload(review, diff_line_map)
        self.assertEqual(comments, [])

    def test_drops_comment_with_non_commentable_start_line(self) -> None:
        review = {
            "summary": "",
            "comments": [
                {
                    "path": "src/example.py",
                    "line": 12,
                    "start_line": 8,
                    "side": "RIGHT",
                    "body": "start_line not in diff.",
                }
            ],
        }
        diff_line_map = {"src/example.py": {"LEFT": set(), "RIGHT": {10, 11, 12}}}
        summary, comments = _normalize_review_payload(review, diff_line_map)
        self.assertEqual(comments, [])

    def test_drops_comment_missing_body(self) -> None:
        review = {
            "summary": "",
            "comments": [
                {
                    "path": "src/example.py",
                    "line": 10,
                    "side": "RIGHT",
                    "body": "",
                }
            ],
        }
        diff_line_map = {"src/example.py": {"LEFT": set(), "RIGHT": {10}}}
        summary, comments = _normalize_review_payload(review, diff_line_map)
        self.assertEqual(comments, [])

    def test_drops_comment_missing_path(self) -> None:
        review = {
            "summary": "",
            "comments": [
                {
                    "line": 10,
                    "side": "RIGHT",
                    "body": "No path.",
                }
            ],
        }
        summary, comments = _normalize_review_payload(review, {})
        self.assertEqual(comments, [])

    def test_drops_comment_with_non_integer_line(self) -> None:
        review = {
            "summary": "",
            "comments": [
                {
                    "path": "src/example.py",
                    "line": "ten",
                    "side": "RIGHT",
                    "body": "Bad line.",
                }
            ],
        }
        diff_line_map = {"src/example.py": {"LEFT": set(), "RIGHT": {10}}}
        summary, comments = _normalize_review_payload(review, diff_line_map)
        self.assertEqual(comments, [])

    def test_defaults_side_to_right(self) -> None:
        review = {
            "summary": "",
            "comments": [
                {
                    "path": "src/example.py",
                    "line": 10,
                    "body": "No explicit side.",
                }
            ],
        }
        diff_line_map = {"src/example.py": {"LEFT": set(), "RIGHT": {10}}}
        summary, comments = _normalize_review_payload(review, diff_line_map)
        self.assertEqual(len(comments), 1)
        self.assertEqual(comments[0]["side"], "RIGHT")

    def test_drops_comment_with_duplicate_prefix_suggestion(self) -> None:
        review = {
            "summary": "",
            "comments": [
                {
                    "path": "src/example.py",
                    "line": 12,
                    "start_line": 11,
                    "side": "RIGHT",
                    "body": "\u26a0\ufe0f [IMPORTANT] Fix.\n\n```suggestion\n# comment above\nnew_body()\n```",
                }
            ],
        }
        diff_line_map = {"src/example.py": {"LEFT": set(), "RIGHT": {10, 11, 12, 13}}}
        diff_content_map = {
            "src/example.py": {
                "LEFT": {},
                "RIGHT": {
                    10: "# comment above",
                    11: "old_body()",
                    12: "}",
                    13: "next_line",
                },
            }
        }
        summary, comments = _normalize_review_payload(
            review, diff_line_map, diff_content_map
        )
        self.assertEqual(comments, [])

    def test_drops_comment_with_duplicate_suffix_suggestion(self) -> None:
        review = {
            "summary": "",
            "comments": [
                {
                    "path": "src/example.py",
                    "line": 12,
                    "start_line": 11,
                    "side": "RIGHT",
                    "body": "\u26a0\ufe0f [IMPORTANT] Fix.\n\n```suggestion\nnew_body()\nreturn value\n```",
                }
            ],
        }
        diff_line_map = {"src/example.py": {"LEFT": set(), "RIGHT": {10, 11, 12, 13}}}
        diff_content_map = {
            "src/example.py": {
                "LEFT": {},
                "RIGHT": {
                    10: "before",
                    11: "old_body()",
                    12: "other_line",
                    13: "return value",
                },
            }
        }
        summary, comments = _normalize_review_payload(
            review, diff_line_map, diff_content_map
        )
        self.assertEqual(comments, [])

    def test_keeps_comment_with_valid_suggestion(self) -> None:
        review = {
            "summary": "",
            "comments": [
                {
                    "path": "src/example.py",
                    "line": 12,
                    "start_line": 11,
                    "side": "RIGHT",
                    "body": "\u26a0\ufe0f [IMPORTANT] Fix.\n\n```suggestion\nnew_body()\nreturn value\n```",
                }
            ],
        }
        diff_line_map = {"src/example.py": {"LEFT": set(), "RIGHT": {10, 11, 12, 13}}}
        diff_content_map = {
            "src/example.py": {
                "LEFT": {},
                "RIGHT": {
                    10: "# unrelated",
                    11: "old_body()",
                    12: "old_return",
                    13: "next_line",
                },
            }
        }
        summary, comments = _normalize_review_payload(
            review, diff_line_map, diff_content_map
        )
        self.assertEqual(len(comments), 1)

    def test_keeps_comment_when_no_content_map_provided(self) -> None:
        review = {
            "summary": "",
            "comments": [
                {
                    "path": "src/example.py",
                    "line": 12,
                    "start_line": 11,
                    "side": "RIGHT",
                    "body": "```suggestion\n# comment above\nnew_body()\n```",
                }
            ],
        }
        diff_line_map = {"src/example.py": {"LEFT": set(), "RIGHT": {11, 12}}}
        summary, comments = _normalize_review_payload(review, diff_line_map)
        self.assertEqual(len(comments), 1)

    def test_keeps_comment_when_surrounding_context_not_in_diff(self) -> None:
        # If we don't know what's above start_line or below line, we can't
        # prove duplication, so keep the comment.
        review = {
            "summary": "",
            "comments": [
                {
                    "path": "src/example.py",
                    "line": 12,
                    "start_line": 11,
                    "side": "RIGHT",
                    "body": "```suggestion\nnew_body()\nreturn value\n```",
                }
            ],
        }
        diff_line_map = {"src/example.py": {"LEFT": set(), "RIGHT": {11, 12}}}
        diff_content_map = {
            "src/example.py": {
                "LEFT": {},
                "RIGHT": {11: "old_body()", 12: "old_return"},
            }
        }
        summary, comments = _normalize_review_payload(
            review, diff_line_map, diff_content_map
        )
        self.assertEqual(len(comments), 1)


class LineContentForPatchTest(unittest.TestCase):
    def test_captures_content_for_each_side(self) -> None:
        patch = """@@ -10,3 +10,4 @@
 context
-old_value
+new_value
 unchanged
"""
        result = _line_content_for_patch(patch)
        self.assertEqual(result["LEFT"], {10: "context", 11: "old_value", 12: "unchanged"})
        self.assertEqual(
            result["RIGHT"],
            {10: "context", 11: "new_value", 12: "unchanged"},
        )

    def test_empty_patch_returns_empty_content(self) -> None:
        result = _line_content_for_patch(None)
        self.assertEqual(result["LEFT"], {})
        self.assertEqual(result["RIGHT"], {})


class ExtractSuggestionBlocksTest(unittest.TestCase):
    def test_extracts_single_block(self) -> None:
        body = "Prefix.\n\n```suggestion\nfoo()\nbar()\n```\n\nTrailing text."
        blocks = _extract_suggestion_blocks(body)
        self.assertEqual(blocks, [["foo()", "bar()"]])

    def test_extracts_multiple_blocks(self) -> None:
        body = "```suggestion\nalpha\n```\n\nsecond\n\n```suggestion\nbeta\ngamma\n```\n"
        blocks = _extract_suggestion_blocks(body)
        self.assertEqual(blocks, [["alpha"], ["beta", "gamma"]])

    def test_returns_empty_list_when_no_blocks(self) -> None:
        self.assertEqual(_extract_suggestion_blocks("no suggestion here"), [])
        self.assertEqual(_extract_suggestion_blocks(""), [])
        self.assertEqual(_extract_suggestion_blocks(None), [])


class ValidateSuggestionBlocksTest(unittest.TestCase):
    def test_flags_duplicate_prefix(self) -> None:
        comment = {
            "path": "src/example.py",
            "side": "RIGHT",
            "line": 12,
            "start_line": 11,
            "body": "```suggestion\n# header\nbody()\n```",
        }
        diff_content_map = {
            "src/example.py": {
                "LEFT": {},
                "RIGHT": {10: "# header", 11: "old", 12: "end"},
            }
        }
        errors = _validate_suggestion_blocks(comment, diff_content_map)
        self.assertEqual(len(errors), 1)
        self.assertIn("duplicates the context line immediately above", errors[0])

    def test_flags_duplicate_suffix(self) -> None:
        comment = {
            "path": "src/example.py",
            "side": "RIGHT",
            "line": 12,
            "body": "```suggestion\nbody()\nfooter\n```",
        }
        diff_content_map = {
            "src/example.py": {
                "LEFT": {},
                "RIGHT": {12: "old", 13: "footer"},
            }
        }
        errors = _validate_suggestion_blocks(comment, diff_content_map)
        self.assertEqual(len(errors), 1)
        self.assertIn("duplicates the context line immediately below", errors[0])

    def test_returns_no_errors_for_valid_block(self) -> None:
        comment = {
            "path": "src/example.py",
            "side": "RIGHT",
            "line": 12,
            "start_line": 11,
            "body": "```suggestion\nalpha\nbeta\n```",
        }
        diff_content_map = {
            "src/example.py": {
                "LEFT": {},
                "RIGHT": {10: "# prev", 11: "old1", 12: "old2", 13: "next"},
            }
        }
        self.assertEqual(_validate_suggestion_blocks(comment, diff_content_map), [])

    def test_ignores_comments_without_suggestion_blocks(self) -> None:
        comment = {
            "path": "src/example.py",
            "side": "RIGHT",
            "line": 12,
            "body": "No suggestion block here.",
        }
        diff_content_map = {
            "src/example.py": {"LEFT": {}, "RIGHT": {12: "content"}}
        }
        self.assertEqual(_validate_suggestion_blocks(comment, diff_content_map), [])

    def test_handles_missing_surrounding_context(self) -> None:
        comment = {
            "path": "src/example.py",
            "side": "RIGHT",
            "line": 12,
            "start_line": 11,
            "body": "```suggestion\nalpha\nbeta\n```",
        }
        diff_content_map = {
            "src/example.py": {"LEFT": {}, "RIGHT": {11: "old", 12: "old2"}}
        }
        self.assertEqual(_validate_suggestion_blocks(comment, diff_content_map), [])


if __name__ == "__main__":
    unittest.main()
