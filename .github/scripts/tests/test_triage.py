from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from triage_new_issues import (
    TRIAGE_DISCLAIMER,
    _lowercase_first,
    apply_triage_result,
    build_duplicate_comment,
    build_duplicate_section,
    build_follow_up_comment,
    build_follow_up_section,
    extract_duplicate_of,
    extract_follow_up_questions,
    follow_up_comment_metadata,
    duplicate_comment_metadata,
    format_recent_issues_for_dedupe,
    format_issue_comments,
    load_recent_issues_for_dedupe,
    resolve_issue_number_override,
    sync_duplicate_comment,
    sync_follow_up_comment,
    _cleanup_legacy_triage_comments,
)

from oz_workflows.helpers import (
    WorkflowProgressComment,
    _format_triage_session_link,
    build_comment_body,
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

class TriageWorkflowGuardsTest(unittest.TestCase):
    def _normalized_workflow_text(self, filename: str) -> str:
        workflow_path = Path(__file__).resolve().parents[2] / "workflows" / filename
        return " ".join(workflow_path.read_text(encoding="utf-8").split())

    def test_reusable_workflow_ignores_bot_issue_comment_events(self) -> None:
        self.assertIn(
            "if: >- github.event_name != 'issue_comment' || github.event.comment.user.type != 'Bot'",
            self._normalized_workflow_text("triage-new-issues.yml"),
        )

    def test_local_workflow_ignores_bot_issue_comment_events(self) -> None:
        self.assertIn(
            "github.event_name == 'issue_comment' && !github.event.issue.pull_request && github.event.comment.user.type != 'Bot' && (",
            self._normalized_workflow_text("triage-new-issues-local.yml"),
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


class LoadRecentIssuesForDedupeTest(unittest.TestCase):
    def test_returns_prefetched_issue_batch(self) -> None:
        github = FakeRecentIssuesGitHubClient(
            [
                {"number": 1, "title": "One"},
                {"number": 2, "title": "Two"},
            ]
        )
        issues = load_recent_issues_for_dedupe(github)
        self.assertEqual([issue["number"] for issue in issues or []], [1, 2])
        self.assertEqual(github.calls, 1)

    def test_returns_none_when_fetch_fails(self) -> None:
        github = FakeRecentIssuesGitHubClient([], should_fail=True)
        self.assertIsNone(load_recent_issues_for_dedupe(github))


class FormatRecentIssuesForDedupeTest(unittest.TestCase):
    def test_formats_prefetched_issues_and_excludes_current_issue(self) -> None:
        rendered = format_recent_issues_for_dedupe(
            [
                {"number": 10, "title": "Current", "body": "skip me"},
                {"number": 11, "title": "Neighbor", "body": "has details"},
                {"number": 12, "title": "Pull request", "body": "skip", "pull_request": {"url": "https://example.test/pr/12"}},
            ],
            current_issue_number=10,
        )
        self.assertIn("#11: Neighbor", rendered)
        self.assertNotIn("#10: Current", rendered)
        self.assertNotIn("#12: Pull request", rendered)

    def test_reports_fetch_failure(self) -> None:
        self.assertEqual(
            format_recent_issues_for_dedupe(None, current_issue_number=10),
            "Unable to fetch recent issues for duplicate detection.",
        )


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

    def test_deletes_existing_comment_when_questions_empty(self) -> None:
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
        comment_id = int(github.comments[0]["id"])
        sync_follow_up_comment(github, "acme", "widgets", issue, questions=[])
        self.assertIn(comment_id, github.deleted_comment_ids)
        self.assertEqual(len(github.comments), 0)

    def test_noop_when_no_existing_comment_and_questions_empty(self) -> None:
        github = FakeTriageGitHubClient()
        issue = {"number": 42, "user": {"login": "alice"}}
        sync_follow_up_comment(github, "acme", "widgets", issue, questions=[])
        self.assertEqual(len(github.comments), 0)
        self.assertEqual(github.deleted_comment_ids, [])


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

    def test_skips_invalid_duplicate_issue_numbers(self) -> None:
        result = {
            "duplicate_of": [
                {"issue_number": "abc", "title": "Bad"},
                {"issue_number": 0, "title": "Also bad"},
                {"issue_number": 7, "title": "Valid"},
            ]
        }
        self.assertEqual(
            extract_duplicate_of(result),
            [{"issue_number": 7, "title": "Valid", "similarity_reason": ""}],
        )

    def test_skips_self_references_and_duplicate_entries(self) -> None:
        result = {
            "duplicate_of": [
                {"issue_number": 42, "title": "Self"},
                {"issue_number": 10, "title": "First"},
                {"issue_number": "10", "title": "Duplicate"},
            ]
        }
        self.assertEqual(
            extract_duplicate_of(result, current_issue_number=42),
            [{"issue_number": 10, "title": "First", "similarity_reason": ""}],
        )


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
        self.assertIn("Why it looks similar: Same error message", body)
        self.assertIn("close it as a duplicate after review", body)
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


class FormatTriageSessionLinkTest(unittest.TestCase):
    def test_formats_conversation_link_as_markdown(self) -> None:
        result = _format_triage_session_link("https://app.warp.dev/conversation/abc")
        self.assertEqual(result, "[the triage session on Warp](https://app.warp.dev/conversation/abc)")

    def test_formats_sharing_link_as_markdown(self) -> None:
        result = _format_triage_session_link("https://app.warp.dev/session/xyz")
        self.assertEqual(result, "[the triage session on Warp](https://app.warp.dev/session/xyz)")

    def test_strips_whitespace(self) -> None:
        result = _format_triage_session_link("  https://example.test/session  ")
        self.assertEqual(result, "[the triage session on Warp](https://example.test/session)")


class BuildFollowUpSectionTest(unittest.TestCase):
    def test_includes_reporter_mention_and_questions(self) -> None:
        issue = {"number": 42, "user": {"login": "alice"}}
        section = build_follow_up_section(issue, ["What OS?", "What version?"])
        self.assertIn("### Follow-up questions", section)
        self.assertIn("@alice", section)
        self.assertIn("1. What OS?", section)
        self.assertIn("2. What version?", section)
        self.assertIn("Thanks for the report", section)
        self.assertIn("Reply in-thread", section)

    def test_omits_reporter_when_missing(self) -> None:
        issue = {"number": 42, "user": {"login": ""}}
        section = build_follow_up_section(issue, ["What OS?"])
        self.assertIn("### Follow-up questions", section)
        self.assertNotIn("@", section)
        self.assertIn("1. What OS?", section)


class BuildDuplicateSectionTest(unittest.TestCase):
    def test_includes_issue_links_and_reasons(self) -> None:
        issue = {"number": 42, "user": {"login": "alice"}}
        duplicates = [
            {"issue_number": 10, "title": "Original bug", "similarity_reason": "Same error"},
            {"issue_number": 20, "title": "Another", "similarity_reason": ""},
        ]
        section = build_duplicate_section(issue, duplicates)
        self.assertIn("### Potential duplicates", section)
        self.assertIn("#10", section)
        self.assertIn("Original bug", section)
        self.assertIn("Why it looks similar: Same error", section)
        self.assertIn("#20", section)
        self.assertIn("Another", section)
        self.assertNotIn("Why it looks similar: \n", section)
        self.assertIn("close it as a duplicate after review", section)

    def test_omits_reason_when_empty(self) -> None:
        issue = {"number": 42, "user": {"login": "alice"}}
        duplicates = [
            {"issue_number": 5, "title": "Dupe", "similarity_reason": ""},
        ]
        section = build_duplicate_section(issue, duplicates)
        self.assertNotIn("Why it looks similar", section)


class CleanupLegacyTriageCommentsTest(unittest.TestCase):
    def test_deletes_follow_up_and_duplicate_comments(self) -> None:
        github = FakeTriageGitHubClient()
        issue_number = 42
        follow_up_body = build_comment_body(
            "follow-up content",
            follow_up_comment_metadata(issue_number),
        )
        dup_body = build_comment_body(
            "duplicate content",
            duplicate_comment_metadata(issue_number),
        )
        github.create_comment("acme", "widgets", issue_number, follow_up_body)
        github.create_comment("acme", "widgets", issue_number, dup_body)
        github.create_comment("acme", "widgets", issue_number, "unrelated comment")
        self.assertEqual(len(github.comments), 3)
        issue = {"number": issue_number}
        _cleanup_legacy_triage_comments(github, "acme", "widgets", issue)
        self.assertEqual(len(github.comments), 1)
        self.assertIn("unrelated", str(github.comments[0]["body"]))

    def test_noop_when_no_legacy_comments(self) -> None:
        github = FakeTriageGitHubClient()
        github.create_comment("acme", "widgets", 42, "normal comment")
        issue = {"number": 42}
        _cleanup_legacy_triage_comments(github, "acme", "widgets", issue)
        self.assertEqual(len(github.comments), 1)


class ReplaceBodyTest(unittest.TestCase):
    def test_replaces_comment_content_preserving_metadata(self) -> None:
        github = FakeTriageGitHubClient()
        progress = WorkflowProgressComment(
            github, "acme", "widgets", 42,
            workflow="triage-new-issues",
            event_payload={"sender": {"login": "alice"}},
        )
        progress.start("Stage 1 message")
        self.assertEqual(len(github.comments), 1)
        body_before = str(github.comments[0]["body"])
        self.assertIn("Stage 1 message", body_before)
        self.assertIn(progress.metadata, body_before)

        progress.replace_body("Stage 2 message")
        body_after = str(github.comments[0]["body"])
        self.assertNotIn("Stage 1 message", body_after)
        self.assertIn("Stage 2 message", body_after)
        self.assertIn(progress.metadata, body_after)
        self.assertIn("@alice", body_after)

    def test_creates_comment_when_none_exists(self) -> None:
        github = FakeTriageGitHubClient()
        progress = WorkflowProgressComment(
            github, "acme", "widgets", 42,
            workflow="triage-new-issues",
            event_payload={"sender": {"login": "bob"}},
        )
        progress.replace_body("Direct replace")
        self.assertEqual(len(github.comments), 1)
        self.assertIn("Direct replace", str(github.comments[0]["body"]))
        self.assertIn(progress.metadata, str(github.comments[0]["body"]))


class MutualExclusivityTest(unittest.TestCase):
    """Verify that when both follow-up questions and duplicates are present,
    only the duplicate section appears."""

    def test_duplicates_suppress_follow_up_questions(self) -> None:
        issue = {"number": 42, "user": {"login": "alice"}}
        result = {
            "summary": "looks like a dupe",
            "follow_up_questions": ["What OS?"],
            "duplicate_of": [
                {"issue_number": 10, "title": "Original", "similarity_reason": "Same"},
            ],
        }
        follow_up_questions = extract_follow_up_questions(result)
        duplicates = extract_duplicate_of(result, current_issue_number=42)

        # Simulate the logic from process_issue
        parts: list[str] = ["Oz has completed the triage of this issue. The triage concluded that looks like a dupe."]
        if duplicates:
            parts.append(build_duplicate_section(issue, duplicates))
        elif follow_up_questions:
            parts.append(build_follow_up_section(issue, follow_up_questions))
        parts.append(TRIAGE_DISCLAIMER)
        body = "\n\n".join(parts)

        self.assertIn("### Potential duplicates", body)
        self.assertNotIn("### Follow-up questions", body)
        self.assertIn(TRIAGE_DISCLAIMER, body)

    def test_follow_up_when_no_duplicates(self) -> None:
        issue = {"number": 42, "user": {"login": "alice"}}
        result = {
            "summary": "needs more info",
            "follow_up_questions": ["What version?"],
            "duplicate_of": [],
        }
        follow_up_questions = extract_follow_up_questions(result)
        duplicates = extract_duplicate_of(result, current_issue_number=42)

        parts: list[str] = ["Oz has completed the triage of this issue. The triage concluded that needs more info."]
        if duplicates:
            parts.append(build_duplicate_section(issue, duplicates))
        elif follow_up_questions:
            parts.append(build_follow_up_section(issue, follow_up_questions))
        parts.append(TRIAGE_DISCLAIMER)
        body = "\n\n".join(parts)

        self.assertIn("### Follow-up questions", body)
        self.assertNotIn("### Potential duplicates", body)
        self.assertIn(TRIAGE_DISCLAIMER, body)

    def test_neither_section_when_both_empty(self) -> None:
        issue = {"number": 42, "user": {"login": "alice"}}
        result = {
            "summary": "all good",
            "follow_up_questions": [],
            "duplicate_of": [],
        }
        follow_up_questions = extract_follow_up_questions(result)
        duplicates = extract_duplicate_of(result, current_issue_number=42)

        parts: list[str] = ["Oz has completed the triage of this issue. The triage concluded that all good."]
        if duplicates:
            parts.append(build_duplicate_section(issue, duplicates))
        elif follow_up_questions:
            parts.append(build_follow_up_section(issue, follow_up_questions))
        parts.append(TRIAGE_DISCLAIMER)
        body = "\n\n".join(parts)

        self.assertNotIn("### Follow-up questions", body)
        self.assertNotIn("### Potential duplicates", body)
        self.assertIn(TRIAGE_DISCLAIMER, body)


class LowercaseFirstTest(unittest.TestCase):
    def test_lowercases_initial_uppercase(self) -> None:
        self.assertEqual(_lowercase_first("This is a bug"), "this is a bug")

    def test_preserves_already_lowercase(self) -> None:
        self.assertEqual(_lowercase_first("already lowercase"), "already lowercase")

    def test_handles_empty_string(self) -> None:
        self.assertEqual(_lowercase_first(""), "")

    def test_handles_single_character(self) -> None:
        self.assertEqual(_lowercase_first("A"), "a")

    def test_preserves_rest_of_string(self) -> None:
        self.assertEqual(_lowercase_first("The GPU driver is outdated"), "the GPU driver is outdated")


class SummaryCasingInStage3Test(unittest.TestCase):
    """Verify that the summary is lowercased when embedded mid-sentence."""

    def test_uppercase_summary_reads_naturally(self) -> None:
        summary = _lowercase_first(str("This is a new summary").strip())
        sentence = f"The triage concluded that {summary}."
        self.assertEqual(sentence, "The triage concluded that this is a new summary.")

    def test_fallback_summary_stays_lowercase(self) -> None:
        summary = _lowercase_first(str("triage completed").strip())
        sentence = f"The triage concluded that {summary}."
        self.assertEqual(sentence, "The triage concluded that triage completed.")


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

    def get_comment(self, owner: str, repo: str, comment_id: int) -> dict[str, object]:
        for comment in self.comments:
            if int(comment["id"]) == comment_id:
                return dict(comment)
        raise AssertionError(f"Missing comment {comment_id}")

    def update_comment(self, owner: str, repo: str, comment_id: int, body: str) -> dict[str, object]:
        for comment in self.comments:
            if int(comment["id"]) == comment_id:
                comment["body"] = body
                return dict(comment)
        raise AssertionError(f"Missing comment {comment_id}")

    def delete_comment(self, owner: str, repo: str, comment_id: int) -> None:
        self.deleted_comment_ids.append(comment_id)
        self.comments = [comment for comment in self.comments if int(comment["id"]) != comment_id]


class FakeRecentIssuesGitHubClient:
    def __init__(self, issues: list[dict[str, object]], *, should_fail: bool = False) -> None:
        self.issues = issues
        self.should_fail = should_fail
        self.calls = 0

    def get_issues(self, **_: object) -> list[dict[str, object]]:
        self.calls += 1
        if self.should_fail:
            raise RuntimeError("boom")
        return list(self.issues)


if __name__ == "__main__":
    unittest.main()
