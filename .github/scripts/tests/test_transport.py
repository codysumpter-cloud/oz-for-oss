from __future__ import annotations

import base64
import json
import unittest
from oz_workflows.transport import parse_transport_comment, poll_for_transport_payload


def transport_comment(payload: str) -> str:
    return f"<!-- oz-workflow-transport {payload} -->"


def encoded_payload(payload: dict[str, str]) -> str:
    return base64.b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8")


class ParseTransportCommentTest(unittest.TestCase):
    def test_decodes_payload(self) -> None:
        body = transport_comment(
            json.dumps(
                {
                    "token": "abc",
                    "kind": "review-json",
                    "encoding": "base64",
                    "payload": encoded_payload({"hello": "world"}),
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
                    "encoding": "base64",
                    "payload": "%%%not-base64%%%",
                }
            )
        )
        self.assertIsNone(parse_transport_comment(body))


class PollForTransportPayloadTest(unittest.TestCase):
    def test_skips_malformed_transport_comments(self) -> None:
        valid_comment = transport_comment(
            json.dumps(
                {
                    "token": "abc",
                    "kind": "review-json",
                    "encoding": "base64",
                    "payload": encoded_payload({"hello": "world"}),
                }
            )
        )
        malformed_comment = transport_comment(
            json.dumps(
                {
                    "token": "abc",
                    "kind": "review-json",
                    "encoding": "base64",
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


if __name__ == "__main__":
    unittest.main()
