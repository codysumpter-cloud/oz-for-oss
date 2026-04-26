from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from oz_workflows.workflow_config import (
    SelfImprovementConfig,
    TriageWorkflowConfig,
    load_self_improvement_config,
    load_triage_workflow_config,
    resolve_repo_config_path,
)


def _write_config(repo_root: Path, text: str) -> Path:
    path = repo_root / ".github" / "oz" / "config.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class ResolveRepoConfigPathTest(unittest.TestCase):
    def test_prefers_consuming_repo_config(self) -> None:
        with TemporaryDirectory() as tempdir:
            workspace_root = Path(tempdir)
            workflow_root = workspace_root / "__oz_shared"
            consumer_config = _write_config(workspace_root, "version: 1\n")
            _write_config(workflow_root, "version: 1\n")
            with patch.dict(
                os.environ,
                {
                    "GITHUB_WORKSPACE": str(workspace_root),
                    "WORKFLOW_CODE_PATH": "__oz_shared",
                },
                clear=False,
            ):
                self.assertEqual(
                    resolve_repo_config_path(workspace_root),
                    consumer_config.resolve(),
                )

    def test_falls_back_to_workflow_repo_config(self) -> None:
        with TemporaryDirectory() as tempdir:
            workspace_root = Path(tempdir)
            workflow_root = workspace_root / "__oz_shared"
            workflow_config = _write_config(workflow_root, "version: 1\n")
            with patch.dict(
                os.environ,
                {
                    "GITHUB_WORKSPACE": str(workspace_root),
                    "WORKFLOW_CODE_PATH": "__oz_shared",
                },
                clear=False,
            ):
                self.assertEqual(
                    resolve_repo_config_path(workspace_root),
                    workflow_config.resolve(),
                )


class LoadSelfImprovementConfigTest(unittest.TestCase):
    def test_loads_expected_values(self) -> None:
        with TemporaryDirectory() as tempdir:
            workspace_root = Path(tempdir)
            _write_config(
                workspace_root,
                (
                    "version: 1\n"
                    "self_improvement:\n"
                    "  reviewers:\n"
                    "    - octocat\n"
                    "  base_branch: develop\n"
                ),
            )
            config = load_self_improvement_config(workspace_root)
            self.assertEqual(
                config,
                SelfImprovementConfig(reviewers=["octocat"], base_branch="develop"),
            )

    def test_missing_reviewers_means_auto_resolution(self) -> None:
        with TemporaryDirectory() as tempdir:
            workspace_root = Path(tempdir)
            _write_config(
                workspace_root,
                "version: 1\nself_improvement:\n  base_branch: auto\n",
            )
            config = load_self_improvement_config(workspace_root)
            self.assertIsNone(config.reviewers)
            self.assertIsNone(config.base_branch)

    def test_empty_reviewer_list_is_preserved(self) -> None:
        with TemporaryDirectory() as tempdir:
            workspace_root = Path(tempdir)
            _write_config(
                workspace_root,
                "version: 1\nself_improvement:\n  reviewers: []\n",
            )
            config = load_self_improvement_config(workspace_root)
            self.assertEqual(config.reviewers, [])

    def test_env_overrides_file_values(self) -> None:
        with TemporaryDirectory() as tempdir:
            workspace_root = Path(tempdir)
            _write_config(
                workspace_root,
                (
                    "version: 1\n"
                    "self_improvement:\n"
                    "  reviewers:\n"
                    "    - octocat\n"
                    "  base_branch: develop\n"
                ),
            )
            with patch.dict(
                os.environ,
                {
                    "SELF_IMPROVEMENT_REVIEWERS": "hubot,mona",
                    "SELF_IMPROVEMENT_BASE_BRANCH": "release",
                },
                clear=False,
            ):
                config = load_self_improvement_config(workspace_root)
            self.assertEqual(config.reviewers, ["hubot", "mona"])
            self.assertEqual(config.base_branch, "release")

    def test_config_reviewers_reject_at_prefixed_handles(self) -> None:
        with TemporaryDirectory() as tempdir:
            workspace_root = Path(tempdir)
            config_path = _write_config(
                workspace_root,
                (
                    "version: 1\n"
                    "self_improvement:\n"
                    "  reviewers:\n"
                    "    - \"@octocat\"\n"
                ),
            )
            with self.assertRaises(RuntimeError) as ctx:
                load_self_improvement_config(workspace_root)
            self.assertIn(str(config_path), str(ctx.exception))
            self.assertIn("without a leading '@'", str(ctx.exception))

    def test_env_reviewers_reject_at_prefixed_handles(self) -> None:
        with TemporaryDirectory() as tempdir:
            workspace_root = Path(tempdir)
            config_path = _write_config(workspace_root, "version: 1\n")
            with patch.dict(
                os.environ,
                {"SELF_IMPROVEMENT_REVIEWERS": "@hubot,mona"},
                clear=False,
            ):
                with self.assertRaises(RuntimeError) as ctx:
                    load_self_improvement_config(workspace_root)
            self.assertIn(str(config_path), str(ctx.exception))
            self.assertIn("without a leading '@'", str(ctx.exception))

    def test_invalid_version_fails(self) -> None:
        with TemporaryDirectory() as tempdir:
            workspace_root = Path(tempdir)
            config_path = _write_config(workspace_root, "version: 2\n")
            with self.assertRaises(RuntimeError) as ctx:
                load_self_improvement_config(workspace_root)
            self.assertIn(str(config_path), str(ctx.exception))
            self.assertIn("version", str(ctx.exception))

    def test_unknown_active_key_fails(self) -> None:
        with TemporaryDirectory() as tempdir:
            workspace_root = Path(tempdir)
            _write_config(
                workspace_root,
                "version: 1\nself_improvement:\n  reviewerz: [octocat]\n",
            )
            with self.assertRaises(RuntimeError) as ctx:
                load_self_improvement_config(workspace_root)
            self.assertIn("reviewerz", str(ctx.exception))

    def test_invalid_yaml_fails(self) -> None:
        with TemporaryDirectory() as tempdir:
            workspace_root = Path(tempdir)
            _write_config(workspace_root, "version: [1\n")
            with self.assertRaises(RuntimeError) as ctx:
                load_self_improvement_config(workspace_root)
            self.assertIn(".github/oz/config.yml", str(ctx.exception))


class LoadTriageWorkflowConfigTest(unittest.TestCase):
    def test_defaults_to_triaged_when_config_missing(self) -> None:
        with TemporaryDirectory() as tempdir:
            workspace_root = Path(tempdir)
            config = load_triage_workflow_config(workspace_root)
            self.assertEqual(
                config,
                TriageWorkflowConfig(prior_triage_labels=frozenset({"triaged"})),
            )

    def test_loads_configured_prior_triage_labels(self) -> None:
        with TemporaryDirectory() as tempdir:
            workspace_root = Path(tempdir)
            _write_config(
                workspace_root,
                (
                    "version: 1\n"
                    "triage:\n"
                    "  prior_triage_labels:\n"
                    "    - triaged\n"
                    "    - needs-info\n"
                ),
            )
            config = load_triage_workflow_config(workspace_root)
            self.assertEqual(
                config,
                TriageWorkflowConfig(
                    prior_triage_labels=frozenset({"triaged", "needs-info"})
                ),
            )

    def test_rejects_blank_prior_triage_labels(self) -> None:
        with TemporaryDirectory() as tempdir:
            workspace_root = Path(tempdir)
            config_path = _write_config(
                workspace_root,
                (
                    "version: 1\n"
                    "triage:\n"
                    "  prior_triage_labels:\n"
                    "    - ''\n"
                ),
            )
            with self.assertRaises(RuntimeError) as ctx:
                load_triage_workflow_config(workspace_root)
            self.assertIn(str(config_path), str(ctx.exception))
            self.assertIn("must not be blank", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
