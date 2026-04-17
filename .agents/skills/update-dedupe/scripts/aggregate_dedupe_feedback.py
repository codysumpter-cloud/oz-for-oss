#!/usr/bin/env python3
"""Aggregate recent closed-as-duplicate signals into JSON.

The output feeds the ``update-dedupe`` self-improvement loop. Signals
collected: issues closed as duplicates (``state_reason == "not_planned"``
with a ``duplicate`` label or an explicit maintainer comment pointing at a
canonical thread), along with the inferred canonical issue.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Any


DEFAULT_REPO = "warpdotdev/oz-for-oss"
ORG_MEMBER_ASSOCIATIONS = {"COLLABORATOR", "MEMBER", "OWNER"}
DUPLICATE_PATTERN = re.compile(
    r"(?:duplicate\s+of|dup(?:licate)?\s*(?:of)?\s*)?#(\d+)",
    re.IGNORECASE,
)


def _gh_api(args: list[str]) -> Any:
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


def _issue_has_duplicate_label(issue: dict[str, Any]) -> bool:
    labels = issue.get("labels") or []
    for label in labels:
        name = label.get("name") if isinstance(label, dict) else ""
        if name == "duplicate":
            return True
    return False


def _canonical_candidates_from_comments(
    repo: str, issue_number: int
) -> list[int]:
    try:
        comments = _gh_api(
            [
                "--paginate",
                f"repos/{repo}/issues/{issue_number}/comments",
            ]
        )
    except subprocess.CalledProcessError:
        return []
    candidates: list[int] = []
    for comment in comments:
        if not isinstance(comment, dict):
            continue
        association = comment.get("author_association") or "NONE"
        if association not in ORG_MEMBER_ASSOCIATIONS:
            continue
        body = comment.get("body") or ""
        for match in DUPLICATE_PATTERN.finditer(body):
            try:
                num = int(match.group(1))
            except (TypeError, ValueError):
                continue
            if num and num != issue_number and num not in candidates:
                candidates.append(num)
    return candidates


def build_payload(repo: str, days: int) -> dict[str, Any]:
    cutoff = _since(days)
    closed_issues = _gh_api(
        [
            "--paginate",
            f"repos/{repo}/issues?state=closed&per_page=100",
        ]
    )
    if not isinstance(closed_issues, list):
        closed_issues = []

    records: list[dict[str, Any]] = []
    for issue in closed_issues:
        if not isinstance(issue, dict):
            continue
        if issue.get("pull_request"):
            continue
        closed_at = issue.get("closed_at") or ""
        try:
            when = datetime.fromisoformat(closed_at.replace("Z", "+00:00"))
        except ValueError:
            continue
        if when < cutoff:
            continue
        state_reason = issue.get("state_reason") or ""
        has_dup_label = _issue_has_duplicate_label(issue)
        if state_reason != "not_planned" and not has_dup_label:
            continue

        issue_number = int(issue.get("number") or 0)
        canonical_candidates = _canonical_candidates_from_comments(
            repo, issue_number
        )
        records.append(
            {
                "number": issue_number,
                "title": issue.get("title") or "",
                "url": issue.get("html_url") or "",
                "closed_at": closed_at,
                "state_reason": state_reason,
                "has_duplicate_label": has_dup_label,
                "canonical_candidates": canonical_candidates,
            }
        )

    return {
        "repo": repo,
        "lookback_days": days,
        "generated_at": _iso_now(),
        "closed_as_duplicate": records,
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
