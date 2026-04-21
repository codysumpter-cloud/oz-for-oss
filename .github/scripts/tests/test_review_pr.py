from __future__ import annotations

import unittest

from review_pr import (
    _build_diff_line_map,
    _commentable_lines_for_patch,
    _extract_suggestion_blocks,
    _line_content_for_patch,
    _normalize_review_path,
    _normalize_review_payload,
    _validate_suggestion_blocks,
)


class _FakeFile:
    def __init__(self, filename: str, patch: str | None) -> None:
        self.filename = filename
        self.patch = patch


class NormalizeReviewPathTest(unittest.TestCase):
    def test_normalization_table(self) -> None:
        cases = [
            ("strips_a_prefix", "a/src/file.py", "src/file.py"),
            ("strips_b_prefix", "b/src/file.py", "src/file.py"),
            ("strips_dot_slash_prefix", "./src/file.py", "src/file.py"),
            (
                "does_not_double_strip_a_b_path",
                "a/b/real_dir/file.py",
                "b/real_dir/file.py",
            ),
            ("no_prefix", "src/file.py", "src/file.py"),
            ("none_value", None, ""),
            ("empty_string", "", ""),
            ("whitespace_stripped", "  a/src/file.py  ", "src/file.py"),
        ]
        for label, path, expected in cases:
            with self.subTest(label=label):
                self.assertEqual(_normalize_review_path(path), expected)


class CommentableLinesForPatchTest(unittest.TestCase):
    def test_commentable_lines_table(self) -> None:
        single_hunk = """@@ -10,3 +10,4 @@
 context
-old_value
+new_value
 unchanged
"""
        context_hunk = """@@ -5,3 +5,3 @@
 context_a
-removed
+added
 context_b
"""
        multi_hunk = """@@ -1,3 +1,3 @@
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
        cases = [
            (
                "single_hunk_tracks_left_and_right",
                single_hunk,
                {10, 11, 12},
                {10, 11, 12},
            ),
            (
                "context_lines_commentable_on_left_and_right",
                context_hunk,
                {5, 6, 7},
                {5, 6, 7},
            ),
            (
                "multi_hunk_patch_tracks_each_hunk",
                multi_hunk,
                {1, 2, 3, 20, 21, 22},
                {1, 2, 3, 20, 21, 22},
            ),
            ("empty_patch", "", set(), set()),
            ("none_patch", None, set(), set()),
        ]
        for label, patch, expected_left, expected_right in cases:
            with self.subTest(label=label):
                result = _commentable_lines_for_patch(patch)
                self.assertEqual(result["LEFT"], expected_left)
                self.assertEqual(result["RIGHT"], expected_right)


class BuildDiffLineMapTest(unittest.TestCase):
    def test_builds_map_from_file_list(self) -> None:
        files = [
            _FakeFile(
                "src/example.py",
                "@@ -1,3 +1,3 @@\n ctx\n-old\n+new\n ctx\n",
            )
        ]
        result = _build_diff_line_map(files)
        self.assertIn("src/example.py", result)
        self.assertIn(2, result["src/example.py"]["LEFT"])
        self.assertIn(2, result["src/example.py"]["RIGHT"])

    def test_normalizes_file_paths(self) -> None:
        files = [_FakeFile("a/src/example.py", "")]
        result = _build_diff_line_map(files)
        self.assertIn("src/example.py", result)
        self.assertNotIn("a/src/example.py", result)

    def test_empty_file_list(self) -> None:
        self.assertEqual(_build_diff_line_map([]), {})


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

    def test_drop_table(self) -> None:
        """Comments with invalid path/line/body/start_line are dropped.

        Each case provides a single-comment review plus the diff context,
        and asserts that the comment is dropped (normalized output is
        empty).
        """
        default_line_map = {
            "src/example.py": {"LEFT": set(), "RIGHT": {10}}
        }
        duplicate_prefix_line_map = {
            "src/example.py": {"LEFT": set(), "RIGHT": {10, 11, 12, 13}}
        }
        duplicate_prefix_content_map = {
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
        duplicate_suffix_content_map = {
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
        cases = [
            (
                "file_outside_diff",
                {
                    "path": "src/missing.py",
                    "line": 12,
                    "side": "RIGHT",
                    "body": "💡 [SUGGESTION] Mentioned file is outside the diff.",
                },
                {"src/example.py": {"LEFT": set(), "RIGHT": {1, 2, 3}}},
                None,
            ),
            (
                "non_commentable_line",
                {
                    "path": "src/example.py",
                    "line": 99,
                    "side": "RIGHT",
                    "body": "⚠️ [IMPORTANT] Wrong line.",
                },
                {"src/example.py": {"LEFT": {11}, "RIGHT": {10, 11, 12}}},
                None,
            ),
            (
                "invalid_start_line_greater_than_line",
                {
                    "path": "src/example.py",
                    "line": 10,
                    "start_line": 15,
                    "side": "RIGHT",
                    "body": "start_line >= line.",
                },
                {"src/example.py": {"LEFT": set(), "RIGHT": {10, 11, 12, 15}}},
                None,
            ),
            (
                "non_commentable_start_line",
                {
                    "path": "src/example.py",
                    "line": 12,
                    "start_line": 8,
                    "side": "RIGHT",
                    "body": "start_line not in diff.",
                },
                {"src/example.py": {"LEFT": set(), "RIGHT": {10, 11, 12}}},
                None,
            ),
            (
                "missing_body",
                {
                    "path": "src/example.py",
                    "line": 10,
                    "side": "RIGHT",
                    "body": "",
                },
                default_line_map,
                None,
            ),
            (
                "missing_path",
                {"line": 10, "side": "RIGHT", "body": "No path."},
                {},
                None,
            ),
            (
                "non_integer_line",
                {
                    "path": "src/example.py",
                    "line": "ten",
                    "side": "RIGHT",
                    "body": "Bad line.",
                },
                default_line_map,
                None,
            ),
            (
                "duplicate_prefix_suggestion",
                {
                    "path": "src/example.py",
                    "line": 12,
                    "start_line": 11,
                    "side": "RIGHT",
                    "body": "\u26a0\ufe0f [IMPORTANT] Fix.\n\n```suggestion\n# comment above\nnew_body()\n```",
                },
                duplicate_prefix_line_map,
                duplicate_prefix_content_map,
            ),
            (
                "duplicate_suffix_suggestion",
                {
                    "path": "src/example.py",
                    "line": 12,
                    "start_line": 11,
                    "side": "RIGHT",
                    "body": "\u26a0\ufe0f [IMPORTANT] Fix.\n\n```suggestion\nnew_body()\nreturn value\n```",
                },
                duplicate_prefix_line_map,
                duplicate_suffix_content_map,
            ),
        ]
        for label, comment, diff_line_map, diff_content_map in cases:
            with self.subTest(label=label):
                review = {"summary": "", "comments": [comment]}
                if diff_content_map is None:
                    _summary, comments = _normalize_review_payload(
                        review, diff_line_map
                    )
                else:
                    _summary, comments = _normalize_review_payload(
                        review, diff_line_map, diff_content_map
                    )
                self.assertEqual(comments, [])

    def test_drops_non_dict_comment_entry(self) -> None:
        review = {"summary": "", "comments": ["not a dict"]}
        _summary, comments = _normalize_review_payload(review, {})
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

    def test_strips_trailing_cr_from_crlf_bodies(self) -> None:
        body = "Prefix.\r\n\r\n```suggestion\r\nfoo()\r\nbar()\r\n```\r\n"
        blocks = _extract_suggestion_blocks(body)
        self.assertEqual(blocks, [["foo()", "bar()"]])


class ValidateSuggestionBlocksTest(unittest.TestCase):
    def test_duplicate_context_cases(self) -> None:
        """Each case asserts ``_validate_suggestion_blocks`` emits the
        expected error (or none)."""
        cases = [
            (
                "flags_duplicate_prefix",
                {
                    "path": "src/example.py",
                    "side": "RIGHT",
                    "line": 12,
                    "start_line": 11,
                    "body": "```suggestion\n# header\nbody()\n```",
                },
                {
                    "src/example.py": {
                        "LEFT": {},
                        "RIGHT": {10: "# header", 11: "old", 12: "end"},
                    }
                },
                "duplicates the context line immediately above",
            ),
            (
                "flags_duplicate_suffix",
                {
                    "path": "src/example.py",
                    "side": "RIGHT",
                    "line": 12,
                    "body": "```suggestion\nbody()\nfooter\n```",
                },
                {
                    "src/example.py": {
                        "LEFT": {},
                        "RIGHT": {12: "old", 13: "footer"},
                    }
                },
                "duplicates the context line immediately below",
            ),
            (
                "returns_no_errors_for_valid_block",
                {
                    "path": "src/example.py",
                    "side": "RIGHT",
                    "line": 12,
                    "start_line": 11,
                    "body": "```suggestion\nalpha\nbeta\n```",
                },
                {
                    "src/example.py": {
                        "LEFT": {},
                        "RIGHT": {
                            10: "# prev",
                            11: "old1",
                            12: "old2",
                            13: "next",
                        },
                    }
                },
                None,
            ),
            (
                "ignores_comments_without_suggestion_blocks",
                {
                    "path": "src/example.py",
                    "side": "RIGHT",
                    "line": 12,
                    "body": "No suggestion block here.",
                },
                {"src/example.py": {"LEFT": {}, "RIGHT": {12: "content"}}},
                None,
            ),
            (
                "handles_missing_surrounding_context",
                {
                    "path": "src/example.py",
                    "side": "RIGHT",
                    "line": 12,
                    "start_line": 11,
                    "body": "```suggestion\nalpha\nbeta\n```",
                },
                {
                    "src/example.py": {
                        "LEFT": {},
                        "RIGHT": {11: "old", 12: "old2"},
                    }
                },
                None,
            ),
        ]
        for label, comment, content_map, expected_substring in cases:
            with self.subTest(label=label):
                errors = _validate_suggestion_blocks(comment, content_map)
                if expected_substring is None:
                    self.assertEqual(errors, [])
                else:
                    self.assertEqual(len(errors), 1)
                    self.assertIn(expected_substring, errors[0])


if __name__ == "__main__":
    unittest.main()
