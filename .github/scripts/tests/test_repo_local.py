from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, call, patch

from oz_workflows.repo_local import (
    SelfImprovementConfig,
    WriteSurfaceViolation,
    assert_write_surface,
    changed_files_since_base_branch,
    format_repo_local_prompt_section,
    maybe_push_update_branch,
    resolve_repo_local_skill_path,
    resolve_self_improvement_base_branch,
    resolve_self_improvement_reviewers,
)


class ResolveRepoLocalSkillPathTest(unittest.TestCase):
    def _write_companion(self, workspace: Path, core_name: str, body: str) -> Path:
        companion_dir = workspace / ".agents" / "skills" / f"{core_name}-local"
        companion_dir.mkdir(parents=True)
        path = companion_dir / "SKILL.md"
        path.write_text(body, encoding="utf-8")
        return path

    def test_returns_none_when_file_missing(self) -> None:
        with TemporaryDirectory() as temp_dir:
            self.assertIsNone(
                resolve_repo_local_skill_path(Path(temp_dir), "review-pr")
            )

    def test_returns_none_when_file_empty(self) -> None:
        with TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            self._write_companion(workspace, "review-pr", "")
            self.assertIsNone(
                resolve_repo_local_skill_path(workspace, "review-pr")
            )

    def test_returns_none_when_frontmatter_only(self) -> None:
        frontmatter_only = (
            "---\n"
            "name: review-pr-local\n"
            "specializes: review-pr\n"
            "description: scaffold\n"
            "---\n"
        )
        with TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            self._write_companion(workspace, "review-pr", frontmatter_only)
            self.assertIsNone(
                resolve_repo_local_skill_path(workspace, "review-pr")
            )

    def test_returns_none_when_frontmatter_only_with_whitespace_after(self) -> None:
        frontmatter_only = (
            "---\n"
            "name: review-pr-local\n"
            "---\n"
            "   \n\n\t\n"
        )
        with TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            self._write_companion(workspace, "review-pr", frontmatter_only)
            self.assertIsNone(
                resolve_repo_local_skill_path(workspace, "review-pr")
            )

    def test_returns_path_when_body_present(self) -> None:
        body = (
            "---\n"
            "name: review-pr-local\n"
            "specializes: review-pr\n"
            "---\n"
            "# Repo-specific review guidance\n"
            "- Prefer conservative suggestions.\n"
        )
        with TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            path = self._write_companion(workspace, "review-pr", body)
            resolved = resolve_repo_local_skill_path(workspace, "review-pr")
            self.assertIsNotNone(resolved)
            assert resolved is not None
            self.assertEqual(resolved, path.resolve())

    def test_returns_path_without_frontmatter(self) -> None:
        body = "# bare markdown body\n"
        with TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            path = self._write_companion(workspace, "triage-issue", body)
            resolved = resolve_repo_local_skill_path(workspace, "triage-issue")
            self.assertIsNotNone(resolved)
            assert resolved is not None
            self.assertEqual(resolved, path.resolve())

    def test_returns_none_for_empty_skill_name(self) -> None:
        with TemporaryDirectory() as temp_dir:
            self.assertIsNone(resolve_repo_local_skill_path(Path(temp_dir), ""))
            self.assertIsNone(
                resolve_repo_local_skill_path(Path(temp_dir), "   ")
            )


class FormatRepoLocalPromptSectionTest(unittest.TestCase):
    def test_section_references_path_and_does_not_inline_body(self) -> None:
        companion_path = Path("/tmp/workspace/.agents/skills/review-pr-local/SKILL.md")
        companion_body = "SECRET_BODY_TOKEN_THAT_MUST_NOT_APPEAR"
        section = format_repo_local_prompt_section("review-pr", companion_path)
        self.assertIn(str(companion_path), section)
        self.assertIn("Repository-specific guidance", section)
        self.assertIn("review-pr", section)
        self.assertIn("override", section.lower())
        self.assertNotIn(companion_body, section)

    def test_section_mentions_override_reminder(self) -> None:
        section = format_repo_local_prompt_section(
            "triage-issue", Path("/x/.agents/skills/triage-issue-local/SKILL.md")
        )
        self.assertIn("output schema", section)
        self.assertIn("severity labels", section)
        self.assertIn("safety rules", section)


class AssertWriteSurfaceTest(unittest.TestCase):
    def test_passes_when_all_paths_match_allowed_prefix(self) -> None:
        assert_write_surface(
            [".agents/skills/review-pr-local/SKILL.md"],
            allowed_prefixes=[".agents/skills/review-pr-local/"],
            loop_name="update-pr-review",
        )

    def test_passes_with_empty_change_list(self) -> None:
        assert_write_surface(
            [],
            allowed_prefixes=[".agents/skills/review-pr-local/"],
            loop_name="update-pr-review",
        )

    def test_ignores_blank_lines(self) -> None:
        assert_write_surface(
            ["", "  ", ".agents/skills/review-pr-local/SKILL.md"],
            allowed_prefixes=[".agents/skills/review-pr-local/"],
            loop_name="update-pr-review",
        )

    def test_fails_when_path_outside_allowed_prefix(self) -> None:
        with self.assertRaises(WriteSurfaceViolation) as ctx:
            assert_write_surface(
                [".agents/skills/review-pr/SKILL.md"],
                allowed_prefixes=[".agents/skills/review-pr-local/"],
                loop_name="update-pr-review",
            )
        self.assertIn("update-pr-review", str(ctx.exception))
        self.assertIn(".agents/skills/review-pr/SKILL.md", str(ctx.exception))

    def test_fails_when_any_path_outside(self) -> None:
        with self.assertRaises(WriteSurfaceViolation):
            assert_write_surface(
                [
                    ".agents/skills/review-pr-local/SKILL.md",
                    ".github/scripts/review_pr.py",
                ],
                allowed_prefixes=[".agents/skills/review-pr-local/"],
                loop_name="update-pr-review",
            )


class ChangedFilesSinceBaseBranchTest(unittest.TestCase):
    @patch("oz_workflows.repo_local.subprocess.run")
    def test_uses_the_provided_base_branch(self, mock_run) -> None:
        mock_run.side_effect = [
            Mock(returncode=0, stdout="", stderr=""),
            Mock(returncode=0, stdout="a.py\nb.py\n", stderr=""),
        ]
        changed = changed_files_since_base_branch(
            Path("/tmp/repo"), "oz-agent/update-pr-review", "develop"
        )
        self.assertEqual(changed, ["a.py", "b.py"])
        self.assertEqual(
            mock_run.call_args_list[1],
            call(
                ["git", "diff", "--name-only", "origin/develop...oz-agent/update-pr-review"],
                cwd="/tmp/repo",
                capture_output=True,
                text=True,
                check=True,
            ),
        )


class ResolveSelfImprovementBaseBranchTest(unittest.TestCase):
    @patch("oz_workflows.repo_local._remote_branch_exists", return_value=True)
    def test_prefers_explicit_configured_branch(self, _mock_remote_exists) -> None:
        branch = resolve_self_improvement_base_branch(
            Path("/tmp/repo"),
            SelfImprovementConfig(reviewers=None, base_branch="develop"),
        )
        self.assertEqual(branch, "develop")

    @patch("oz_workflows.repo_local._remote_branch_exists", return_value=True)
    @patch("oz_workflows.repo_local._detect_default_branch", return_value="master")
    def test_detects_default_branch_when_config_is_auto(
        self, _mock_detect_default_branch, _mock_remote_exists
    ) -> None:
        branch = resolve_self_improvement_base_branch(
            Path("/tmp/repo"),
            SelfImprovementConfig(reviewers=None, base_branch=None),
        )
        self.assertEqual(branch, "master")

    @patch("oz_workflows.repo_local._detect_default_branch", return_value=None)
    def test_fails_when_default_branch_cannot_be_detected(
        self, _mock_detect_default_branch
    ) -> None:
        with self.assertRaises(RuntimeError) as ctx:
            resolve_self_improvement_base_branch(
                Path("/tmp/repo"),
                SelfImprovementConfig(reviewers=None, base_branch=None),
            )
        self.assertIn("SELF_IMPROVEMENT_BASE_BRANCH", str(ctx.exception))


class ResolveSelfImprovementReviewersTest(unittest.TestCase):
    def test_prefers_explicit_reviewer_list(self) -> None:
        with TemporaryDirectory() as temp_dir:
            reviewers = resolve_self_improvement_reviewers(
                Path(temp_dir),
                ["README.md"],
                SelfImprovementConfig(reviewers=["octocat"], base_branch=None),
            )
            self.assertEqual(reviewers, ["octocat"])

    def test_empty_explicit_reviewer_list_disables_assignment(self) -> None:
        with TemporaryDirectory() as temp_dir:
            reviewers = resolve_self_improvement_reviewers(
                Path(temp_dir),
                ["README.md"],
                SelfImprovementConfig(reviewers=[], base_branch=None),
            )
            self.assertEqual(reviewers, [])

    def test_derives_reviewers_from_stakeholders(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            stakeholders = repo_root / ".github" / "STAKEHOLDERS"
            stakeholders.parent.mkdir(parents=True)
            stakeholders.write_text(
                (
                    "# later rules win\n"
                    "/README.md @docs-owner\n"
                    "/.github/scripts/ @platform-owner @backup-owner\n"
                ),
                encoding="utf-8",
            )
            reviewers = resolve_self_improvement_reviewers(
                repo_root,
                ["README.md", ".github/scripts/repo_local.py"],
                SelfImprovementConfig(reviewers=None, base_branch=None),
            )
            self.assertEqual(reviewers, ["docs-owner", "platform-owner", "backup-owner"])

    def test_falls_back_to_codeowners_when_stakeholders_missing(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            codeowners = repo_root / ".github" / "CODEOWNERS"
            codeowners.parent.mkdir(parents=True)
            codeowners.write_text("/specs/ @spec-owner\n", encoding="utf-8")
            reviewers = resolve_self_improvement_reviewers(
                repo_root,
                ["specs/GH338/tech.md"],
                SelfImprovementConfig(reviewers=None, base_branch=None),
            )
            self.assertEqual(reviewers, ["spec-owner"])

    def test_returns_empty_when_no_owners_match(self) -> None:
        with TemporaryDirectory() as temp_dir:
            reviewers = resolve_self_improvement_reviewers(
                Path(temp_dir),
                ["README.md"],
                SelfImprovementConfig(reviewers=None, base_branch=None),
            )
            self.assertEqual(reviewers, [])


class MaybePushUpdateBranchTest(unittest.TestCase):
    @patch("oz_workflows.repo_local.subprocess.run")
    @patch("oz_workflows.repo_local.resolve_self_improvement_reviewers")
    @patch("oz_workflows.repo_local.resolve_self_improvement_base_branch")
    @patch("oz_workflows.repo_local.load_self_improvement_config")
    @patch("oz_workflows.repo_local._pr_exists_for_branch")
    @patch("oz_workflows.repo_local.changed_files_since_base_branch")
    @patch("oz_workflows.repo_local.branch_exists")
    def test_uses_resolved_base_branch_for_diff_and_pr_create(
        self,
        mock_branch_exists,
        mock_changed_files,
        mock_pr_exists,
        mock_load_config,
        mock_resolve_base_branch,
        mock_resolve_reviewers,
        mock_run,
    ) -> None:
        repo_root = Path("/tmp/repo")
        config = SelfImprovementConfig(reviewers=None, base_branch=None)
        mock_branch_exists.return_value = True
        mock_changed_files.return_value = [".agents/skills/review-pr-local/SKILL.md"]
        mock_pr_exists.return_value = False
        mock_load_config.return_value = config
        mock_resolve_base_branch.return_value = "develop"
        mock_resolve_reviewers.return_value = ["octocat", "hubot"]

        maybe_push_update_branch(
            repo_root,
            "oz-agent/update-pr-review",
            allowed_prefixes=[".agents/skills/review-pr-local/"],
            loop_name="update-pr-review",
            pr_title="chore: update",
            pr_body="body",
        )

        mock_changed_files.assert_called_once_with(
            repo_root, "oz-agent/update-pr-review", "develop"
        )
        mock_run.assert_has_calls(
            [
                call(
                    ["git", "push", "origin", "oz-agent/update-pr-review"],
                    cwd="/tmp/repo",
                    check=True,
                ),
                call(
                    [
                        "gh",
                        "pr",
                        "create",
                        "--head",
                        "oz-agent/update-pr-review",
                        "--base",
                        "develop",
                        "--title",
                        "chore: update",
                        "--body",
                        "body",
                        "--reviewer",
                        "octocat,hubot",
                    ],
                    cwd="/tmp/repo",
                    check=True,
                ),
            ]
        )

    @patch("oz_workflows.repo_local.subprocess.run")
    @patch("oz_workflows.repo_local.resolve_self_improvement_reviewers", return_value=[])
    @patch("oz_workflows.repo_local.resolve_self_improvement_base_branch", return_value="main")
    @patch(
        "oz_workflows.repo_local.load_self_improvement_config",
        return_value=SelfImprovementConfig(reviewers=None, base_branch=None),
    )
    @patch("oz_workflows.repo_local._pr_exists_for_branch", return_value=False)
    @patch(
        "oz_workflows.repo_local.changed_files_since_base_branch",
        return_value=[".agents/skills/dedupe-issue-local/SKILL.md"],
    )
    @patch("oz_workflows.repo_local.branch_exists", return_value=True)
    def test_omits_reviewer_flag_when_no_reviewers_resolve(
        self,
        _mock_branch_exists,
        _mock_changed_files,
        _mock_pr_exists,
        _mock_load_config,
        _mock_resolve_base_branch,
        _mock_resolve_reviewers,
        mock_run,
    ) -> None:
        maybe_push_update_branch(
            Path("/tmp/repo"),
            "oz-agent/update-dedupe",
            allowed_prefixes=[".agents/skills/dedupe-issue-local/"],
            loop_name="update-dedupe",
            pr_title="chore: update",
            pr_body="body",
        )
        create_call = mock_run.call_args_list[-1]
        self.assertNotIn("--reviewer", create_call.args[0])
        self.assertEqual(create_call.args[0][5], "--base")
        self.assertEqual(create_call.args[0][6], "main")


if __name__ == "__main__":
    unittest.main()
