from __future__ import annotations
from contextlib import closing

from github import Auth, Github

from oz_workflows.env import repo_parts, repo_slug, require_env
from oz_workflows.helpers import resolve_issue_number_for_pr


STALE_LABELS = {"ready-to-spec", "ready-to-implement"}


def main() -> None:
    owner, repo = repo_parts()
    pr_number = int(require_env("PR_NUMBER"))
    with closing(Github(auth=Auth.Token(require_env("GH_TOKEN")))) as client:
        github = client.get_repo(repo_slug())
        pr = github.get_pull(pr_number)
        if pr.state != "open":
            return
        files = list(pr.get_files())
        changed_files = [str(file.filename) for file in files]
        issue_number = resolve_issue_number_for_pr(
            github, owner, repo, pr, changed_files
        )
        if issue_number is None:
            return
        issue = github.get_issue(issue_number)
        issue_labels = {label.name for label in issue.labels}
        for label in STALE_LABELS & issue_labels:
            issue.remove_from_labels(label)


if __name__ == "__main__":
    main()
