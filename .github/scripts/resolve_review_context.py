from __future__ import annotations

import re

from oz_workflows.actions import notice, set_output
from oz_workflows.env import load_event, optional_env
from oz_workflows.helpers import ORG_MEMBER_ASSOCIATIONS


SLASH_COMMAND_PATTERN = re.compile(
    r"(?:^|\s)(?:/oz-review|@oz-agent\s+/review)\b([\s\S]*)", re.IGNORECASE
)


def main() -> None:
    event = load_event()
    event_name = event.get("event_name") or event.get("action")
    github_event_name = optional_env("GITHUB_EVENT_NAME")

    should_review = False
    pr_number = ""
    trigger_source = github_event_name
    requester = optional_env("GITHUB_ACTOR")
    focus = ""
    comment_id = ""

    if github_event_name == "workflow_dispatch":
        candidate = optional_env("DISPATCH_PR_NUMBER")
        focus = optional_env("DISPATCH_FOCUS")
        if candidate.isdigit() and int(candidate) > 0:
            should_review = True
            pr_number = candidate
    elif github_event_name == "issue_comment":
        issue = event["issue"]
        comment = event["comment"]
        body = comment.get("body") or ""
        match = SLASH_COMMAND_PATTERN.search(body)
        requester = comment.get("user", {}).get("login") or requester
        comment_id = str(comment.get("id") or "")
        if match:
            focus = match.group(1).strip()
        should_review = (
            bool(issue.get("pull_request"))
            and bool(match)
            and comment.get("author_association") in ORG_MEMBER_ASSOCIATIONS
            and requester != "github-actions[bot]"
        )
        if should_review:
            pr_number = str(issue["number"])

    set_output("should_review", "true" if should_review else "false")
    set_output("pr_number", pr_number if should_review else "")
    set_output("trigger_source", trigger_source)
    set_output("requester", requester)
    set_output("focus", focus)
    set_output("comment_id", comment_id)
    if not should_review:
        notice("PR review orchestration skipped after context resolution.")


if __name__ == "__main__":
    main()
