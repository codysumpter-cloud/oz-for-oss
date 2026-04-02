from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from triage_new_issues import (
    apply_triage_result,
    build_duplicate_comment,
    build_follow_up_comment,
    extract_duplicate_of,
    extract_follow_up_questions,
    format_issue_comments,
    resolve_issue_number_override,
    sync_duplicate_comment,
    sync_follow_up_comment,
)

from oz_workflows.triage import (
    ORIGINAL_REPORT_END,
    ORIGINAL_REPORT_START,
    compose_triaged_issue_body,
    dedupe_strings,
    discover_issue_templates,
    extract_original_issue_report,
    format_stakeholders_for_prompt,
    load_stakeholders,
    load_triage_config,
    select_recent_untriaged_issues,
)


class LoadTriageConfigTest(unittest.TestCase):
    def test_loads_valid_json_config(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text(
                '{"labels":{"triaged":{"color":"0E8A16","description":"done"}}}',
                encoding="utf-8",
            )
            parsed = load_triage_config(config_path)
            self.assertIn("labels", parsed)
            self.assertNotIn("stakeholders", parsed)
            self.assertNotIn("default_experts", parsed)

    def test_loads_config_without_stakeholders_key(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text(
                '{"labels":{"bug":{"color":"D73A4A","description":"bug"}}}',
                encoding="utf-8",
            )
            parsed = load_triage_config(config_path)
            self.assertIn("labels", parsed)

    def test_rejects_config_without_labels(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text('{"other": "value"}', encoding="utf-8")
            with self.assertRaises(RuntimeError):
                load_triage_config(config_path)


class LoadStakeholdersTest(unittest.TestCase):
    def test_parses_stakeholders_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "STAKEHOLDERS"
            path.write_text(
                "# Comment line\n"
                "/src/ @alice @bob\n"
                "\n"
                "/docs/ @carol\n",
                encoding="utf-8",
            )
            entries = load_stakeholders(path)
            self.assertEqual(len(entries), 2)
            self.assertEqual(entries[0]["pattern"], "/src/")
            self.assertEqual(entries[0]["owners"], ["alice", "bob"])
            self.assertEqual(entries[1]["pattern"], "/docs/")
            self.assertEqual(entries[1]["owners"], ["carol"])

    def test_returns_empty_for_missing_file(self) -> None:
        entries = load_stakeholders(Path("/nonexistent/STAKEHOLDERS"))
        self.assertEqual(entries, [])

    def test_skips_lines_without_owners(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "STAKEHOLDERS"
            path.write_text("/src/\n/docs/ @alice\n", encoding="utf-8")
            entries = load_stakeholders(path)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["pattern"], "/docs/")


class FormatStakeholdersForPromptTest(unittest.TestCase):
    def test_formats_entries(self) -> None:
        entries = [
            {"pattern": "/src/", "owners": ["alice", "bob"]},
            {"pattern": "/docs/", "owners": ["carol"]},
        ]
        result = format_stakeholders_for_prompt(entries)
        self.assertIn("/src/", result)
        self.assertIn("@alice", result)
        self.assertIn("@bob", result)
        self.assertIn("@carol", result)

    def test_returns_fallback_for_empty(self) -> None:
        result = format_stakeholders_for_prompt([])
        self.assertEqual(result, "No stakeholders configured.")


class DedupeStringsTest(unittest.TestCase):
    def test_preserves_order_while_deduplicating(self) -> None:
        self.assertEqual(dedupe_strings(["triaged", "bug", "triaged", "bug", "area:workflow"]), ["triaged", "bug", "area:workflow"])


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

    def test_skips_managed_oz_comments(self) -> None:
        rendered = format_issue_comments(
            [
                {
                    "id": 1,
                    "author_association": "NONE",
                    "created_at": "2026-03-24T00:00:00Z",
                    "body": "Visible reporter comment",
                    "user": {"login": "alice"},
                },
                {
                    "id": 2,
                    "author_association": "NONE",
                    "created_at": "2026-03-24T01:00:00Z",
                    "body": "Managed status\n\n<!-- oz-agent-metadata: {\"type\":\"issue-status\"} -->",
                    "user": {"login": "oz-agent"},
                },
            ]
        )
        self.assertEqual(rendered, "- @alice [NONE] (2026-03-24T00:00:00Z): Visible reporter comment")


class ExtractFollowUpQuestionsTest(unittest.TestCase):
    def test_normalizes_strings_and_objects(self) -> None:
        questions = extract_follow_up_questions(
            {
                "follow_up_questions": [
                    "What Warp version is affected?",
                    {"question": "What Warp version is affected?"},
                    {"question": "Does this reproduce in another shell?"},
                    "",
                ]
            }
        )
        self.assertEqual(
            questions,
            [
                "What Warp version is affected?",
                "Does this reproduce in another shell?",
            ],
        )


class ApplyTriageResultTest(unittest.TestCase):
    def test_replaces_primary_and_repro_labels(self) -> None:
        github = FakeTriageGitHubClient()
        issue = {
            "number": 42,
            "labels": [
                {"name": "bug"},
                {"name": "repro:unknown"},
                {"name": "triaged"},
                {"name": "area:workflow"},
            ],
            "body": "Original body",
        }
        apply_triage_result(
            github,
            "acme",
            "widgets",
            issue,
            result={
                "labels": ["enhancement", "repro:high", "area:workflow"],
                "issue_body": "## Updated",
            },
            configured_labels={
                "triaged": {"color": "0E8A16", "description": "done"},
                "enhancement": {"color": "A2EEEF", "description": "enh"},
                "repro:high": {"color": "B60205", "description": "repro"},
                "area:workflow": {"color": "7057FF", "description": "area"},
            },
            repo_labels={
                "triaged": {"name": "triaged"},
                "bug": {"name": "bug"},
                "enhancement": {"name": "enhancement"},
                "repro:unknown": {"name": "repro:unknown"},
                "repro:high": {"name": "repro:high"},
                "area:workflow": {"name": "area:workflow"},
            },
        )
        self.assertEqual(github.removed_labels, ["bug", "repro:unknown"])
        self.assertEqual(github.added_labels, ["enhancement", "repro:high", "area:workflow", "triaged"])
        self.assertEqual(github.updated_issue_body, compose_triaged_issue_body("## Updated", "Original body"))


    def test_skips_triaged_label_when_needs_info_present(self) -> None:
        github = FakeTriageGitHubClient()
        issue = {
            "number": 55,
            "labels": [],
            "body": "Original body",
        }
        apply_triage_result(
            github,
            "acme",
            "widgets",
            issue,
            result={
                "labels": ["needs-info", "repro:unknown"],
                "issue_body": "## Needs more info",
            },
            configured_labels={
                "triaged": {"color": "0E8A16", "description": "done"},
                "needs-info": {"color": "D876E3", "description": "info"},
                "repro:unknown": {"color": "CCCCCC", "description": "repro"},
            },
            repo_labels={
                "triaged": {"name": "triaged"},
                "needs-info": {"name": "needs-info"},
                "repro:unknown": {"name": "repro:unknown"},
            },
        )
        self.assertNotIn("triaged", github.added_labels)
        self.assertIn("needs-info", github.added_labels)

    def test_adds_needs_info_when_follow_up_questions_present(self) -> None:
        github = FakeTriageGitHubClient()
        issue = {
            "number": 57,
            "labels": [],
            "body": "Original body",
        }
        apply_triage_result(
            github,
            "acme",
            "widgets",
            issue,
            result={
                "labels": ["bug", "repro:low"],
                "issue_body": "## Bug with questions",
                "follow_up_questions": ["What OS are you on?"],
            },
            configured_labels={
                "triaged": {"color": "0E8A16", "description": "done"},
                "bug": {"color": "D73A4A", "description": "bug"},
                "needs-info": {"color": "D876E3", "description": "info"},
                "repro:low": {"color": "CCCCCC", "description": "repro"},
            },
            repo_labels={
                "triaged": {"name": "triaged"},
                "bug": {"name": "bug"},
                "needs-info": {"name": "needs-info"},
                "repro:low": {"name": "repro:low"},
            },
        )
        self.assertIn("needs-info", github.added_labels)
        self.assertNotIn("triaged", github.added_labels)

    def test_removes_triaged_on_retriage_with_needs_info(self) -> None:
        github = FakeTriageGitHubClient()
        issue = {
            "number": 56,
            "labels": [{"name": "triaged"}, {"name": "bug"}],
            "body": "Original body",
        }
        apply_triage_result(
            github,
            "acme",
            "widgets",
            issue,
            result={
                "labels": ["needs-info", "repro:unknown"],
                "issue_body": "## Needs more info",
            },
            configured_labels={
                "triaged": {"color": "0E8A16", "description": "done"},
                "needs-info": {"color": "D876E3", "description": "info"},
                "bug": {"color": "D73A4A", "description": "bug"},
                "repro:unknown": {"color": "CCCCCC", "description": "repro"},
            },
            repo_labels={
                "triaged": {"name": "triaged"},
                "needs-info": {"name": "needs-info"},
                "bug": {"name": "bug"},
                "repro:unknown": {"name": "repro:unknown"},
            },
        )
        self.assertIn("triaged", github.removed_labels)
        self.assertIn("bug", github.removed_labels)
        self.assertNotIn("triaged", github.added_labels)


class SyncFollowUpCommentTest(unittest.TestCase):
    def test_creates_managed_follow_up_comment(self) -> None:
        github = FakeTriageGitHubClient()
        issue = {"number": 42, "user": {"login": "alice"}}
        sync_follow_up_comment(
            github,
            "acme",
            "widgets",
            issue,
            questions=["What Warp version is affected?"],
        )
        self.assertEqual(len(github.comments), 1)
        self.assertEqual(
            github.comments[0]["body"],
            build_follow_up_comment(issue, ["What Warp version is affected?"]),
        )

    def test_preserves_existing_comment_when_questions_empty(self) -> None:
        github = FakeTriageGitHubClient()
        issue = {"number": 42, "user": {"login": "alice"}}
        sync_follow_up_comment(
            github,
            "acme",
            "widgets",
            issue,
            questions=["What Warp version is affected?"],
        )
        self.assertEqual(len(github.comments), 1)
        sync_follow_up_comment(github, "acme", "widgets", issue, questions=[])
        self.assertEqual(github.deleted_comment_ids, [])
        self.assertEqual(len(github.comments), 1)


class ExtractDuplicateOfTest(unittest.TestCase):
    def test_extracts_valid_duplicate_entries(self) -> None:
        result = {
            "duplicate_of": [
                {"issue_number": 10, "title": "Same bug", "similarity_reason": "Same error"},
                {"issue_number": 20, "title": "Related", "similarity_reason": "Same feature"},
            ]
        }
        duplicates = extract_duplicate_of(result)
        self.assertEqual(len(duplicates), 2)
        self.assertEqual(duplicates[0]["issue_number"], 10)
        self.assertEqual(duplicates[1]["issue_number"], 20)

    def test_returns_empty_for_missing_field(self) -> None:
        self.assertEqual(extract_duplicate_of({"labels": ["bug"]}), [])

    def test_returns_empty_for_non_list(self) -> None:
        self.assertEqual(extract_duplicate_of({"duplicate_of": "not a list"}), [])

    def test_skips_entries_without_issue_number(self) -> None:
        result = {
            "duplicate_of": [
                {"title": "No number"},
                {"issue_number": 5, "title": "Has number"},
            ]
        }
        duplicates = extract_duplicate_of(result)
        self.assertEqual(len(duplicates), 1)
        self.assertEqual(duplicates[0]["issue_number"], 5)


class BuildDuplicateCommentTest(unittest.TestCase):
    def test_builds_comment_with_duplicate_links(self) -> None:
        issue = {"number": 42, "user": {"login": "alice"}}
        duplicates = [
            {"issue_number": 10, "title": "Original bug", "similarity_reason": "Same error message"},
            {"issue_number": 20, "title": "Another report", "similarity_reason": "Same symptoms"},
        ]
        body = build_duplicate_comment(issue, duplicates)
        self.assertIn("@alice", body)
        self.assertIn("#10", body)
        self.assertIn("#20", body)
        self.assertIn("Original bug", body)
        self.assertIn("closed in 2 business days", body)
        self.assertIn("oz-agent-metadata", body)


class SyncDuplicateCommentTest(unittest.TestCase):
    def test_creates_managed_duplicate_comment(self) -> None:
        github = FakeTriageGitHubClient()
        issue = {"number": 42, "user": {"login": "alice"}}
        sync_duplicate_comment(
            github,
            "acme",
            "widgets",
            issue,
            duplicates=[
                {"issue_number": 10, "title": "Original", "similarity_reason": "Same"},
                {"issue_number": 20, "title": "Another", "similarity_reason": "Same"},
            ],
        )
        self.assertEqual(len(github.comments), 1)
        self.assertIn("#10", str(github.comments[0]["body"]))
        self.assertIn("#20", str(github.comments[0]["body"]))

    def test_preserves_existing_comment_when_duplicates_empty(self) -> None:
        github = FakeTriageGitHubClient()
        issue = {"number": 42, "user": {"login": "alice"}}
        sync_duplicate_comment(
            github,
            "acme",
            "widgets",
            issue,
            duplicates=[
                {"issue_number": 10, "title": "Original", "similarity_reason": "Same"},
            ],
        )
        self.assertEqual(len(github.comments), 1)
        sync_duplicate_comment(github, "acme", "widgets", issue, duplicates=[])
        self.assertEqual(github.deleted_comment_ids, [])
        self.assertEqual(len(github.comments), 1)


class FakeTriageGitHubClient:
    def __init__(self) -> None:
        self.comments: list[dict[str, object]] = []
        self.added_labels: list[str] = []
        self.removed_labels: list[str] = []
        self.updated_issue_body = ""
        self.deleted_comment_ids: list[int] = []

    def add_labels(self, owner: str, repo: str, issue_number: int, labels: list[str]) -> list[dict[str, object]]:
        self.added_labels = list(labels)
        return [{"name": label} for label in labels]

    def remove_label(self, owner: str, repo: str, issue_number: int, label_name: str) -> None:
        self.removed_labels.append(label_name)

    def update_issue(self, owner: str, repo: str, issue_number: int, **fields: object) -> dict[str, object]:
        self.updated_issue_body = str(fields.get("body") or "")
        return {"number": issue_number, "body": self.updated_issue_body}

    def list_issue_comments(self, owner: str, repo: str, issue_number: int) -> list[dict[str, object]]:
        return [dict(comment) for comment in self.comments]

    def create_comment(self, owner: str, repo: str, issue_number: int, body: str) -> dict[str, object]:
        comment = {"id": len(self.comments) + 1, "body": body}
        self.comments.append(comment)
        return dict(comment)

    def update_comment(self, owner: str, repo: str, comment_id: int, body: str) -> dict[str, object]:
        for comment in self.comments:
            if int(comment["id"]) == comment_id:
                comment["body"] = body
                return dict(comment)
        raise AssertionError(f"Missing comment {comment_id}")

    def delete_comment(self, owner: str, repo: str, comment_id: int) -> None:
        self.deleted_comment_ids.append(comment_id)
        self.comments = [comment for comment in self.comments if int(comment["id"]) != comment_id]


if __name__ == "__main__":
    unittest.main()
