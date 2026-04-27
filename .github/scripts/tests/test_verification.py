from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from oz_workflows.verification import (
    VerificationArtifact,
    discover_verification_skills,
    format_verification_skills_for_prompt,
    list_downloadable_verification_artifacts,
    render_verification_comment,
)


class DiscoverVerificationSkillsTest(unittest.TestCase):
    def _write_skill(self, repo_root: Path, name: str, body: str) -> None:
        skill_dir = repo_root / ".agents" / "skills" / name
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(body, encoding="utf-8")

    def test_discovers_only_verification_true_skills(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            self._write_skill(
                repo_root,
                "verify-ui",
                (
                    "---\n"
                    "name: verify-ui\n"
                    "description: UI verification\n"
                    "metadata:\n"
                    "  verification: true\n"
                    "---\n"
                    "\n"
                    "# verify-ui\n"
                ),
            )
            self._write_skill(
                repo_root,
                "review-pr",
                (
                    "---\n"
                    "name: review-pr\n"
                    "description: Review PRs\n"
                    "---\n"
                    "\n"
                    "# review-pr\n"
                ),
            )

            skills = discover_verification_skills(repo_root)

            self.assertEqual(len(skills), 1)
            self.assertEqual(skills[0].name, "verify-ui")
            self.assertEqual(skills[0].description, "UI verification")

    def test_accepts_string_true_in_metadata(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            self._write_skill(
                repo_root,
                "verify-api",
                (
                    "---\n"
                    "name: verify-api\n"
                    "description: API verification\n"
                    "metadata:\n"
                    '  verification: "true"\n'
                    "---\n"
                    "\n"
                    "# verify-api\n"
                ),
            )

            skills = discover_verification_skills(repo_root)

            self.assertEqual([skill.name for skill in skills], ["verify-api"])

    def test_ignores_top_level_verification_flag_without_metadata(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            self._write_skill(
                repo_root,
                "verify-ui",
                (
                    "---\n"
                    "name: verify-ui\n"
                    "description: UI verification\n"
                    "verification: true\n"
                    "---\n"
                    "\n"
                    "# verify-ui\n"
                ),
            )

            skills = discover_verification_skills(repo_root)

            self.assertEqual(skills, [])

    def test_ignores_invalid_frontmatter(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            self._write_skill(
                repo_root,
                "broken",
                "---\nverification: [unterminated\n---\n",
            )
            self.assertEqual(discover_verification_skills(repo_root), [])


class FormatVerificationSkillsForPromptTest(unittest.TestCase):
    def test_formats_relative_paths(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            skill_dir = repo_root / ".agents" / "skills" / "verify-ui"
            skill_dir.mkdir(parents=True)
            skill_path = skill_dir / "SKILL.md"
            skill_path.write_text("", encoding="utf-8")
            text = format_verification_skills_for_prompt(
                [
                    SimpleNamespace(
                        name="verify-ui",
                        path=skill_path.resolve(),
                        description="UI verification",
                    )
                ],
                workspace_root=repo_root,
            )
            self.assertIn("`verify-ui`", text)
            self.assertIn("`.agents/skills/verify-ui/SKILL.md`", text)
            self.assertIn("UI verification", text)


class ListDownloadableVerificationArtifactsTest(unittest.TestCase):
    @patch("oz_workflows.verification.build_oz_client")
    def test_collects_downloadable_screenshot_and_file_artifacts(
        self, mock_build_client: MagicMock
    ) -> None:
        run = SimpleNamespace(
            artifacts=[
                SimpleNamespace(
                    artifact_type="SCREENSHOT",
                    data=SimpleNamespace(artifact_uid="shot-1"),
                ),
                SimpleNamespace(
                    artifact_type="FILE",
                    data=SimpleNamespace(
                        artifact_uid="vid-1",
                        filename="demo.mp4",
                    ),
                ),
                SimpleNamespace(
                    artifact_type="FILE",
                    data=SimpleNamespace(
                        artifact_uid="report-1",
                        filename="verification_report.json",
                    ),
                ),
            ]
        )
        client = MagicMock()
        client.agent.get_artifact.side_effect = [
            SimpleNamespace(
                artifact_type="SCREENSHOT",
                data=SimpleNamespace(
                    download_url="https://example.test/shot.png",
                    content_type="image/png",
                    description="Login page",
                ),
            ),
            SimpleNamespace(
                artifact_type="FILE",
                data=SimpleNamespace(
                    download_url="https://example.test/demo.mp4",
                    content_type="video/mp4",
                    description="Verification recording",
                    filename="demo.mp4",
                ),
            ),
        ]
        mock_build_client.return_value = client

        artifacts = list_downloadable_verification_artifacts(
            run,
            exclude_filenames={"verification_report.json"},
        )

        self.assertEqual(len(artifacts), 2)
        self.assertTrue(artifacts[0].is_image)
        self.assertTrue(artifacts[1].is_video)


class RenderVerificationCommentTest(unittest.TestCase):
    def test_renders_summary_skills_and_artifacts(self) -> None:
        comment = render_verification_comment(
            {
                "overall_status": "passed",
                "summary": "Everything looked good.",
                "skills": [
                    {
                        "name": "verify-ui",
                        "path": ".agents/skills/verify-ui/SKILL.md",
                        "status": "passed",
                        "summary": "Loaded the UI successfully.",
                    }
                ],
            },
            session_link="https://warp.dev/session/123",
            artifacts=[
                VerificationArtifact(
                    artifact_type="SCREENSHOT",
                    title="home.png",
                    content_type="image/png",
                    download_url="https://example.test/home.png",
                    description="Home page",
                ),
                VerificationArtifact(
                    artifact_type="FILE",
                    title="demo.mp4",
                    content_type="video/mp4",
                    download_url="https://example.test/demo.mp4",
                    description="Demo video",
                ),
            ],
        )

        self.assertIn("## /oz-verify report", comment)
        self.assertIn("Status: **passed**", comment)
        self.assertIn("Session: [view on Warp](https://warp.dev/session/123)", comment)
        self.assertIn("`verify-ui` (`.agents/skills/verify-ui/SKILL.md`): **passed**", comment)
        self.assertIn("![Home page](https://example.test/home.png)", comment)
        self.assertIn("[Demo video](https://example.test/demo.mp4)", comment)


if __name__ == "__main__":
    unittest.main()
