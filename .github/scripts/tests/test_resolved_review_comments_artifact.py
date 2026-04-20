from __future__ import annotations

import json
import unittest
from unittest.mock import Mock, patch

import httpx

from oz_workflows.artifacts import (
    RESOLVED_REVIEW_COMMENTS_FILENAME,
    normalize_resolved_review_comments_payload,
    try_load_resolved_review_comments_artifact,
)


class NormalizeResolvedReviewCommentsPayloadTest(unittest.TestCase):
    def test_returns_empty_for_none_payload(self) -> None:
        self.assertEqual(normalize_resolved_review_comments_payload(None), [])

    def test_returns_empty_for_empty_payload(self) -> None:
        self.assertEqual(normalize_resolved_review_comments_payload({}), [])

    def test_accepts_wrapped_object_payload(self) -> None:
        payload = {
            "resolved_review_comments": [
                {"comment_id": 111, "summary": "Fixed the validation bug."},
                {"comment_id": 222, "summary": "Renamed variable in foo.py."},
            ]
        }
        self.assertEqual(
            normalize_resolved_review_comments_payload(payload),
            [
                {"comment_id": 111, "summary": "Fixed the validation bug."},
                {"comment_id": 222, "summary": "Renamed variable in foo.py."},
            ],
        )

    def test_accepts_bare_list_payload(self) -> None:
        payload = [
            {"comment_id": 111, "summary": "Addressed review feedback."},
        ]
        self.assertEqual(
            normalize_resolved_review_comments_payload(payload),
            [{"comment_id": 111, "summary": "Addressed review feedback."}],
        )

    def test_strips_whitespace_from_summary(self) -> None:
        payload = {
            "resolved_review_comments": [
                {"comment_id": 111, "summary": "  Trimmed summary.  "},
            ]
        }
        self.assertEqual(
            normalize_resolved_review_comments_payload(payload),
            [{"comment_id": 111, "summary": "Trimmed summary."}],
        )

    def test_drops_entries_missing_comment_id(self) -> None:
        payload = {
            "resolved_review_comments": [
                {"summary": "No comment id."},
                {"comment_id": 111, "summary": "Valid entry."},
            ]
        }
        self.assertEqual(
            normalize_resolved_review_comments_payload(payload),
            [{"comment_id": 111, "summary": "Valid entry."}],
        )

    def test_drops_entries_with_non_positive_comment_id(self) -> None:
        payload = {
            "resolved_review_comments": [
                {"comment_id": 0, "summary": "Zero id."},
                {"comment_id": -12, "summary": "Negative id."},
                {"comment_id": 111, "summary": "Valid."},
            ]
        }
        self.assertEqual(
            normalize_resolved_review_comments_payload(payload),
            [{"comment_id": 111, "summary": "Valid."}],
        )

    def test_drops_entries_with_boolean_comment_id(self) -> None:
        payload = {
            "resolved_review_comments": [
                {"comment_id": True, "summary": "Boolean masquerading as int."},
            ]
        }
        self.assertEqual(normalize_resolved_review_comments_payload(payload), [])

    def test_coerces_string_comment_id(self) -> None:
        payload = {
            "resolved_review_comments": [
                {"comment_id": "123", "summary": "String id coerced."},
            ]
        }
        self.assertEqual(
            normalize_resolved_review_comments_payload(payload),
            [{"comment_id": 123, "summary": "String id coerced."}],
        )

    def test_drops_entries_missing_summary(self) -> None:
        payload = {
            "resolved_review_comments": [
                {"comment_id": 111},
                {"comment_id": 222, "summary": ""},
                {"comment_id": 333, "summary": "   "},
                {"comment_id": 444, "summary": "Kept."},
            ]
        }
        self.assertEqual(
            normalize_resolved_review_comments_payload(payload),
            [{"comment_id": 444, "summary": "Kept."}],
        )

    def test_drops_non_dict_entries(self) -> None:
        payload = {
            "resolved_review_comments": [
                "not a dict",
                123,
                {"comment_id": 111, "summary": "Survives."},
            ]
        }
        self.assertEqual(
            normalize_resolved_review_comments_payload(payload),
            [{"comment_id": 111, "summary": "Survives."}],
        )

    def test_deduplicates_by_comment_id(self) -> None:
        payload = {
            "resolved_review_comments": [
                {"comment_id": 111, "summary": "First entry."},
                {"comment_id": 111, "summary": "Duplicate id."},
            ]
        }
        self.assertEqual(
            normalize_resolved_review_comments_payload(payload),
            [{"comment_id": 111, "summary": "First entry."}],
        )

    def test_returns_empty_when_resolved_review_comments_not_a_list(self) -> None:
        payload = {"resolved_review_comments": "not a list"}
        self.assertEqual(normalize_resolved_review_comments_payload(payload), [])


class TryLoadResolvedReviewCommentsArtifactTest(unittest.TestCase):
    @patch("oz_workflows.artifacts.poll_for_artifact")
    def test_returns_normalized_entries_when_artifact_present(
        self, mock_poll
    ) -> None:
        mock_poll.return_value = {
            "resolved_review_comments": [
                {"comment_id": 999, "summary": "Applied the fix."},
            ]
        }
        result = try_load_resolved_review_comments_artifact(
            "run-abc", timeout_seconds=0, poll_interval_seconds=0
        )
        self.assertEqual(
            result,
            [{"comment_id": 999, "summary": "Applied the fix."}],
        )
        mock_poll.assert_called_once_with(
            "run-abc",
            filename=RESOLVED_REVIEW_COMMENTS_FILENAME,
            timeout_seconds=0,
            poll_interval_seconds=0,
        )

    @patch("oz_workflows.artifacts.poll_for_artifact")
    def test_returns_empty_list_on_recoverable_load_failures(self, mock_poll) -> None:
        """Every recoverable failure path returns ``[]`` instead of raising."""
        request = httpx.Request("GET", "https://example.test/signed")
        response = Mock(spec=httpx.Response, status_code=404, request=request)
        cases = [
            (
                "artifact_missing_timeout",
                RuntimeError("Timed out waiting for FILE artifact"),
            ),
            (
                "malformed_json",
                json.JSONDecodeError("malformed", "doc", 0),
            ),
            (
                "http_status_error",
                httpx.HTTPStatusError(
                    "not found", request=request, response=response
                ),
            ),
            (
                "transient_http_error",
                httpx.ReadTimeout("timeout"),
            ),
        ]
        for label, exc in cases:
            with self.subTest(label=label):
                mock_poll.reset_mock()
                mock_poll.side_effect = exc
                result = try_load_resolved_review_comments_artifact(
                    "run-abc", timeout_seconds=0, poll_interval_seconds=0
                )
                self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
