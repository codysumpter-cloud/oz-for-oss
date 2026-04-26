from __future__ import annotations

from contextlib import closing

from github import Auth, Github

from oz_workflows.env import repo_parts, repo_slug, require_env
from oz_workflows.helpers import resolve_pr_association


STALE_LABEL = "ready-to-spec"


def main() -> None:
    owner, repo = repo_parts()
    pr_number = int(require_env("PR_NUMBER"))
    with closing(Github(auth=Auth.Token(require_env("GH_TOKEN")))) as client:
        github = client.get_repo(repo_slug())
        pr = github.get_pull(pr_number)
        if pr.state != "open":
            return

        changed_files = [str(file.filename) for file in pr.get_files()]
        association = resolve_pr_association(github, owner, repo, pr, changed_files)
        issue_number = association.get("primary_issue_number")
        if not isinstance(issue_number, int):
            return

        issue = github.get_issue(issue_number)
        label_names = {label.name for label in issue.labels}
        if STALE_LABEL in label_names:
            issue.remove_from_labels(STALE_LABEL)


if __name__ == "__main__":
    main()
