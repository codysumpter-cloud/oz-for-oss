from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from triage_new_issues import (
    TRIAGE_DISCLAIMER,
    _lowercase_first,
    _record_triage_session_link,
    apply_triage_result,
    build_duplicate_section,
    build_follow_up_section,
    build_question_reasoning_section,
    extract_duplicate_of,
    extract_follow_up_questions,
    fetch_command_signatures_context,
    _follow_up_comment_metadata,
    _duplicate_comment_metadata,
    extract_requested_labels,
    format_recent_issues_for_dedupe,
    format_issue_comments,
    load_recent_issues_for_dedupe,
    resolve_issue_number_override,
    triage_heuristics_prompt,
    _triage_summary_comment_metadata,
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
    fetch_command_signatures_listing,
    format_command_signatures_for_prompt,
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

    def test_comment_workflows_ignore_automation_commenters(self) -> None:
        automation_guard = (
            "github.event.comment.user.type != 'Bot' && "
            "!endsWith(github.event.comment.user.login, '[bot]')"
        )
        for filename in (
            "triage-new-issues.yml",
            "triage-new-issues-local.yml",
            "respond-to-triaged-issue-comment.yml",
            "respond-to-triaged-issue-comment-local.yml",
            "respond-to-pr-comment.yml",
            "create-spec-from-issue-local.yml",
            "create-implementation-from-issue-local.yml",
            "pr-hooks.yml",
        ):
            with self.subTest(filename=filename):
                self.assertIn(
                    automation_guard,
                    self._normalized_workflow_text(filename),
                )

    def test_reusable_workflow_ignores_bot_issue_comment_events(self) -> None:
        self.assertIn(
            "if: >- github.event_name != 'issue_comment' || ( github.event.comment.user.type != 'Bot' && !endsWith(github.event.comment.user.login, '[bot]') )",
            self._normalized_workflow_text("triage-new-issues.yml"),
        )

    def test_local_workflow_ignores_bot_issue_comment_events(self) -> None:
        self.assertIn(
            "github.event_name == 'issue_comment' && !github.event.issue.pull_request && github.event.comment.user.type != 'Bot' && !endsWith(github.event.comment.user.login, '[bot]') && (",
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


class ExtractRequestedLabelsTest(unittest.TestCase):
    def test_strips_prohibited_labels(self) -> None:
        result = {"labels": ["bug", "ready-to-implement", "triaged", "ready-to-spec"]}
        self.assertEqual(
            extract_requested_labels(result),
            ["bug", "triaged"],
        )

    def test_returns_normal_labels_unchanged(self) -> None:
        result = {"labels": ["bug", "repro:high", "area:workflow"]}
        self.assertEqual(
            extract_requested_labels(result),
            ["bug", "repro:high", "area:workflow"],
        )

    def test_returns_empty_when_only_prohibited_labels(self) -> None:
        result = {"labels": ["ready-to-implement", "ready-to-spec"]}
        self.assertEqual(extract_requested_labels(result), [])

    def test_returns_empty_for_non_list(self) -> None:
        self.assertEqual(extract_requested_labels({"labels": "bug"}), [])

    def test_returns_empty_for_missing_labels_key(self) -> None:
        self.assertEqual(extract_requested_labels({}), [])


class ExtractFollowUpQuestionsTest(unittest.TestCase):
    def test_normalizes_strings_and_objects(self) -> None:
        questions = extract_follow_up_questions(
            {
                "follow_up_questions": [
                    "What Warp version is affected?",
                    {"question": "What Warp version is affected?", "reasoning": "dup"},
                    {"question": "Does this reproduce in another shell?", "reasoning": "env check"},
                    "",
                ]
            }
        )
        self.assertEqual(
            questions,
            [
                {"question": "What Warp version is affected?", "reasoning": ""},
                {"question": "Does this reproduce in another shell?", "reasoning": "env check"},
            ],
        )

    def test_returns_empty_for_non_list(self) -> None:
        self.assertEqual(extract_follow_up_questions({"follow_up_questions": "not a list"}), [])

    def test_returns_empty_for_missing_key(self) -> None:
        self.assertEqual(extract_follow_up_questions({}), [])

    def test_preserves_reasoning_from_object_entries(self) -> None:
        questions = extract_follow_up_questions(
            {
                "follow_up_questions": [
                    {"question": "What OS?", "reasoning": "Platform-sensitive issue"},
                ]
            }
        )
        self.assertEqual(
            questions,
            [{"question": "What OS?", "reasoning": "Platform-sensitive issue"}],
        )


class ApplyTriageResultTest(unittest.TestCase):
    def test_replaces_primary_and_repro_labels(self) -> None:
        github = FakeTriageGitHubClient()
        issue = github.issue({
            "number": 42,
            "labels": [
                {"name": "bug"},
                {"name": "repro:unknown"},
                {"name": "triaged"},
                {"name": "area:workflow"},
            ],
            "body": "Original body",
        })
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
        self.assertEqual(github.updated_issue_body, "")
        # Triage summary is no longer posted as a separate comment;
        # it is embedded in the progress comment by process_issue.
        self.assertEqual(len(github.comments), 0)


    def test_skips_triaged_label_when_needs_info_present(self) -> None:
        github = FakeTriageGitHubClient()
        issue = github.issue({
            "number": 55,
            "labels": [],
            "body": "Original body",
        })
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
        issue = github.issue({
            "number": 57,
            "labels": [],
            "body": "Original body",
        })
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

    def test_does_not_post_separate_summary_comment(self) -> None:
        github = FakeTriageGitHubClient()
        issue = github.issue({
            "number": 58,
            "labels": [],
            "body": "Original body",
        })
        apply_triage_result(
            github,
            "acme",
            "widgets",
            issue,
            result={
                "labels": ["bug", "repro:low"],
                "issue_body": "## Triage summary content",
            },
            configured_labels={
                "triaged": {"color": "0E8A16", "description": "done"},
                "bug": {"color": "D73A4A", "description": "bug"},
                "repro:low": {"color": "CCCCCC", "description": "repro"},
            },
            repo_labels={
                "triaged": {"name": "triaged"},
                "bug": {"name": "bug"},
                "repro:low": {"name": "repro:low"},
            },
        )
        self.assertEqual(github.updated_issue_body, "")
        # Triage summary is no longer posted as a separate comment;
        # it is embedded in the progress comment by process_issue.
        self.assertEqual(len(github.comments), 0)

    def test_removes_triaged_on_retriage_with_needs_info(self) -> None:
        github = FakeTriageGitHubClient()
        issue = github.issue({
            "number": 56,
            "labels": [{"name": "triaged"}, {"name": "bug"}],
            "body": "Original body",
        })
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
        questions = [
            {"question": "What OS?", "reasoning": "Platform-sensitive"},
            {"question": "What version?", "reasoning": ""},
        ]
        section = build_follow_up_section(issue, questions)
        self.assertIn("@alice", section)
        self.assertIn("1. What OS?", section)
        self.assertIn("2. What version?", section)
        self.assertIn("follow-up questions", section)
        self.assertIn("Reply in-thread", section)
        # Reasoning should NOT be in the above-the-fold section
        self.assertNotIn("Platform-sensitive", section)

    def test_omits_reporter_when_missing(self) -> None:
        issue = {"number": 42, "user": {"login": ""}}
        questions = [{"question": "What OS?", "reasoning": ""}]
        section = build_follow_up_section(issue, questions)
        self.assertNotIn("@", section)
        self.assertIn("1. What OS?", section)


class BuildDuplicateSectionTest(unittest.TestCase):
    def test_includes_issue_links(self) -> None:
        issue = {"number": 42, "user": {"login": "alice"}}
        duplicates = [
            {"issue_number": 10, "title": "Original bug", "similarity_reason": "Same error"},
            {"issue_number": 20, "title": "Another", "similarity_reason": ""},
        ]
        section = build_duplicate_section(issue, duplicates)
        self.assertIn("@alice", section)
        self.assertIn("#10", section)
        self.assertIn("Original bug", section)
        self.assertIn("#20", section)
        self.assertIn("Another", section)
        # Similarity reasons are now in the maintainer details, not above the fold
        self.assertNotIn("Why it looks similar", section)
        self.assertIn("close it as a duplicate after review", section)

    def test_omits_reporter_when_missing(self) -> None:
        issue = {"number": 42, "user": {"login": ""}}
        duplicates = [
            {"issue_number": 5, "title": "Dupe", "similarity_reason": ""},
        ]
        section = build_duplicate_section(issue, duplicates)
        self.assertNotIn("@", section)
        self.assertIn("#5", section)


class CleanupLegacyTriageCommentsTest(unittest.TestCase):
    def test_deletes_follow_up_duplicate_and_summary_comments(self) -> None:
        github = FakeTriageGitHubClient()
        issue_number = 42
        follow_up_body = build_comment_body(
            "follow-up content",
            _follow_up_comment_metadata(issue_number),
        )
        dup_body = build_comment_body(
            "duplicate content",
            _duplicate_comment_metadata(issue_number),
        )
        summary_body = build_comment_body(
            "## Triage summary",
            _triage_summary_comment_metadata(issue_number),
        )
        github._append_comment(follow_up_body)
        github._append_comment(dup_body)
        github._append_comment(summary_body)
        github._append_comment("unrelated comment")
        self.assertEqual(len(github.comments), 4)
        issue = github.issue({"number": issue_number})
        _cleanup_legacy_triage_comments(github, "acme", "widgets", issue)
        self.assertEqual(len(github.comments), 1)
        self.assertIn("unrelated", str(github.comments[0]["body"]))

    def test_noop_when_no_legacy_comments(self) -> None:
        github = FakeTriageGitHubClient()
        github._append_comment("normal comment")
        issue = github.issue({"number": 42})
        _cleanup_legacy_triage_comments(github, "acme", "widgets", issue)
        self.assertEqual(len(github.comments), 1)

    def test_uses_provided_comments_and_skips_fetch(self) -> None:
        # Simulate a GitHub client whose comments list would be out of sync
        # with what the caller already fetched. The function should prefer
        # the caller-provided list and not re-fetch via ``issue.get_comments()``.
        class IssueWithCountingComments(dict):
            def __init__(self, number: int) -> None:
                super().__init__(number=number)
                self.get_comments_calls = 0

            def get_comments(self) -> list[dict[str, object]]:
                self.get_comments_calls += 1
                return []

        issue_number = 42
        issue = IssueWithCountingComments(issue_number)
        github = FakeTriageGitHubClient()
        follow_up_body = build_comment_body(
            "follow-up content",
            _follow_up_comment_metadata(issue_number),
        )
        # Seed the fake client so deletion routes to it.
        github._append_comment(follow_up_body)
        pre_fetched = [FakeTriageComment(github, c) for c in github.comments]
        _cleanup_legacy_triage_comments(
            github, "acme", "widgets", issue, comments=pre_fetched
        )
        self.assertEqual(issue.get_comments_calls, 0)
        self.assertEqual(len(github.comments), 0)


class RecordTriageSessionLinkTest(unittest.TestCase):
    def test_first_pass_says_triaging(self) -> None:
        github = FakeTriageGitHubClient()
        progress = WorkflowProgressComment(
            github, "acme", "widgets", 42,
            workflow="triage-new-issues",
            event_payload={"sender": {"login": "alice"}},
        )
        progress.start("initial")
        _record_triage_session_link(
            progress,
            type("Run", (), {
                "run_id": "oz-run-1",
                "session_link": "https://app.warp.dev/session/abc",
            })(),
            is_retriage=False,
        )
        body = str(github.comments[0]["body"])
        self.assertIn("Oz is triaging this issue.", body)
        self.assertNotIn("re-triaging", body)

    def test_retriage_says_re_triaging(self) -> None:
        github = FakeTriageGitHubClient()
        progress = WorkflowProgressComment(
            github, "acme", "widgets", 42,
            workflow="triage-new-issues",
            event_payload={"sender": {"login": "alice"}},
        )
        progress.start("initial")
        _record_triage_session_link(
            progress,
            type("Run", (), {
                "run_id": "oz-run-2",
                "session_link": "https://app.warp.dev/session/abc",
            })(),
            is_retriage=True,
        )
        body = str(github.comments[0]["body"])
        self.assertIn("re-triaging", body)


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


class BuildQuestionReasoningSectionTest(unittest.TestCase):
    def test_includes_reasoning_for_questions_that_have_it(self) -> None:
        questions = [
            {"question": "What OS?", "reasoning": "Platform-sensitive"},
            {"question": "What version?", "reasoning": ""},
        ]
        section = build_question_reasoning_section(questions)
        self.assertIn("**Question reasoning**", section)
        self.assertIn("1. **What OS?**", section)
        self.assertIn("Platform-sensitive", section)
        # Question 2 has no reasoning, so it should not appear
        self.assertNotIn("What version?", section)

    def test_returns_empty_when_no_reasoning(self) -> None:
        questions = [
            {"question": "What OS?", "reasoning": ""},
        ]
        self.assertEqual(build_question_reasoning_section(questions), "")


class MutualExclusivityTest(unittest.TestCase):
    """Verify that when both follow-up questions and duplicates are present,
    only the duplicate section appears above the fold."""

    def _build_comment_parts(self, result: dict, issue: dict) -> str:
        """Simulate the comment assembly logic from process_issue."""
        from triage_new_issues import _lowercase_first
        summary = _lowercase_first(str(result.get("summary") or "triage completed").strip())
        issue_body = str(result.get("issue_body") or "").strip()
        follow_up_questions = extract_follow_up_questions(result)
        duplicates = extract_duplicate_of(result, current_issue_number=int(issue["number"]))

        parts: list[str] = []
        if not follow_up_questions and not duplicates:
            parts.append("Oz has completed the triage of this issue.")
        elif duplicates:
            parts.append(build_duplicate_section(issue, duplicates))
        elif follow_up_questions:
            parts.append(build_follow_up_section(issue, follow_up_questions))

        maintainer_parts: list[str] = [f"Oz concluded that {summary}."]
        if not duplicates and issue_body:
            maintainer_parts.append(issue_body)
        if duplicates:
            dup_reasoning_lines: list[str] = []
            for dup in duplicates:
                reason = dup.get("similarity_reason") or ""
                if reason:
                    dup_reasoning_lines.append(f"- #{dup['issue_number']}: {reason}")
            if dup_reasoning_lines:
                maintainer_parts.append(
                    "**Duplicate reasoning**\n" + "\n".join(dup_reasoning_lines)
                )
        if follow_up_questions:
            reasoning_section = build_question_reasoning_section(follow_up_questions)
            if reasoning_section:
                maintainer_parts.append(reasoning_section)
        details_body = "\n\n".join(maintainer_parts)
        parts.append(
            "<details>\n<summary>Maintainer details</summary>\n\n"
            f"{details_body}\n\n</details>"
        )
        parts.append(TRIAGE_DISCLAIMER)
        return "\n\n".join(parts)

    def test_duplicates_suppress_follow_up_questions(self) -> None:
        issue = {"number": 42, "user": {"login": "alice"}}
        result = {
            "summary": "looks like a dupe",
            "issue_body": "## Triage summary",
            "follow_up_questions": [{"question": "What OS?", "reasoning": ""}],
            "duplicate_of": [
                {"issue_number": 10, "title": "Original", "similarity_reason": "Same"},
            ],
        }
        body = self._build_comment_parts(result, issue)

        # Duplicate info is above the fold
        self.assertIn("overlap with existing issues", body)
        # Follow-up questions should not appear
        self.assertNotIn("follow-up questions", body)
        # issue_body suppressed for duplicates
        self.assertNotIn("## Triage summary", body)
        # Maintainer details are in the <details> section
        self.assertIn("<details>", body)
        self.assertIn(TRIAGE_DISCLAIMER, body)
        # Duplicate similarity reasoning appears in the maintainer section
        self.assertIn("**Duplicate reasoning**", body)
        self.assertIn("- #10: Same", body)
        # No fallback text when duplicates are present
        self.assertNotIn("Oz has completed the triage of this issue", body)
        self.assertNotIn("Oz has finished triaging this issue", body)

    def test_follow_up_when_no_duplicates(self) -> None:
        issue = {"number": 42, "user": {"login": "alice"}}
        result = {
            "summary": "needs more info",
            "issue_body": "## Triage summary",
            "follow_up_questions": [{"question": "What version?", "reasoning": ""}],
            "duplicate_of": [],
        }
        body = self._build_comment_parts(result, issue)

        self.assertIn("follow-up questions", body)
        self.assertNotIn("overlap with existing issues", body)
        # issue_body should be inside the details section
        self.assertIn("## Triage summary", body)
        self.assertIn("<details>", body)
        self.assertIn(TRIAGE_DISCLAIMER, body)
        # No fallback text when follow-up questions are present
        self.assertNotIn("Oz has completed the triage of this issue", body)
        self.assertNotIn("Oz has finished triaging this issue", body)

    def test_follow_up_reasoning_in_maintainer_section(self) -> None:
        issue = {"number": 42, "user": {"login": "alice"}}
        result = {
            "summary": "needs more info",
            "issue_body": "## Triage summary",
            "follow_up_questions": [
                {"question": "What OS?", "reasoning": "Platform-sensitive"},
                {"question": "What version?", "reasoning": ""},
            ],
            "duplicate_of": [],
        }
        body = self._build_comment_parts(result, issue)

        # Question reasoning appears inside the maintainer <details> section
        self.assertIn("**Question reasoning**", body)
        self.assertIn("**What OS?**", body)
        self.assertIn("Platform-sensitive", body)

    def test_neither_section_when_both_empty(self) -> None:
        issue = {"number": 42, "user": {"login": "alice"}}
        result = {
            "summary": "all good",
            "issue_body": "## Triage summary",
            "follow_up_questions": [],
            "duplicate_of": [],
        }
        body = self._build_comment_parts(result, issue)

        self.assertNotIn("follow-up questions", body)
        self.assertNotIn("overlap with existing issues", body)
        # issue_body should be in the maintainer details
        self.assertIn("## Triage summary", body)
        self.assertIn("<details>", body)
        self.assertIn(TRIAGE_DISCLAIMER, body)
        # Fallback text present when no user-facing content
        self.assertIn("Oz has completed the triage of this issue.", body)


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

    def test_preserves_leading_acronym(self) -> None:
        # "API ..." must not become "aPI ..." when embedded mid-sentence.
        self.assertEqual(
            _lowercase_first("API request validation fails on empty bodies"),
            "API request validation fails on empty bodies",
        )

    def test_preserves_two_letter_acronym(self) -> None:
        self.assertEqual(
            _lowercase_first("PR comments are duplicated"),
            "PR comments are duplicated",
        )

    def test_preserves_cli_acronym(self) -> None:
        self.assertEqual(
            _lowercase_first("CLI flag is ignored"),
            "CLI flag is ignored",
        )

    def test_lowercases_proper_noun_followed_by_lowercase(self) -> None:
        # Heuristic: second character is lowercase, so it's treated as a
        # regular word and the first character is lowercased.
        self.assertEqual(
            _lowercase_first("Python 3.11 compatibility"),
            "python 3.11 compatibility",
        )

    def test_single_uppercase_character_is_lowercased(self) -> None:
        self.assertEqual(_lowercase_first("A"), "a")


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


class TriageHeuristicsPromptTest(unittest.TestCase):
    def test_warp_heuristics_include_video_screenshot_guidance(self) -> None:
        heuristics = triage_heuristics_prompt("warpdotdev", "Warp")
        self.assertIn("video", heuristics)
        self.assertIn("screenshot", heuristics)

    def test_warp_heuristics_include_release_versioning_context(self) -> None:
        heuristics = triage_heuristics_prompt("warpdotdev", "Warp")
        self.assertIn("release branch", heuristics)
        self.assertIn("main/master", heuristics)

    def test_warp_heuristics_include_keyboard_layout_label(self) -> None:
        heuristics = triage_heuristics_prompt("warpdotdev", "Warp")
        self.assertIn("area:keyboard-layout", heuristics)

    def test_non_warp_heuristics_do_not_include_warp_specific_content(self) -> None:
        heuristics = triage_heuristics_prompt("acme", "widgets")
        self.assertNotIn("Warpify", heuristics)
        self.assertNotIn("area:keyboard-layout", heuristics)


class FetchCommandSignaturesContextTest(unittest.TestCase):
    def test_returns_not_applicable_for_non_warp_repos(self) -> None:
        result = fetch_command_signatures_context(None, "acme", "widgets")
        self.assertEqual(result, "Not applicable for this repository.")


class FormatCommandSignaturesForPromptTest(unittest.TestCase):
    def test_formats_command_names(self) -> None:
        result = format_command_signatures_for_prompt(["git", "curl", "docker"])
        self.assertIn("3 commands", result)
        self.assertIn("git", result)
        self.assertIn("curl", result)
        self.assertIn("docker", result)
        self.assertIn("command-signatures", result)

    def test_returns_fallback_for_empty(self) -> None:
        result = format_command_signatures_for_prompt([])
        self.assertEqual(result, "Unable to fetch command-signatures context.")


class FetchCommandSignaturesListingTest(unittest.TestCase):
    def test_returns_empty_list_on_error(self) -> None:
        result = fetch_command_signatures_listing(FakeFailingGitHubClient())
        self.assertEqual(result, [])

    def test_returns_sorted_directory_names(self) -> None:
        client = FakeCommandSignaturesGitHubClient([
            FakeContentFile("curl", "dir"),
            FakeContentFile("git", "dir"),
            FakeContentFile(".github", "dir"),
            FakeContentFile("README.md", "file"),
            FakeContentFile("apt", "dir"),
        ])
        result = fetch_command_signatures_listing(client)
        self.assertEqual(result, ["apt", "curl", "git"])


class FakeFailingGitHubClient:
    def get_repo(self, repo: str) -> None:
        raise RuntimeError("boom")


class FakeContentFile:
    def __init__(self, name: str, file_type: str) -> None:
        self.name = name
        self.type = file_type


class FakeCommandSignaturesRepo:
    def __init__(self, contents: list[FakeContentFile]) -> None:
        self.contents = contents

    def get_contents(self, path: str, ref: str = "") -> list[FakeContentFile]:
        return list(self.contents)


class FakeCommandSignaturesGitHubClient:
    def __init__(self, contents: list[FakeContentFile]) -> None:
        self.repo = FakeCommandSignaturesRepo(contents)

    def get_repo(self, repo: str) -> FakeCommandSignaturesRepo:
        return self.repo


class FakeTriageComment:
    """A minimal stand-in for ``github.IssueComment.IssueComment``."""

    def __init__(self, repo: "FakeTriageGitHubClient", data: dict[str, object]) -> None:
        self._repo = repo
        self._data = data

    @property
    def id(self) -> int:
        return int(self._data["id"])  # type: ignore[arg-type]

    @property
    def body(self) -> str:
        return str(self._data.get("body") or "")

    def edit(self, body: str) -> None:
        self._data["body"] = body

    def delete(self) -> None:
        self._repo.deleted_comment_ids.append(self.id)
        self._repo.comments = [
            c for c in self._repo.comments if int(c["id"]) != self.id  # type: ignore[arg-type]
        ]


class FakeTriageIssue:
    """A minimal stand-in for ``github.Issue.Issue``."""

    def __init__(self, repo: "FakeTriageGitHubClient", data: dict[str, object]) -> None:
        self._repo = repo
        self._data = data

    @property
    def number(self) -> int:
        return int(self._data.get("number") or 0)  # type: ignore[arg-type]

    @property
    def labels(self) -> list[object]:
        return list(self._data.get("labels") or [])  # type: ignore[arg-type]

    @property
    def body(self) -> str:
        return str(self._data.get("body") or "")

    @property
    def user(self) -> object:
        return self._data.get("user")

    @property
    def pull_request(self) -> object:
        return self._data.get("pull_request")

    @property
    def assignees(self) -> list[object]:
        return list(self._data.get("assignees") or [])  # type: ignore[arg-type]

    def add_to_labels(self, *label_names: str) -> None:
        self._repo.added_labels.extend(label_names)

    def remove_from_labels(self, label_name: str) -> None:
        self._repo.removed_labels.append(label_name)

    def get_comments(self) -> list[FakeTriageComment]:
        return [FakeTriageComment(self._repo, c) for c in self._repo.comments]

    def create_comment(self, body: str) -> FakeTriageComment:
        data: dict[str, object] = {"id": len(self._repo.comments) + 1, "body": body}
        self._repo.comments.append(data)
        return FakeTriageComment(self._repo, data)

    def get_comment(self, comment_id: int) -> FakeTriageComment:
        for c in self._repo.comments:
            if int(c["id"]) == comment_id:  # type: ignore[arg-type]
                return FakeTriageComment(self._repo, c)
        raise AssertionError(f"Missing comment {comment_id}")

    def get_events(self) -> list[object]:
        return []


class FakeTriageGitHubClient:
    """A minimal stand-in for ``github.Repository.Repository``."""

    def __init__(self) -> None:
        self.comments: list[dict[str, object]] = []
        self.added_labels: list[str] = []
        self.removed_labels: list[str] = []
        self.updated_issue_body = ""
        self.deleted_comment_ids: list[int] = []

    def issue(self, data: dict[str, object]) -> FakeTriageIssue:
        """Wrap *data* as a PyGitHub-like Issue bound to this fake repository."""
        return FakeTriageIssue(self, data)

    def get_issue(self, issue_number: int) -> FakeTriageIssue:
        return FakeTriageIssue(self, {"number": issue_number})

    def _append_comment(self, body: str) -> dict[str, object]:
        comment: dict[str, object] = {"id": len(self.comments) + 1, "body": body}
        self.comments.append(comment)
        return comment


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
