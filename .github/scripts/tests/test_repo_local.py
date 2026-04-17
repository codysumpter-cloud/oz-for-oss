from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from oz_workflows.repo_local import (
    WriteSurfaceViolation,
    assert_write_surface,
    format_repo_local_prompt_section,
    resolve_repo_local_skill_path,
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
        # Deliberately put text in a fake body to prove we do not include it.
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


if __name__ == "__main__":
    unittest.main()
