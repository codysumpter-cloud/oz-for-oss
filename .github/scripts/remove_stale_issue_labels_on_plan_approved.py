from __future__ import annotations

import logging
from contextlib import closing

from github import Auth, Github

from oz_workflows.env import repo_parts, repo_slug, require_env
from oz_workflows.helpers import resolve_pr_association

logger = logging.getLogger(__name__)

STALE_LABEL = "ready-to-spec"


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    owner, repo = repo_parts()
    pr_number = int(require_env("PR_NUMBER"))
    with closing(Github(auth=Auth.Token(require_env("GH_TOKEN")))) as client:
        github = client.get_repo(repo_slug())
        pr = github.get_pull(pr_number)
        if pr.state != "open":
            logger.info("PR #%s is not open; skipping.", pr_number)
            return

        changed_files = [str(file.filename) for file in pr.get_files()]
        association = resolve_pr_association(github, owner, repo, pr, changed_files)
        issue_number = association.get("primary_issue_number")
        if not isinstance(issue_number, int):
            ambiguous = association.get("ambiguous", False)
            same_repo = association.get("same_repo_issue_numbers") or []
            if ambiguous:
                logger.info(
                    "PR #%s has ambiguous association (%s); skipping label removal.",
                    pr_number,
                    ", ".join(f"#{n}" for n in same_repo),
                )
            else:
                logger.info("PR #%s has no resolvable primary issue; skipping.", pr_number)
            return

        issue = github.get_issue(issue_number)
        label_names = {label.name for label in issue.labels}
        if STALE_LABEL in label_names:
            issue.remove_from_labels(STALE_LABEL)
            logger.info("Removed '%s' from issue #%s.", STALE_LABEL, issue_number)
        else:
            logger.info("Issue #%s does not have '%s' label.", issue_number, STALE_LABEL)


if __name__ == "__main__":
    main()
