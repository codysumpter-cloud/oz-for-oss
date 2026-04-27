from __future__ import annotations

import importlib.util
import io
import os
import sys
import unittest
from base64 import b64encode
from pathlib import Path
from unittest.mock import patch


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
    def test_manual_linked_issues_query_has_balanced_braces(self) -> None:
        self.assertEqual(
            self.module._MANUAL_LINKED_ISSUES_QUERY.count("{"),
            self.module._MANUAL_LINKED_ISSUES_QUERY.count("}"),
        )

    def test_prints_no_context_message_when_nothing_matches(self) -> None:
        stdout = io.StringIO()

        with (
            patch.dict(os.environ, {"GH_TOKEN": "token"}, clear=False),
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
            "owner",
            "repo",
            7,
            workspace=self.module.REPO_ROOT,
            token="token",
        )

    def test_formats_approved_spec_pr_entries(self) -> None:
        stdout = io.StringIO()

        with (
            patch.dict(os.environ, {"GH_TOKEN": "token"}, clear=False),
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

    def test_fetch_file_contents_decodes_base64_response(self) -> None:
        encoded = b64encode(b"Spec body\n").decode("utf-8")
        with patch.object(
            self.module,
            "_gh_json",
            return_value=(
                200,
                {
                    "encoding": "base64",
                    "content": encoded,
                },
            ),
        ) as gh_json:
            content = self.module._fetch_file_contents(
                "owner",
                "repo",
                "specs/GH7/product.md",
                ref="feature-branch",
                token="token",
            )

        self.assertEqual(content, "Spec body")
        gh_json.assert_called_once_with(
            "/repos/owner/repo/contents/specs/GH7/product.md",
            token="token",
            params={"ref": "feature-branch"},
            allow_http_error=True,
        )

    def test_resolve_spec_context_for_pr_uses_http_fetch_helpers(self) -> None:
        with (
            patch.object(
                self.module,
                "_fetch_pull",
                return_value={"head": {"ref": "oz-agent/implement-issue-7"}},
            ) as fetch_pull,
            patch.object(
                self.module,
                "_fetch_pull_files",
                return_value=[{"filename": ".github/scripts/review_pr.py"}],
            ) as fetch_pull_files,
            patch.object(
                self.module,
                "resolve_issue_number_for_pr",
                return_value=7,
            ) as resolve_issue,
            patch.object(
                self.module,
                "resolve_spec_context_for_issue",
                return_value={
                    "selected_spec_pr": None,
                    "approved_spec_prs": [],
                    "unapproved_spec_prs": [],
                    "spec_context_source": "directory",
                    "spec_entries": [{"path": "specs/GH7/product.md", "content": "Spec"}],
                },
            ) as resolve_context,
        ):
            result = self.module.resolve_spec_context_for_pr(
                "owner",
                "repo",
                7,
                workspace=Path("/tmp/workspace"),
                token="token",
            )

        fetch_pull.assert_called_once_with("owner", "repo", 7, token="token")
        fetch_pull_files.assert_called_once_with("owner", "repo", 7, token="token")
        resolve_issue.assert_called_once_with(
            "owner",
            "repo",
            7,
            {"head": {"ref": "oz-agent/implement-issue-7"}},
            [".github/scripts/review_pr.py"],
            token="token",
        )
        resolve_context.assert_called_once_with(
            "owner",
            "repo",
            7,
            workspace=Path("/tmp/workspace"),
            token="token",
        )
        self.assertEqual(result["issue_number"], 7)
        self.assertEqual(result["changed_files"], [".github/scripts/review_pr.py"])


if __name__ == "__main__":
    unittest.main()
