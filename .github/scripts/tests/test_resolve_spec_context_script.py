from __future__ import annotations

import importlib.util
import io
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def _load_module():
    repo_root = Path(__file__).resolve().parents[3]
    script_path = (
        repo_root
        / ".agents"
        / "skills"
        / "review-pr"
        / "scripts"
        / "resolve_spec_context.py"
    )
    spec = importlib.util.spec_from_file_location(
        "resolve_spec_context_script",
        script_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ResolveSpecContextScriptTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = _load_module()

    def test_prints_no_context_message_when_nothing_matches(self) -> None:
        client = MagicMock()
        client.close = MagicMock()
        repo = MagicMock()
        pr = MagicMock()
        repo.get_pull.return_value = pr
        client.get_repo.return_value = repo
        stdout = io.StringIO()

        with (
            patch.dict(os.environ, {"GH_TOKEN": "token"}, clear=False),
            patch.object(self.module, "Github", return_value=client),
            patch.object(self.module.Auth, "Token", return_value="token"),
            patch.object(
                self.module,
                "resolve_spec_context_for_pr",
                return_value={
                    "selected_spec_pr": None,
                    "spec_context_source": "",
                    "spec_entries": [],
                },
            ) as resolve_mock,
            patch.object(sys, "argv", ["resolve_spec_context.py", "--repo", "owner/repo", "--pr", "7"]),
            patch("sys.stdout", stdout),
        ):
            self.module.main()

        self.assertEqual(
            stdout.getvalue().strip(),
            self.module.NO_SPEC_CONTEXT_MESSAGE,
        )
        resolve_mock.assert_called_once_with(
            repo,
            "owner",
            "repo",
            pr,
            workspace=self.module.REPO_ROOT,
        )

    def test_formats_approved_spec_pr_entries(self) -> None:
        client = MagicMock()
        client.close = MagicMock()
        repo = MagicMock()
        repo.get_pull.return_value = SimpleNamespace()
        client.get_repo.return_value = repo
        stdout = io.StringIO()

        with (
            patch.dict(os.environ, {"GH_TOKEN": "token"}, clear=False),
            patch.object(self.module, "Github", return_value=client),
            patch.object(self.module.Auth, "Token", return_value="token"),
            patch.object(
                self.module,
                "resolve_spec_context_for_pr",
                return_value={
                    "selected_spec_pr": {
                        "number": 11,
                        "url": "https://github.com/owner/repo/pull/11",
                    },
                    "spec_context_source": "approved-pr",
                    "spec_entries": [
                        {"path": "specs/GH7/product.md", "content": "Product spec"},
                        {"path": "specs/GH7/tech.md", "content": "Tech spec"},
                    ],
                },
            ),
            patch.object(sys, "argv", ["resolve_spec_context.py", "--repo", "owner/repo", "--pr", "7"]),
            patch("sys.stdout", stdout),
        ):
            self.module.main()

        rendered = stdout.getvalue().strip()
        self.assertIn("Linked approved spec PR: [#11](https://github.com/owner/repo/pull/11)", rendered)
        self.assertIn("## specs/GH7/product.md", rendered)
        self.assertIn("Product spec", rendered)
        self.assertIn("## specs/GH7/tech.md", rendered)
        self.assertIn("Tech spec", rendered)


if __name__ == "__main__":
    unittest.main()
