from __future__ import annotations

import unittest

from oz_workflows.helpers import extract_issue_numbers_from_text


class ExtractIssueNumbersTest(unittest.TestCase):
    def test_extracts_hash_and_url_references(self) -> None:
        text = "Fixes #12 and refs https://github.com/acme/widgets/issues/34"
        self.assertEqual(extract_issue_numbers_from_text("acme", "widgets", text), [12, 34])


if __name__ == "__main__":
    unittest.main()
