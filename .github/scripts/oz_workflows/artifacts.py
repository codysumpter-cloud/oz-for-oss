from __future__ import annotations

import json
import time
from typing import Any, Protocol, cast

import httpx
from oz_agent_sdk import OzAPI
from oz_agent_sdk.types import AgentGetArtifactResponse
from oz_agent_sdk.types.agent import RunItem

from .oz_client import build_oz_client


class _FileArtifactDataLike(Protocol):
    artifact_uid: str
    filename: str | None


class _FileArtifactLike(Protocol):
    artifact_type: str
    data: _FileArtifactDataLike | None


def poll_for_artifact(
    run_id: str,
    *,
    filename: str,
    timeout_seconds: int = 120,
    poll_interval_seconds: int = 5,
) -> dict[str, Any]:
    """Retrieve a FILE artifact by filename from a completed Oz run.

    The caller should invoke this after ``run_agent()`` has returned
    (i.e. the run has reached a terminal SUCCEEDED state).  The artifact
    should already be present, but we poll briefly for resilience against
    propagation delay.
    """
    client = build_oz_client()
    deadline = time.monotonic() + timeout_seconds

    while True:
        run = client.agent.runs.retrieve(run_id)
        artifact_uid = _find_file_artifact(run, filename)
        if artifact_uid is not None:
            return _download_artifact_json(client, artifact_uid)
        if time.monotonic() >= deadline:
            raise RuntimeError(
                f"Timed out waiting for FILE artifact '{filename}' on Oz run {run_id}"
            )
        time.sleep(poll_interval_seconds)


def _find_file_artifact(run: RunItem, filename: str) -> str | None:
    """Return the artifact UID for a FILE artifact matching *filename*, or None."""
    artifacts = cast(list[_FileArtifactLike], run.artifacts or [])
    for artifact in artifacts:
        if artifact.artifact_type != "FILE":
            continue
        data = artifact.data
        if data is None:
            continue
        if data.filename == filename:
            return str(data.artifact_uid)
    return None


def _download_artifact_json(client: OzAPI, artifact_uid: str) -> dict[str, Any]:
    """Fetch a FILE artifact's signed URL and download its JSON content."""
    response: AgentGetArtifactResponse = client.agent.get_artifact(artifact_uid)
    download_url = response.data.download_url
    if not download_url:
        raise RuntimeError(
            f"Artifact {artifact_uid} did not return a download URL"
        )
    with httpx.Client(timeout=30) as http:
        for attempt in range(2):
            download_response = http.get(download_url)
            if download_response.status_code >= 500 and attempt == 0:
                time.sleep(1)
                continue
            download_response.raise_for_status()
            break
    payload = json.loads(download_response.text)
    if not isinstance(payload, dict):
        raise RuntimeError(
            f"Artifact {artifact_uid} must decode to a JSON object"
        )
    return payload
