from __future__ import annotations

from oz_workflows.env import load_event, repo_parts, repo_slug, require_env
from oz_workflows.github_api import GitHubClient
from oz_workflows.helpers import comment_metadata


def main() -> None:
    owner, repo = repo_parts()
    event = load_event()
    issue_number = int(event["issue"]["number"])
    assignee_login = event.get("assignee", {}).get("login") or "oz-agent"
    metadata = comment_metadata("comment-on-unready-assigned-issue", issue_number)
    body = "\n".join(
        [
            "This issue is assigned to Oz, but it is not labeled `ready-to-plan` or `ready-to-implement`, so there is no work to do yet.",
            "",
            metadata,
        ]
    )
    with GitHubClient(require_env("GH_TOKEN"), repo_slug()) as github:
        github.create_comment(owner, repo, issue_number, body)
        github.remove_assignees(owner, repo, issue_number, [assignee_login])


if __name__ == "__main__":
    main()
