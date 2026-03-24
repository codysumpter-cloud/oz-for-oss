from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from triage_new_issues import format_issue_comments, resolve_issue_number_override

from oz_workflows.triage import (
    ORIGINAL_REPORT_END,
    ORIGINAL_REPORT_START,
    compose_triaged_issue_body,
    dedupe_strings,
    discover_issue_templates,
    extract_original_issue_report,
    load_triage_config,
    select_recent_untriaged_issues,
)


class LoadTriageConfigTest(unittest.TestCase):
    def test_loads_valid_json_config(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text(
                '{"labels":{"triaged":{"color":"0E8A16","description":"done"}},"stakeholders":[]}',
                encoding="utf-8",
            )
            parsed = load_triage_config(config_path)
            self.assertIn("labels", parsed)
            self.assertIn("stakeholders", parsed)


class DedupeStringsTest(unittest.TestCase):
    def test_preserves_order_while_deduplicating(self) -> None:
        self.assertEqual(dedupe_strings(["triaged", "bug", "triaged", "bug", "area:cli"]), ["triaged", "bug", "area:cli"])


class SelectRecentUntriagedIssuesTest(unittest.TestCase):
    def test_filters_old_triaged_and_pull_request_entries(self) -> None:
        cutoff = datetime(2026, 3, 24, 1, 0, tzinfo=timezone.utc)
        issues = [
            {
                "number": 1,
                "created_at": "2026-03-24T00:30:00Z",
                "labels": [],
            },
            {
                "number": 2,
                "created_at": "2026-03-24T01:15:00Z",
                "labels": [{"name": "triaged"}],
            },
            {
                "number": 3,
                "created_at": "2026-03-24T01:20:00Z",
                "labels": [],
                "pull_request": {"url": "https://example.test/pr/3"},
            },
            {
                "number": 4,
                "created_at": "2026-03-24T01:25:00Z",
                "labels": [{"name": "bug"}],
            },
        ]
        self.assertEqual(
            [issue["number"] for issue in select_recent_untriaged_issues(issues, cutoff=cutoff)],
            [4],
        )


class DiscoverIssueTemplatesTest(unittest.TestCase):
    def test_discovers_config_template_and_legacy_template(self) -> None:
        with TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            template_dir = workspace / ".github" / "ISSUE_TEMPLATE"
            template_dir.mkdir(parents=True)
            (template_dir / "config.yml").write_text("blank_issues_enabled: false\n", encoding="utf-8")
            (template_dir / "bug.yml").write_text("name: Bug Report\ndescription: File a bug\n", encoding="utf-8")
            (workspace / ".github" / "issue_template.md").write_text("---\nname: Legacy\nabout: Legacy template\n---\nBody", encoding="utf-8")
            result = discover_issue_templates(workspace)
            self.assertEqual(result["config"]["path"], ".github/ISSUE_TEMPLATE/config.yml")
            self.assertEqual(
                [template["path"] for template in result["templates"]],
                [".github/ISSUE_TEMPLATE/bug.yml", ".github/issue_template.md"],
            )


class PreservedOriginalReportTest(unittest.TestCase):
    def test_extracts_original_report_from_preserved_details_block(self) -> None:
        body = (
            "## Bug report\nStructured content\n\n"
            + ORIGINAL_REPORT_START
            + "\n<details>\n<summary>Original issue report</summary>\n\nOriginal report text\n\n</details>\n"
            + ORIGINAL_REPORT_END
        )
        self.assertEqual(extract_original_issue_report(body), "Original report text")

    def test_composes_visible_body_with_preserved_original_report(self) -> None:
        updated = compose_triaged_issue_body("## Bug report\nStructured content", "Original report text")
        self.assertIn("## Bug report\nStructured content", updated)
        self.assertIn(ORIGINAL_REPORT_START, updated)
        self.assertIn(ORIGINAL_REPORT_END, updated)
        self.assertIn("<summary>Original issue report</summary>", updated)
        self.assertIn("Original report text", updated)
class ResolveIssueNumberOverrideTest(unittest.TestCase):
    def test_uses_issue_number_from_issue_comment_event(self) -> None:
        self.assertEqual(
            resolve_issue_number_override("issue_comment", {"issue": {"number": 42}}),
            "42",
        )

    def test_uses_issue_number_from_issue_opened_event(self) -> None:
        self.assertEqual(
            resolve_issue_number_override("issues", {"issue": {"number": 84}}),
            "84",
        )


class FormatIssueCommentsTest(unittest.TestCase):
    def test_can_exclude_triggering_comment(self) -> None:
        rendered = format_issue_comments(
            [
                {
                    "id": 1,
                    "author_association": "MEMBER",
                    "created_at": "2026-03-24T00:00:00Z",
                    "body": "Earlier context",
                    "user": {"login": "alice"},
                },
                {
                    "id": 2,
                    "author_association": "MEMBER",
                    "created_at": "2026-03-24T01:00:00Z",
                    "body": "@oz-agent focus on repro",
                    "user": {"login": "alice"},
                },
            ],
            exclude_comment_id=2,
        )
        self.assertEqual(rendered, "- @alice [MEMBER] (2026-03-24T00:00:00Z): Earlier context")


if __name__ == "__main__":
    unittest.main()
