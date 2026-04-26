from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from oz_workflows.comment_templates import (
    load_workflow_comment_template_config,
    render_comment_template,
)
from oz_workflows.helpers import build_next_steps_section, format_triage_start_line


def _write_config(repo_root: Path, text: str) -> Path:
    path = repo_root / ".github" / "oz" / "config.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class WorkflowCommentTemplateConfigTest(unittest.TestCase):
    def test_defaults_apply_when_workflow_comments_absent(self) -> None:
        with TemporaryDirectory() as tempdir:
            workspace_root = Path(tempdir)
            _write_config(workspace_root, "version: 1\n")

            self.assertEqual(
                render_comment_template(
                    workspace_root,
                    namespace="shared",
                    key="next_steps_section",
                    context={"next_steps_markdown": "- validate\n- ship"},
                ),
                "Next steps:\n- validate\n- ship",
            )

    def test_render_accepts_string_workspace_root(self) -> None:
        with TemporaryDirectory() as tempdir:
            workspace_root = Path(tempdir)
            _write_config(workspace_root, "version: 1\n")

            self.assertEqual(
                render_comment_template(
                    str(workspace_root),
                    namespace="triage-new-issues",
                    key="start_new",
                ),
                "I'm starting to work on triaging this issue.",
            )

    def test_helper_functions_use_configured_overrides(self) -> None:
        with TemporaryDirectory() as tempdir:
            workspace_root = Path(tempdir)
            _write_config(
                workspace_root,
                (
                    "version: 1\n"
                    "workflow_comments:\n"
                    "  shared:\n"
                    "    next_steps_section: |-\n"
                    "      Do this next:\n"
                    "      ${next_steps_markdown}\n"
                    "  triage-new-issues:\n"
                    "    start_new: Custom triage start.\n"
                ),
            )

            with patch("oz_workflows.helpers.workspace", return_value=str(workspace_root)):
                self.assertEqual(
                    build_next_steps_section(["collect logs", "retry"]),
                    "Do this next:\n- collect logs\n- retry",
                )
                self.assertEqual(
                    format_triage_start_line(is_retriage=False),
                    "Custom triage start.",
                )

    def test_falls_back_to_workflow_repo_config_for_templates(self) -> None:
        with TemporaryDirectory() as tempdir:
            workspace_root = Path(tempdir)
            workflow_root = workspace_root / "__oz_shared"
            _write_config(
                workflow_root,
                (
                    "version: 1\n"
                    "workflow_comments:\n"
                    "  shared:\n"
                    "    next_steps_section: |-\n"
                    "      Workflow fallback:\n"
                    "      ${next_steps_markdown}\n"
                ),
            )

            with patch.dict(
                os.environ,
                {
                    "GITHUB_WORKSPACE": str(workspace_root),
                    "WORKFLOW_CODE_PATH": "__oz_shared",
                },
                clear=False,
            ):
                self.assertEqual(
                    render_comment_template(
                        workspace_root,
                        namespace="shared",
                        key="next_steps_section",
                        context={"next_steps_markdown": "- from fallback"},
                    ),
                    "Workflow fallback:\n- from fallback",
                )

    def test_invalid_workflow_comment_config_cases(self) -> None:
        cases = [
            (
                "unknown_namespace",
                (
                    "version: 1\n"
                    "workflow_comments:\n"
                    "  made-up:\n"
                    "    start: nope\n"
                ),
                "Unknown workflow_comments namespace",
            ),
            (
                "unknown_key",
                (
                    "version: 1\n"
                    "workflow_comments:\n"
                    "  triage-new-issues:\n"
                    "    made_up: nope\n"
                ),
                "Unknown workflow comment template key",
            ),
            (
                "blank_value",
                (
                    "version: 1\n"
                    "workflow_comments:\n"
                    "  triage-new-issues:\n"
                    "    start_new: \"   \"\n"
                ),
                "must not be blank",
            ),
            (
                "non_string_value",
                (
                    "version: 1\n"
                    "workflow_comments:\n"
                    "  triage-new-issues:\n"
                    "    start_new: 42\n"
                ),
                "must be a string",
            ),
            (
                "invalid_placeholder_syntax",
                (
                    "version: 1\n"
                    "workflow_comments:\n"
                    "  shared:\n"
                    "    next_steps_section: \"Next: $next_steps_markdown\"\n"
                ),
                "Invalid placeholder syntax",
            ),
            (
                "unknown_placeholder",
                (
                    "version: 1\n"
                    "workflow_comments:\n"
                    "  shared:\n"
                    "    next_steps_section: \"Next: ${unknown_value}\"\n"
                ),
                "Unknown placeholders",
            ),
        ]
        for label, contents, expected in cases:
            with self.subTest(label=label):
                with TemporaryDirectory() as tempdir:
                    workspace_root = Path(tempdir)
                    config_path = _write_config(workspace_root, contents)

                    with self.assertRaises(RuntimeError) as ctx:
                        load_workflow_comment_template_config(workspace_root)

                    self.assertIn(str(config_path), str(ctx.exception))
                    self.assertIn(expected, str(ctx.exception))

    def test_render_requires_all_placeholder_values(self) -> None:
        with TemporaryDirectory() as tempdir:
            workspace_root = Path(tempdir)
            _write_config(workspace_root, "version: 1\n")

            with self.assertRaises(RuntimeError) as ctx:
                render_comment_template(
                    workspace_root,
                    namespace="shared",
                    key="spec_preview",
                    context={
                        "product_path": "specs/GH1/product.md",
                        "product_url": "https://example.test/product",
                    },
                )

            self.assertIn("Missing placeholder values", str(ctx.exception))
            self.assertIn("tech_path", str(ctx.exception))
            self.assertIn("tech_url", str(ctx.exception))

    def test_render_includes_config_path_for_missing_override_placeholder(self) -> None:
        with TemporaryDirectory() as tempdir:
            workspace_root = Path(tempdir)
            config_path = _write_config(
                workspace_root,
                (
                    "version: 1\n"
                    "workflow_comments:\n"
                    "  shared:\n"
                    "    spec_preview: \"Preview: ${product_path}\"\n"
                ),
            )

            with self.assertRaises(RuntimeError) as ctx:
                render_comment_template(
                    workspace_root,
                    namespace="shared",
                    key="spec_preview",
                    context={},
                )

            self.assertIn(str(config_path), str(ctx.exception))
            self.assertIn("Missing placeholder values", str(ctx.exception))
            self.assertIn("product_path", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
