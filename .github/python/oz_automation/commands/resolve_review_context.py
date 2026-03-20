from __future__ import annotations

import os
import re

from oz_automation.context import get_event_name, load_event
from oz_automation.outputs import set_output


SLASH_COMMAND_PATTERN = re.compile(r"(?:^|\s)/oz-review\b([\s\S]*)", re.IGNORECASE)
ALLOWED_ASSOCIATIONS = {"MEMBER", "OWNER"}


def main() -> int:
    event_name = get_event_name()
    event = load_event()

    should_review = False
    pr_number = ""
    trigger_source = event_name
    requester = os.getenv("GITHUB_ACTOR", "")
    focus = ""
    comment_id = ""

    if event_name == "workflow_dispatch":
        raw_pr_number = os.getenv("DISPATCH_PR_NUMBER", "").strip()
        if raw_pr_number.isdigit() and int(raw_pr_number) > 0:
            should_review = True
            pr_number = raw_pr_number
            focus = os.getenv("DISPATCH_FOCUS", "").strip()
    elif event_name == "issue_comment":
        issue = event["issue"]
        comment = event["comment"]
        body = comment.get("body") or ""
        association = comment.get("author_association") or ""
        requester = (comment.get("user") or {}).get("login") or requester
        comment_id = str(comment.get("id") or "")
        match = SLASH_COMMAND_PATTERN.search(body)
        if (
            issue.get("pull_request")
            and match
            and association in ALLOWED_ASSOCIATIONS
            and requester != "github-actions[bot]"
        ):
            should_review = True
            pr_number = str(issue["number"])
            focus = match.group(1).strip()

    set_output("should_review", "true" if should_review else "false")
    set_output("pr_number", pr_number if should_review else "")
    set_output("trigger_source", trigger_source)
    set_output("requester", requester)
    set_output("focus", focus)
    set_output("comment_id", comment_id if should_review else "")
    return 0
