from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from oz_workflows.artifacts import (
    _download_artifact_text,
    _download_artifact_json,
    _find_file_artifact,
    load_pr_description_artifact,
    poll_for_artifact,
    poll_for_text_artifact,
)


def _make_artifact(artifact_type: str, filename: str, artifact_uid: str) -> MagicMock:
    data = MagicMock()
    data.filename = filename
    data.artifact_uid = artifact_uid
    artifact = MagicMock()
    artifact.artifact_type = artifact_type
    artifact.data = data
    return artifact


class FindFileArtifactTest(unittest.TestCase):
    def test_finds_matching_file_artifact(self) -> None:
        run = MagicMock()
        run.artifacts = [
            _make_artifact("PLAN", "plan.md", "uid-plan"),
            _make_artifact("FILE", "review.json", "uid-review"),
        ]
        self.assertEqual(_find_file_artifact(run, "review.json"), "uid-review")

    def test_returns_none_when_no_match(self) -> None:
        run = MagicMock()
        run.artifacts = [
            _make_artifact("FILE", "other.json", "uid-other"),
        ]
        self.assertIsNone(_find_file_artifact(run, "review.json"))

    def test_returns_none_when_no_artifacts(self) -> None:
        run = MagicMock()
        run.artifacts = []
        self.assertIsNone(_find_file_artifact(run, "review.json"))

    def test_returns_none_when_artifacts_is_none(self) -> None:
        run = MagicMock()
        run.artifacts = None
        self.assertIsNone(_find_file_artifact(run, "review.json"))

    def test_skips_non_file_artifacts(self) -> None:
        run = MagicMock()
        run.artifacts = [
            _make_artifact("SCREENSHOT", "review.json", "uid-screenshot"),
        ]
        self.assertIsNone(_find_file_artifact(run, "review.json"))


class DownloadArtifactJsonTest(unittest.TestCase):
    @patch("oz_workflows.artifacts.httpx.Client")
    def test_downloads_text(self, mock_client_cls: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "## Summary\n- Item"
        mock_response.raise_for_status = MagicMock()
        mock_http = MagicMock()
        mock_http.get.return_value = mock_response
        mock_http.__enter__ = MagicMock(return_value=mock_http)
        mock_http.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_http

        client = MagicMock()
        artifact_response = MagicMock()
        artifact_response.data.download_url = "https://storage.example.com/signed-url"
        client.agent.get_artifact.return_value = artifact_response

        result = _download_artifact_text(client, "uid-123")
        self.assertEqual(result, "## Summary\n- Item")
        client.agent.get_artifact.assert_called_once_with("uid-123")
        mock_http.get.assert_called_once_with("https://storage.example.com/signed-url")

    @patch("oz_workflows.artifacts.httpx.Client")
    def test_downloads_and_parses_json(self, mock_client_cls: MagicMock) -> None:
        expected = {"summary": "looks good", "comments": []}
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = json.dumps(expected)
        mock_response.raise_for_status = MagicMock()
        mock_http = MagicMock()
        mock_http.get.return_value = mock_response
        mock_http.__enter__ = MagicMock(return_value=mock_http)
        mock_http.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_http

        client = MagicMock()
        artifact_response = MagicMock()
        artifact_response.data.download_url = "https://storage.example.com/signed-url"
        client.agent.get_artifact.return_value = artifact_response

        result = _download_artifact_json(client, "uid-123")
        self.assertEqual(result, expected)
        client.agent.get_artifact.assert_called_once_with("uid-123")
        mock_http.get.assert_called_once_with("https://storage.example.com/signed-url")

    def test_raises_when_no_download_url(self) -> None:
        client = MagicMock()
        artifact_response = MagicMock()
        artifact_response.data.download_url = None
        client.agent.get_artifact.return_value = artifact_response

        with self.assertRaises(RuntimeError):
            _download_artifact_json(client, "uid-123")


class PollForArtifactTest(unittest.TestCase):
    @patch("oz_workflows.artifacts.build_oz_client")
    @patch("oz_workflows.artifacts._download_artifact_json")
    def test_returns_immediately_when_artifact_present(
        self, mock_download: MagicMock, mock_build_client: MagicMock
    ) -> None:
        expected = {"hello": "world"}
        mock_download.return_value = expected

        run = MagicMock()
        run.artifacts = [_make_artifact("FILE", "review.json", "uid-abc")]
        client = MagicMock()
        client.agent.runs.retrieve.return_value = run
        mock_build_client.return_value = client

        result = poll_for_artifact("run-123", filename="review.json", timeout_seconds=0)
        self.assertEqual(result, expected)

    @patch("oz_workflows.artifacts.build_oz_client")
    @patch("oz_workflows.artifacts.time.sleep", return_value=None)
    def test_times_out_when_artifact_missing(
        self, _mock_sleep: MagicMock, mock_build_client: MagicMock
    ) -> None:
        run = MagicMock()
        run.artifacts = []
        client = MagicMock()
        client.agent.runs.retrieve.return_value = run
        mock_build_client.return_value = client

        with self.assertRaises(RuntimeError) as ctx:
            poll_for_artifact(
                "run-123",
                filename="review.json",
                timeout_seconds=0,
                poll_interval_seconds=0,
            )
        self.assertIn("Timed out", str(ctx.exception))

    @patch("oz_workflows.artifacts.build_oz_client")
    @patch("oz_workflows.artifacts._download_artifact_text")
    def test_returns_text_artifact_when_present(
        self, mock_download: MagicMock, mock_build_client: MagicMock
    ) -> None:
        mock_download.return_value = "PR body"

        run = MagicMock()
        run.artifacts = [_make_artifact("FILE", "pr_description.md", "uid-pr")]
        client = MagicMock()
        client.agent.runs.retrieve.return_value = run
        mock_build_client.return_value = client

        result = poll_for_text_artifact(
            "run-123",
            filename="pr_description.md",
            timeout_seconds=0,
        )
        self.assertEqual(result, "PR body")


class LoadPrDescriptionArtifactTest(unittest.TestCase):
    @patch("oz_workflows.artifacts.poll_for_text_artifact")
    def test_returns_stripped_description(self, mock_poll: MagicMock) -> None:
        mock_poll.return_value = "  Closes #42\n\n## Summary\n  "
        result = load_pr_description_artifact("run-123")
        self.assertEqual(result, "Closes #42\n\n## Summary")
        mock_poll.assert_called_once_with("run-123", filename="pr_description.md")

    @patch("oz_workflows.artifacts.poll_for_text_artifact")
    def test_raises_when_empty(self, mock_poll: MagicMock) -> None:
        mock_poll.return_value = "   "
        with self.assertRaises(RuntimeError) as ctx:
            load_pr_description_artifact("run-123")
        self.assertIn("empty", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
