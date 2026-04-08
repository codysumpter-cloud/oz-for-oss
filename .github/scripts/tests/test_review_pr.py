from __future__ import annotations

import unittest

from review_pr import _commentable_lines_for_patch, _normalize_review_payload


class CommentableLinesForPatchTest(unittest.TestCase):
    def test_tracks_valid_left_and_right_lines_from_patch(self) -> None:
        patch = """@@ -10,3 +10,4 @@
 context
-old_value
+new_value
 unchanged
"""
        result = _commentable_lines_for_patch(patch)
        self.assertEqual(result["LEFT"], {11})
        self.assertEqual(result["RIGHT"], {10, 11, 12})


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

    def test_rejects_comment_for_file_outside_diff(self) -> None:
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

        with self.assertRaisesRegex(
            ValueError, "not part of the PR diff"
        ):
            _normalize_review_payload(
                review,
                {"src/example.py": {"LEFT": set(), "RIGHT": {1, 2, 3}}},
            )

    def test_rejects_comment_for_non_commentable_line(self) -> None:
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

        with self.assertRaisesRegex(
            ValueError, "not commentable in the PR diff"
        ):
            _normalize_review_payload(
                review,
                {"src/example.py": {"LEFT": {11}, "RIGHT": {10, 11, 12}}},
            )


if __name__ == "__main__":
    unittest.main()
