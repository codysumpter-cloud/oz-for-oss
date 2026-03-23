from __future__ import annotations

import unittest

from oz_workflows.helpers import append_comment_sections, build_comment_body


class CommentUpdateTest(unittest.TestCase):
    def test_appends_instead_of_replacing(self) -> None:
        metadata = "<!-- meta -->"
        existing = build_comment_body("@alice\n\nOz is working on this issue.\n\nSharing session at: https://example.test/session/123", metadata)
        updated = append_comment_sections(existing, metadata, ["I created a plan PR for this issue: https://example.test/pr/1"])
        self.assertIn("Sharing session at: https://example.test/session/123", updated)
        self.assertIn("I created a plan PR for this issue: https://example.test/pr/1", updated)
        self.assertTrue(updated.endswith(metadata))


if __name__ == "__main__":
    unittest.main()
