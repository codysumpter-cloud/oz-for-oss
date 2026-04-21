from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from pathlib import Path

from oz_workflows import oz_client
from oz_workflows.oz_client import (
    _workflow_code_root,
    build_agent_config,
    build_oz_client,
    skill_file_path,
    skill_spec,
)


class BuildOzClientTest(unittest.TestCase):
    @patch.dict(
        os.environ,
        {"WARP_API_KEY": "fake-key", "STAGING_ORIGIN_TOKEN": "fake-token"},
        clear=True,
    )
    @patch("oz_workflows.oz_client.OzAPI")
    def test_default_headers_include_api_source(
        self, mock_oz_api: unittest.mock.MagicMock
    ) -> None:
        build_oz_client()
        _args, kwargs = mock_oz_api.call_args
        headers = kwargs["default_headers"]
        self.assertEqual(kwargs["base_url"], "https://staging.warp.dev/api/v1")
        self.assertEqual(headers["x-oz-api-source"], "GITHUB_ACTION")
        self.assertEqual(headers["X-Warp-Origin-Token"], "fake-token")

    @patch.dict(
        os.environ,
        {
            "WARP_API_KEY": "fake-key",
            "WARP_API_BASE_URL": "https://app.warp.dev/api/v1",
            "WARP_ORIGIN_TOKEN_ENV_NAME": "PROD_ORIGIN_TOKEN",
            "PROD_ORIGIN_TOKEN": "prod-token",
        },
        clear=True,
    )
    @patch("oz_workflows.oz_client.OzAPI")
    def test_uses_configured_base_url_and_origin_token_env_name(
        self, mock_oz_api: unittest.mock.MagicMock
    ) -> None:
        build_oz_client()
        _args, kwargs = mock_oz_api.call_args
        headers = kwargs["default_headers"]
        self.assertEqual(kwargs["base_url"], "https://app.warp.dev/api/v1")
        self.assertEqual(headers["X-Warp-Origin-Token"], "prod-token")


class SkillSpecTest(unittest.TestCase):
    def test_prefers_consuming_repo_skill_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            repo_root = Path(tempdir)
            skill_path = repo_root / ".agents/skills/implement-issue/SKILL.md"
            skill_path.parent.mkdir(parents=True)
            skill_path.write_text("# implement issue\n", encoding="utf-8")
            with patch.dict(
                os.environ,
                {
                    "GITHUB_REPOSITORY": "warpdotdev/consumer-repo",
                    "GITHUB_WORKSPACE": str(repo_root),
                    "WORKFLOW_CODE_REPOSITORY": "warpdotdev/oz-for-oss",
                    "WORKFLOW_CODE_PATH": "__oz_shared",
                },
                clear=False,
            ):
                self.assertEqual(
                    skill_spec("implement-issue"),
                    "warpdotdev/consumer-repo:.agents/skills/implement-issue/SKILL.md",
                )
                self.assertEqual(
                    skill_file_path("implement-issue"),
                    ".agents/skills/implement-issue/SKILL.md",
                )

    def test_falls_back_to_workflow_repo_skill_when_consumer_repo_lacks_it(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            repo_root = Path(tempdir)
            skill_path = repo_root / "__oz_shared/.agents/skills/implement-issue/SKILL.md"
            skill_path.parent.mkdir(parents=True)
            skill_path.write_text("# implement issue\n", encoding="utf-8")
            with patch.dict(
                os.environ,
                {
                    "GITHUB_REPOSITORY": "warpdotdev/consumer-repo",
                    "GITHUB_WORKSPACE": str(repo_root),
                    "WORKFLOW_CODE_REPOSITORY": "warpdotdev/oz-for-oss",
                    "WORKFLOW_CODE_PATH": "__oz_shared",
                },
                clear=False,
            ):
                self.assertEqual(
                    skill_spec("implement-issue"),
                    "warpdotdev/oz-for-oss:.agents/skills/implement-issue/SKILL.md",
                )
                self.assertEqual(
                    skill_file_path("implement-issue"),
                    "__oz_shared/.agents/skills/implement-issue/SKILL.md",
                )

    def test_preserves_relative_skill_file_path(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            repo_root = Path(tempdir)
            skill_path = repo_root / ".agents/skills/review-pr/SKILL.md"
            skill_path.parent.mkdir(parents=True)
            skill_path.write_text("# review pr\n", encoding="utf-8")
            with patch.dict(
                os.environ,
                {
                    "GITHUB_REPOSITORY": "warpdotdev/oz-oss-testbed",
                    "GITHUB_WORKSPACE": str(repo_root),
                },
                clear=False,
            ):
                self.assertEqual(
                    skill_spec(".agents/skills/review-pr/SKILL.md"),
                    "warpdotdev/oz-oss-testbed:.agents/skills/review-pr/SKILL.md",
                )
                self.assertEqual(
                    skill_file_path(".agents/skills/review-pr/SKILL.md"),
                    ".agents/skills/review-pr/SKILL.md",
                )

    def test_preserves_already_qualified_skill_spec(self) -> None:
        qualified = "warpdotdev/oz-oss-testbed:.agents/skills/create-tech-spec/SKILL.md"
        self.assertEqual(skill_spec(qualified), qualified)


class WorkflowCodeRootTest(unittest.TestCase):
    def test_honors_configured_absolute_path(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            with patch.dict(
                os.environ,
                {"WORKFLOW_CODE_PATH": str(root)},
                clear=False,
            ):
                self.assertEqual(_workflow_code_root(), root)

    def test_resolves_relative_configured_path_against_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            workspace_root = Path(tempdir)
            (workspace_root / "__oz_shared").mkdir()
            with patch.dict(
                os.environ,
                {
                    "GITHUB_WORKSPACE": str(workspace_root),
                    "WORKFLOW_CODE_PATH": "__oz_shared",
                },
                clear=False,
            ):
                self.assertEqual(
                    _workflow_code_root(), workspace_root / "__oz_shared"
                )

    def test_walks_up_to_github_sentinel(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            repo_root = Path(tempdir).resolve()
            nested = repo_root / ".github" / "scripts" / "oz_workflows"
            nested.mkdir(parents=True)
            fake_module = nested / "oz_client.py"
            fake_module.write_text("", encoding="utf-8")
            env_without_override = {
                key: value
                for key, value in os.environ.items()
                if key != "WORKFLOW_CODE_PATH"
            }
            with patch.dict(os.environ, env_without_override, clear=True), patch.object(
                oz_client, "__file__", str(fake_module)
            ):
                self.assertEqual(_workflow_code_root(), repo_root)

    def test_walks_up_when_module_is_nested_deeper(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            repo_root = Path(tempdir).resolve()
            nested = (
                repo_root
                / ".github"
                / "scripts"
                / "oz_workflows"
                / "extra"
                / "deeper"
            )
            nested.mkdir(parents=True)
            fake_module = nested / "oz_client.py"
            fake_module.write_text("", encoding="utf-8")
            env_without_override = {
                key: value
                for key, value in os.environ.items()
                if key != "WORKFLOW_CODE_PATH"
            }
            with patch.dict(os.environ, env_without_override, clear=True), patch.object(
                oz_client, "__file__", str(fake_module)
            ):
                self.assertEqual(_workflow_code_root(), repo_root)

    def test_raises_when_no_github_sentinel_found(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            nested = Path(tempdir).resolve() / "vendor" / "oz_workflows"
            nested.mkdir(parents=True)
            fake_module = nested / "oz_client.py"
            fake_module.write_text("", encoding="utf-8")
            env_without_override = {
                key: value
                for key, value in os.environ.items()
                if key != "WORKFLOW_CODE_PATH"
            }
            with patch.dict(os.environ, env_without_override, clear=True), patch.object(
                oz_client, "__file__", str(fake_module)
            ):
                with self.assertRaises(RuntimeError) as ctx:
                    _workflow_code_root()
                self.assertIn(".github", str(ctx.exception))


class BuildAgentConfigTest(unittest.TestCase):
    @patch.dict(os.environ, {"WARP_ENVIRONMENT_ID": "default-env"}, clear=False)
    def test_uses_warp_environment_id(self) -> None:
        config = build_agent_config(
            config_name="review-pull-request",
            workspace=Path("/tmp"),
        )
        self.assertEqual(config["environment_id"], "default-env")

    @patch.dict(os.environ, {}, clear=True)
    def test_requires_warp_environment_id(self) -> None:
        with self.assertRaises(RuntimeError):
            build_agent_config(
                config_name="review-pull-request",
                workspace=Path("/tmp"),
            )

    @patch.dict(os.environ, {"WARP_ENVIRONMENT_ID": "default-env"}, clear=True)
    def test_defaults_session_sharing_to_viewer(self) -> None:
        config = build_agent_config(
            config_name="review-pull-request",
            workspace=Path("/tmp"),
        )
        self.assertEqual(
            dict(config).get("session_sharing"),
            {"public_access": "VIEWER"},
        )

    @patch.dict(
        os.environ,
        {
            "WARP_ENVIRONMENT_ID": "default-env",
            "WARP_SESSION_SHARING_PUBLIC_ACCESS": "EDITOR",
        },
        clear=True,
    )
    def test_session_sharing_can_be_set_to_editor(self) -> None:
        config = build_agent_config(
            config_name="review-pull-request",
            workspace=Path("/tmp"),
        )
        self.assertEqual(
            dict(config).get("session_sharing"),
            {"public_access": "EDITOR"},
        )

    @patch.dict(
        os.environ,
        {
            "WARP_ENVIRONMENT_ID": "default-env",
            "WARP_SESSION_SHARING_PUBLIC_ACCESS": "viewer",
        },
        clear=True,
    )
    def test_session_sharing_is_case_insensitive(self) -> None:
        config = build_agent_config(
            config_name="review-pull-request",
            workspace=Path("/tmp"),
        )
        self.assertEqual(
            dict(config).get("session_sharing"),
            {"public_access": "VIEWER"},
        )

    @patch.dict(
        os.environ,
        {
            "WARP_ENVIRONMENT_ID": "default-env",
            "WARP_SESSION_SHARING_PUBLIC_ACCESS": "none",
        },
        clear=True,
    )
    def test_session_sharing_can_be_disabled(self) -> None:
        config = build_agent_config(
            config_name="review-pull-request",
            workspace=Path("/tmp"),
        )
        self.assertNotIn("session_sharing", dict(config))

    @patch.dict(
        os.environ,
        {
            "WARP_ENVIRONMENT_ID": "default-env",
            "WARP_SESSION_SHARING_PUBLIC_ACCESS": "off",
        },
        clear=True,
    )
    def test_session_sharing_off_also_disables(self) -> None:
        config = build_agent_config(
            config_name="review-pull-request",
            workspace=Path("/tmp"),
        )
        self.assertNotIn("session_sharing", dict(config))

    @patch.dict(
        os.environ,
        {
            "WARP_ENVIRONMENT_ID": "default-env",
            "WARP_SESSION_SHARING_PUBLIC_ACCESS": "bogus",
        },
        clear=True,
    )
    def test_unknown_session_sharing_value_disables_sharing(self) -> None:
        config = build_agent_config(
            config_name="review-pull-request",
            workspace=Path("/tmp"),
        )
        self.assertNotIn("session_sharing", dict(config))


if __name__ == "__main__":
    unittest.main()
