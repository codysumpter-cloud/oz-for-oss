from __future__ import annotations

from oz_automation.context import get_repo_ref, load_event
from oz_automation.github_client import compose_body, get_repository, issue_metadata, remove_assignee


WORKFLOW_NAME = "comment-on-unready-assigned-issue"


def main() -> int:
    event = load_event()
    repo_ref = get_repo_ref(event)
    repo = get_repository(repo_ref)

    issue_payload = event["issue"]
    assignee = (event.get("assignee") or {}).get("login") or "oz-agent"
    issue = repo.get_issue(number=issue_payload["number"])

    issue.create_comment(
        compose_body(
            [
                "This issue is assigned to Oz, but it is not labeled `ready-to-plan` or `ready-to-implement`, so there is no work to do yet.",
            ],
            issue_metadata(WORKFLOW_NAME, issue.number),
        )
    )
    remove_assignee(issue, assignee)
    return 0
