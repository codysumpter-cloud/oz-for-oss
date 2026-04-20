#!/usr/bin/env python3
"""Aggregate recent maintainer feedback on triaged issues into JSON.

The output feeds the ``update-triage`` self-improvement loop. Signals
collected: issues triaged in the lookback window, subsequent maintainer
label changes (additions and removals), re-opens, and any follow-up
comments from organization members. Closed-as-duplicate events are
intentionally excluded; those are handled by the separate
``update-dedupe`` loop.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Any


DEFAULT_REPO = "warpdotdev/oz-for-oss"
ORG_MEMBER_ASSOCIATIONS = {"COLLABORATOR", "MEMBER", "OWNER"}


def _gh_api(args: list[str]) -> Any:
    """Run ``gh api`` with *args* and return the parsed JSON response."""
    result = subprocess.run(
        ["gh", "api", *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _since(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


def _issue_has_triaged_label(issue: dict[str, Any]) -> bool:
    labels = issue.get("labels") or []
    for label in labels:
        name = label.get("name") if isinstance(label, dict) else ""
        if name == "triaged":
            return True
    return False


def _issue_events(repo: str, issue_number: int) -> list[dict[str, Any]]:
    try:
        return _gh_api(
            [
                "--paginate",
                f"repos/{repo}/issues/{issue_number}/events",
            ]
        )
    except subprocess.CalledProcessError:
        return []


def _issue_comments(repo: str, issue_number: int) -> list[dict[str, Any]]:
    try:
        return _gh_api(
            [
                "--paginate",
                f"repos/{repo}/issues/{issue_number}/comments",
            ]
        )
    except subprocess.CalledProcessError:
        return []


def _label_events(events: list[dict[str, Any]], cutoff: datetime) -> list[dict[str, Any]]:
    label_events: list[dict[str, Any]] = []
    for event in events:
        kind = event.get("event") or ""
        if kind not in {"labeled", "unlabeled", "reopened"}:
            continue
        created_at = event.get("created_at") or ""
        try:
            when = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except ValueError:
            continue
        if when < cutoff:
            continue
        label_events.append(
            {
                "event": kind,
                "created_at": created_at,
                "actor": (event.get("actor") or {}).get("login") or "",
                "label": (event.get("label") or {}).get("name") or "",
            }
        )
    return label_events


def _maintainer_comments(
    comments: list[dict[str, Any]], cutoff: datetime
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for comment in comments:
        association = comment.get("author_association") or "NONE"
        if association not in ORG_MEMBER_ASSOCIATIONS:
            continue
        created_at = comment.get("created_at") or ""
        try:
            when = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except ValueError:
            continue
        if when < cutoff:
            continue
        selected.append(
            {
                "created_at": created_at,
                "author": (comment.get("user") or {}).get("login") or "",
                "body": comment.get("body") or "",
                "author_association": association,
            }
        )
    return selected


def build_payload(repo: str, days: int) -> dict[str, Any]:
    cutoff = _since(days)
    triaged_issues = _gh_api(
        [
            "--paginate",
            f"repos/{repo}/issues?state=all&labels=triaged&per_page=100",
        ]
    )
    if not isinstance(triaged_issues, list):
        triaged_issues = []

    records: list[dict[str, Any]] = []
    for issue in triaged_issues:
        if not isinstance(issue, dict):
            continue
        if issue.get("pull_request"):
            continue
        if not _issue_has_triaged_label(issue):
            continue
        updated_at = issue.get("updated_at") or ""
        try:
            when = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        except ValueError:
            continue
        if when < cutoff:
            continue

        issue_number = int(issue.get("number") or 0)
        events = _issue_events(repo, issue_number)
        label_events = _label_events(events, cutoff)
        comments = _issue_comments(repo, issue_number)
        maintainer_comments = _maintainer_comments(comments, cutoff)

        if not label_events and not maintainer_comments:
            continue

        records.append(
            {
                "number": issue_number,
                "title": issue.get("title") or "",
                "url": issue.get("html_url") or "",
                "labels": [
                    label.get("name")
                    for label in (issue.get("labels") or [])
                    if isinstance(label, dict)
                ],
                "label_events": label_events,
                "maintainer_comments": maintainer_comments,
                "state": issue.get("state") or "",
                "state_reason": issue.get("state_reason") or "",
            }
        )

    return {
        "repo": repo,
        "lookback_days": days,
        "generated_at": _iso_now(),
        "issues": records,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=DEFAULT_REPO, help="owner/name")
    parser.add_argument("--days", type=int, default=7, help="lookback window in days")
    parser.add_argument(
        "--output",
        default=None,
        help="output path; if omitted, a temp file is used and the path is printed",
    )
    args = parser.parse_args()

    payload = build_payload(args.repo, args.days)
    if args.output:
        output_path = args.output
        with open(output_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
    else:
        handle = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        )
        json.dump(payload, handle, indent=2)
        handle.close()
        output_path = handle.name
    print(output_path)


if __name__ == "__main__":
    main()
