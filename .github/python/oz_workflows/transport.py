from __future__ import annotations

import base64
import json
import re
import time
import uuid
from typing import Any

from .github_api import GitHubClient


TRANSPORT_PATTERN = re.compile(r"<!-- oz-workflow-transport (?P<payload>\{.*\}) -->", re.DOTALL)


def new_transport_token() -> str:
    return uuid.uuid4().hex


def parse_transport_comment(body: str) -> dict[str, Any] | None:
    match = TRANSPORT_PATTERN.search(body)
    if not match:
        return None
    payload = json.loads(match.group("payload"))
    encoded = payload.get("payload", "")
    decoded = base64.b64decode(encoded).decode("utf-8")
    payload["decoded_payload"] = decoded
    return payload


def poll_for_transport_payload(
    github: GitHubClient,
    owner: str,
    repo: str,
    issue_number: int,
    *,
    token: str,
    kind: str,
    timeout_seconds: int = 120,
    poll_interval_seconds: int = 5,
) -> tuple[dict[str, Any], int]:
    deadline = time.monotonic() + timeout_seconds
    while True:
        comments = github.list_issue_comments(owner, repo, issue_number)
        for comment in reversed(comments):
            body = comment.get("body") or ""
            parsed = parse_transport_comment(body)
            if not parsed:
                continue
            if parsed.get("token") != token or parsed.get("kind") != kind:
                continue
            return parsed, int(comment["id"])
        if time.monotonic() >= deadline:
            raise RuntimeError(
                f"Timed out waiting for Oz transport payload {kind} ({token}) on issue/PR #{issue_number}"
            )
        time.sleep(poll_interval_seconds)
