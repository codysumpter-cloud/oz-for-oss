from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from oz_workflows.env import parse_mcp_servers


class ParseMcpServersTest(unittest.TestCase):
    def test_parses_inline_json(self) -> None:
        parsed = parse_mcp_servers('{"github":{"warp_id":"123"}}', Path.cwd())
        self.assertEqual(parsed, {"github": {"warp_id": "123"}})

    def test_parses_json_file_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "mcp.json"
            config_path.write_text('{"github":{"warp_id":"123"}}', encoding="utf-8")
            parsed = parse_mcp_servers(str(config_path), Path.cwd())
            self.assertEqual(parsed, {"github": {"warp_id": "123"}})


if __name__ == "__main__":
    unittest.main()
