from __future__ import annotations
from contextlib import closing
from github import Auth, Github

from oz_workflows.env import load_event, repo_parts, repo_slug, require_env
from oz_workflows.helpers import WorkflowProgressComment


def main() -> None:
    owner, repo = repo_parts()
    event = load_event()
    issue_number = int(event["issue"]["number"])
    assignee_login = event.get("assignee", {}).get("login") or "oz-agent"
    with closing(Github(auth=Auth.Token(require_env("GH_TOKEN")))) as client:
        github = client.get_repo(repo_slug())
        issue = github.get_issue(issue_number)
        progress = WorkflowProgressComment(
            github,
            owner,
            repo,
            issue_number,
            workflow="comment-on-unready-assigned-issue",
            event_payload=event,
        )
        progress.start("Oz is checking whether this assignment is ready for work.")
        progress.complete(
            "This issue is assigned to Oz, but it is not labeled `ready-to-spec` or `ready-to-implement`, so there is no work to do yet.",
        )
        issue.remove_from_assignees(assignee_login)


if __name__ == "__main__":
    main()
