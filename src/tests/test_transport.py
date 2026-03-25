from __future__ import annotations

import base64
import json
import unittest

from oz_workflows.transport import parse_transport_comment


class ParseTransportCommentTest(unittest.TestCase):
    def test_decodes_payload(self) -> None:
        encoded = base64.b64encode(json.dumps({"hello": "world"}).encode("utf-8")).decode("utf-8")
        body = (
            '<!-- oz-workflow-transport '
            + json.dumps(
                {
                    "token": "abc",
                    "kind": "review-json",
                    "encoding": "base64",
                    "payload": encoded,
                }
            )
            + " -->"
        )
        parsed = parse_transport_comment(body)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["decoded_payload"], '{"hello": "world"}')


if __name__ == "__main__":
    unittest.main()
