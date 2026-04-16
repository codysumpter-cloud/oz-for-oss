from __future__ import annotations

import unittest

from review_pr import (
    _build_diff_line_map,
    _commentable_lines_for_patch,
    _normalize_review_path,
    _normalize_review_payload,
)


class _FakeFile:
    def __init__(self, filename: str, patch: str | None) -> None:
        self.filename = filename
        self.patch = patch


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


if __name__ == "__main__":
    unittest.main()
