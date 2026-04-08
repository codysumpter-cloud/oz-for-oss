from __future__ import annotations

import base64
import binascii
import gzip
import json
import re
import time
import uuid
import zlib
from typing import Any
from github.Repository import Repository


TRANSPORT_PATTERN = re.compile(r"<!-- oz-workflow-transport (?P<payload>\{.*\}) -->", re.DOTALL)
BASE64_ENCODING = "base64"
GZIP_BASE64_ENCODING = "gzip+base64"


def new_transport_token() -> str:
    return uuid.uuid4().hex


def encode_transport_payload(decoded_payload: str, *, encoding: str = GZIP_BASE64_ENCODING) -> str:
    payload_bytes = decoded_payload.encode("utf-8")
    if encoding == BASE64_ENCODING:
        encoded_bytes = payload_bytes
    elif encoding == GZIP_BASE64_ENCODING:
        encoded_bytes = gzip.compress(payload_bytes, compresslevel=9, mtime=0)
    else:
        raise ValueError(f"Unsupported transport encoding: {encoding}")
    return base64.b64encode(encoded_bytes).decode("utf-8")


def decode_transport_payload(encoded_payload: str, *, encoding: str) -> str:
    decoded_bytes = base64.b64decode(encoded_payload, validate=True)
    if encoding == BASE64_ENCODING:
        payload_bytes = decoded_bytes
    elif encoding == GZIP_BASE64_ENCODING:
        payload_bytes = gzip.decompress(decoded_bytes)
    else:
        raise ValueError(f"Unsupported transport encoding: {encoding}")
    return payload_bytes.decode("utf-8")


def parse_transport_comment(body: str) -> dict[str, Any] | None:
    match = TRANSPORT_PATTERN.search(body)
    if not match:
        return None
    try:
        payload = json.loads(match.group("payload"))
        if not isinstance(payload, dict):
            return None
        encoded = str(payload.get("payload", "") or "")
        encoding = str(payload.get("encoding") or BASE64_ENCODING).strip().lower()
        decoded = decode_transport_payload(encoded, encoding=encoding)
    except (TypeError, ValueError, json.JSONDecodeError, binascii.Error, UnicodeDecodeError, OSError, zlib.error, EOFError):
        return None
    payload["decoded_payload"] = decoded
    return payload


def cleanup_transport_comments(
    github: Repository | Any,
    owner: str,
    repo: str,
    issue_number: int,
) -> None:
    """Delete any oz-workflow-transport comments on the given issue/PR. Best-effort."""
    try:
        if hasattr(github, "get_issue"):
            comments = list(github.get_issue(issue_number).get_comments())
        else:
            comments = github.list_issue_comments(owner, repo, issue_number)
        for comment in comments:
            body = (
                str(comment.get("body") or "")
                if isinstance(comment, dict)
                else str(getattr(comment, "body", "") or "")
            )
            if not TRANSPORT_PATTERN.search(body):
                continue
            try:
                comment_id = (
                    comment.get("id")
                    if isinstance(comment, dict)
                    else getattr(comment, "id", None)
                )
                if comment_id is not None:
                    if hasattr(comment, "delete"):
                        comment.delete()
                    else:
                        from .helpers import _delete_issue_comment

                        _delete_issue_comment(
                            github, owner, repo, issue_number, int(comment_id)
                        )
            except Exception:
                pass
    except Exception:
        pass


def poll_for_transport_payload(
    github: Repository | Any,
    owner: str,
    repo: str,
    issue_number: int,
    *,
    token: str,
    kind: str,
    timeout_seconds: int = 600,
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
