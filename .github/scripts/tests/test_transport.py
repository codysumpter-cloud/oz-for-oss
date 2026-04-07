from __future__ import annotations

import json
import unittest

from oz_workflows.transport import (
    BASE64_ENCODING,
    GZIP_BASE64_ENCODING,
    TRANSPORT_PATTERN,
    cleanup_transport_comments,
    encode_transport_payload,
    parse_transport_comment,
    poll_for_transport_payload,
)


def transport_comment(payload: str) -> str:
    return f"<!-- oz-workflow-transport {payload} -->"


def encoded_payload(payload: dict[str, object], *, encoding: str = GZIP_BASE64_ENCODING) -> str:
    return encode_transport_payload(json.dumps(payload), encoding=encoding)


class ParseTransportCommentTest(unittest.TestCase):
    def test_decodes_payload(self) -> None:
        body = transport_comment(
            json.dumps(
                {
                    "token": "abc",
                    "kind": "review-json",
                    "encoding": BASE64_ENCODING,
                    "payload": encoded_payload({"hello": "world"}, encoding=BASE64_ENCODING),
                }
            )
        )
        parsed = parse_transport_comment(body)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["decoded_payload"], '{"hello": "world"}')

    def test_defaults_missing_encoding_to_base64(self) -> None:
        body = transport_comment(
            json.dumps(
                {
                    "token": "abc",
                    "kind": "review-json",
                    "payload": encoded_payload({"hello": "world"}, encoding=BASE64_ENCODING),
                }
            )
        )
        parsed = parse_transport_comment(body)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["decoded_payload"], '{"hello": "world"}')

    def test_decodes_gzip_base64_payload(self) -> None:
        body = transport_comment(
            json.dumps(
                {
                    "token": "abc",
                    "kind": "review-json",
                    "encoding": GZIP_BASE64_ENCODING,
                    "payload": encoded_payload({"hello": "world"}, encoding=GZIP_BASE64_ENCODING),
                }
            )
        )
        parsed = parse_transport_comment(body)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["decoded_payload"], '{"hello": "world"}')

    def test_returns_none_for_malformed_json(self) -> None:
        body = transport_comment('{"token": "abc", "kind": }')
        self.assertIsNone(parse_transport_comment(body))

    def test_returns_none_for_invalid_base64_payload(self) -> None:
        body = transport_comment(
            json.dumps(
                {
                    "token": "abc",
                    "kind": "review-json",
                    "encoding": BASE64_ENCODING,
                    "payload": "%%%not-base64%%%",
                }
            )
        )
        self.assertIsNone(parse_transport_comment(body))

    def test_returns_none_for_invalid_gzip_payload(self) -> None:
        body = transport_comment(
            json.dumps(
                {
                    "token": "abc",
                    "kind": "review-json",
                    "encoding": GZIP_BASE64_ENCODING,
                    "payload": encoded_payload({"hello": "world"}, encoding=BASE64_ENCODING),
                }
            )
        )
        self.assertIsNone(parse_transport_comment(body))

    def test_gzip_encoding_reduces_large_review_like_payload(self) -> None:
        review_payload = {
            "summary": "Request changes",
            "comments": [
                {
                    "path": "foo.py",
                    "line": index + 1,
                    "side": "RIGHT",
                    "body": (
                        "⚠️ [IMPORTANT] "
                        + "This review comment repeats similar context and suggestion text. " * 6
                    ),
                }
                for index in range(40)
            ],
        }
        plain = encoded_payload(review_payload, encoding=BASE64_ENCODING)
        compressed = encoded_payload(review_payload, encoding=GZIP_BASE64_ENCODING)
        self.assertLess(len(compressed), len(plain))


class PollForTransportPayloadTest(unittest.TestCase):
    def test_skips_malformed_transport_comments(self) -> None:
        valid_comment = transport_comment(
            json.dumps(
                {
                    "token": "abc",
                    "kind": "review-json",
                    "encoding": BASE64_ENCODING,
                    "payload": encoded_payload({"hello": "world"}, encoding=BASE64_ENCODING),
                }
            )
        )
        malformed_comment = transport_comment(
            json.dumps(
                {
                    "token": "abc",
                    "kind": "review-json",
                    "encoding": BASE64_ENCODING,
                    "payload": "%%%not-base64%%%",
                }
            )
        )

        class FakeGitHubClient:
            def list_issue_comments(self, owner: str, repo: str, issue_number: int) -> list[dict[str, object]]:
                self.request = (owner, repo, issue_number)
                return [
                    {"id": 1, "body": valid_comment},
                    {"id": 2, "body": malformed_comment},
                ]

        github = FakeGitHubClient()
        parsed, comment_id = poll_for_transport_payload(
            github,
            "warpdotdev",
            "oz-for-oss",
            42,
            token="abc",
            kind="review-json",
            timeout_seconds=0,
            poll_interval_seconds=0,
        )

        self.assertEqual(github.request, ("warpdotdev", "oz-for-oss", 42))
        self.assertEqual(comment_id, 1)
        self.assertEqual(parsed["decoded_payload"], '{"hello": "world"}')


class CleanupTransportCommentsTest(unittest.TestCase):
    def test_deletes_transport_comments(self) -> None:
        transport_body = transport_comment(
            json.dumps(
                {
                    "token": "abc",
                    "kind": "review-json",
                    "encoding": BASE64_ENCODING,
                    "payload": encoded_payload({"hello": "world"}, encoding=BASE64_ENCODING),
                }
            )
        )

        class FakeClient:
            def __init__(self) -> None:
                self.comments: list[dict[str, object]] = [
                    {"id": 1, "body": "normal comment"},
                    {"id": 2, "body": transport_body},
                    {"id": 3, "body": "another normal comment"},
                ]
                self.deleted_ids: list[int] = []

            def list_issue_comments(self, owner: str, repo: str, issue_number: int) -> list[dict[str, object]]:
                return list(self.comments)

            def delete_comment(self, owner: str, repo: str, comment_id: int) -> None:
                self.deleted_ids.append(comment_id)
                self.comments = [c for c in self.comments if int(c["id"]) != comment_id]

        fake = FakeClient()
        cleanup_transport_comments(fake, "acme", "widgets", 42)

        self.assertEqual(fake.deleted_ids, [2])
        self.assertEqual(len(fake.comments), 2)

    def test_leaves_non_transport_comments_untouched(self) -> None:
        class FakeClient:
            def __init__(self) -> None:
                self.comments: list[dict[str, object]] = [
                    {"id": 1, "body": "normal comment"},
                    {"id": 2, "body": "another comment"},
                ]
                self.deleted_ids: list[int] = []

            def list_issue_comments(self, owner: str, repo: str, issue_number: int) -> list[dict[str, object]]:
                return list(self.comments)

            def delete_comment(self, owner: str, repo: str, comment_id: int) -> None:
                self.deleted_ids.append(comment_id)

        fake = FakeClient()
        cleanup_transport_comments(fake, "acme", "widgets", 42)

        self.assertEqual(fake.deleted_ids, [])
        self.assertEqual(len(fake.comments), 2)

    def test_swallows_errors_silently(self) -> None:
        class FakeClient:
            def list_issue_comments(self, owner: str, repo: str, issue_number: int) -> list[dict[str, object]]:
                raise RuntimeError("API error")

        # Should not raise
        cleanup_transport_comments(FakeClient(), "acme", "widgets", 42)


if __name__ == "__main__":
    unittest.main()
