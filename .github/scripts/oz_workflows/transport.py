from __future__ import annotations

import base64
import binascii
import json
import re
import time
import uuid
from typing import Any
from github.Repository import Repository


TRANSPORT_PATTERN = re.compile(r"<!-- oz-workflow-transport (?P<payload>\{.*\}) -->", re.DOTALL)


def new_transport_token() -> str:
    return uuid.uuid4().hex


def parse_transport_comment(body: str) -> dict[str, Any] | None:
    match = TRANSPORT_PATTERN.search(body)
    if not match:
        return None
    try:
        payload = json.loads(match.group("payload"))
        if not isinstance(payload, dict):
            return None
        encoded = payload.get("payload", "")
        decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
    except (TypeError, ValueError, json.JSONDecodeError, binascii.Error, UnicodeDecodeError):
        return None
    payload["decoded_payload"] = decoded
    return payload


def poll_for_transport_payload(
    github: Repository | Any,
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
        if hasattr(github, "get_issue"):
            comments = list(github.get_issue(issue_number).get_comments())
        else:
            comments = github.list_issue_comments(owner, repo, issue_number)
        for comment in reversed(comments):
            body = (
                str(comment.get("body") or "")
                if isinstance(comment, dict)
                else str(getattr(comment, "body", "") or "")
            )
            parsed = parse_transport_comment(body)
            if not parsed:
                continue
            if parsed.get("token") != token or parsed.get("kind") != kind:
                continue
            comment_id = comment.get("id") if isinstance(comment, dict) else getattr(comment, "id", None)
            return parsed, int(comment_id)
        if time.monotonic() >= deadline:
            raise RuntimeError(
                f"Timed out waiting for Oz transport payload {kind} ({token}) on issue/PR #{issue_number}"
            )
        time.sleep(poll_interval_seconds)
