from __future__ import annotations

import json
import random
import time
import warnings
from typing import Any, Protocol, cast

import httpx
from oz_agent_sdk import OzAPI
from oz_agent_sdk.types import AgentGetArtifactResponse
from oz_agent_sdk.types.agent import RunItem

from .oz_client import build_oz_client

# Retry policy for artifact downloads. A transient CDN or S3 blip can surface as
# either a 5xx response or as a network-level exception (connection reset, DNS
# flake, read timeout, etc.). We want to retry a handful of times with
# exponential backoff + jitter so a momentary failure at the tail end of an
# otherwise successful agent run does not cause the entire workflow to fail.
_DOWNLOAD_MAX_ATTEMPTS = 5
_DOWNLOAD_INITIAL_BACKOFF_SECONDS = 1.0
_DOWNLOAD_MAX_BACKOFF_SECONDS = 10.0

# Network-level httpx exceptions that are worth retrying. These cover the
# common transient failures for signed-URL downloads.
_RETRYABLE_NETWORK_EXCEPTIONS: tuple[type[BaseException], ...] = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadError,
    httpx.ReadTimeout,
    httpx.WriteError,
    httpx.WriteTimeout,
    httpx.PoolTimeout,
    httpx.RemoteProtocolError,
)


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
    artifact_uid = _poll_for_file_artifact_uid(
        client,
        run_id,
        filename=filename,
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
    )
    return _download_artifact_json(client, artifact_uid)


def poll_for_text_artifact(
    run_id: str,
    *,
    filename: str,
    timeout_seconds: int = 120,
    poll_interval_seconds: int = 5,
) -> str:
    """Retrieve a FILE artifact by filename and return its raw text content."""
    client = build_oz_client()
    artifact_uid = _poll_for_file_artifact_uid(
        client,
        run_id,
        filename=filename,
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
    )
    return _download_artifact_text(client, artifact_uid)


def _poll_for_file_artifact_uid(
    client: OzAPI,
    run_id: str,
    *,
    filename: str,
    timeout_seconds: int,
    poll_interval_seconds: int,
) -> str:
    """Wait for a FILE artifact by filename and return its artifact UID."""
    deadline = time.monotonic() + timeout_seconds

    while True:
        run = client.agent.runs.retrieve(run_id)
        artifact_uid = _find_file_artifact(run, filename)
        if artifact_uid is not None:
            return artifact_uid
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
    payload = json.loads(_download_artifact_text(client, artifact_uid))
    if not isinstance(payload, dict):
        raise RuntimeError(
            f"Artifact {artifact_uid} must decode to a JSON object"
        )
    return payload


def _download_artifact_text(client: OzAPI, artifact_uid: str) -> str:
    """Fetch a FILE artifact's signed URL and download its text content.

    The download is retried with exponential backoff + jitter on 5xx
    responses and on transient httpx network errors (connect/read timeouts,
    protocol errors, etc.). 4xx responses are not retried and surface
    immediately as ``httpx.HTTPStatusError``.
    """
    response: AgentGetArtifactResponse = client.agent.get_artifact(artifact_uid)
    download_url = response.data.download_url
    if not download_url:
        raise RuntimeError(
            f"Artifact {artifact_uid} did not return a download URL"
        )
    with httpx.Client(timeout=30) as http:
        return _download_text_with_retries(http, download_url, artifact_uid)


def _download_text_with_retries(
    http: httpx.Client, download_url: str, artifact_uid: str
) -> str:
    """GET *download_url* with retries on 5xx and transient network errors.

    Returns the response text on success. Raises the last encountered error
    after ``_DOWNLOAD_MAX_ATTEMPTS`` failed attempts.
    """
    last_error: Exception | None = None
    for attempt in range(_DOWNLOAD_MAX_ATTEMPTS):
        try:
            download_response = http.get(download_url)
        except _RETRYABLE_NETWORK_EXCEPTIONS as exc:
            last_error = exc
        else:
            if download_response.status_code < 500:
                # 2xx returns the body; 4xx raises a non-retryable error.
                download_response.raise_for_status()
                return download_response.text
            last_error = httpx.HTTPStatusError(
                (
                    f"Server error {download_response.status_code} while "
                    f"downloading artifact {artifact_uid}"
                ),
                request=download_response.request,
                response=download_response,
            )

        if attempt >= _DOWNLOAD_MAX_ATTEMPTS - 1:
            break
        backoff = min(
            _DOWNLOAD_INITIAL_BACKOFF_SECONDS * (2**attempt),
            _DOWNLOAD_MAX_BACKOFF_SECONDS,
        )
        # Add jitter to avoid thundering-herd style retry storms across
        # concurrently-running workflows.
        time.sleep(backoff + random.uniform(0, 1))

    # At least one attempt always runs, so last_error is set when we exit
    # the loop without returning. Guard against the theoretical case where
    # it isn't so we don't raise ``TypeError`` under ``python -O`` (which
    # strips ``assert`` statements).
    if last_error is None:
        raise RuntimeError(
            f"Exhausted retries downloading artifact {artifact_uid} "
            "without recording an error"
        )
    raise last_error


PR_DESCRIPTION_FILENAME = "pr_description.md"

PR_METADATA_FILENAME = "pr-metadata.json"

_PR_METADATA_REQUIRED_KEYS = ("branch_name", "pr_title", "pr_summary")


def load_pr_metadata_artifact(run_id: str) -> dict[str, Any]:
    """Load and validate the pr-metadata.json artifact from a completed Oz run.

    The artifact must be a JSON object containing at least the keys
    ``branch_name``, ``pr_title``, and ``pr_summary``.
    """
    metadata = poll_for_artifact(
        run_id,
        filename=PR_METADATA_FILENAME,
    )
    missing = [key for key in _PR_METADATA_REQUIRED_KEYS if key not in metadata]
    if missing:
        raise RuntimeError(
            f"pr-metadata.json artifact from Oz run {run_id} is missing "
            f"required key(s): {', '.join(missing)}"
        )
    pr_summary = metadata.get("pr_summary", "")
    if not isinstance(pr_summary, str) or not pr_summary.strip():
        raise RuntimeError(
            f"pr-metadata.json artifact from Oz run {run_id} has an empty pr_summary"
        )
    return metadata


def load_pr_description_artifact(run_id: str) -> str:
    """Load and validate the pr_description.md artifact from a completed Oz run.

    .. deprecated::
        Use :func:`load_pr_metadata_artifact` instead, which reads the
        structured ``pr-metadata.json`` artifact.
    """
    warnings.warn(
        "load_pr_description_artifact is deprecated; use load_pr_metadata_artifact instead",
        DeprecationWarning,
        stacklevel=2,
    )
    pr_description = poll_for_text_artifact(
        run_id,
        filename=PR_DESCRIPTION_FILENAME,
    ).strip()
    if not pr_description:
        raise RuntimeError(
            f"Oz run {run_id} produced an empty {PR_DESCRIPTION_FILENAME} artifact"
        )
    return pr_description
