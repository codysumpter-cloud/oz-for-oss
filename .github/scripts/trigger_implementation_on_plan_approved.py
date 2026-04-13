from __future__ import annotations

import json
import os
import tempfile
from contextlib import closing

from github import Auth, Github

from oz_workflows.env import load_event, repo_parts, repo_slug, require_env
from oz_workflows.helpers import (
    is_automation_user,
    resolve_issue_number_for_pr,
)


def main() -> None:
    owner, repo = repo_parts()
    event = load_event()
    pr = event["pull_request"]

    if pr.get("state") != "open":
        return

    if is_automation_user(event.get("sender")):
        return

    with closing(Github(auth=Auth.Token(require_env("GH_TOKEN")))) as client:
        github = client.get_repo(repo_slug())
        pr_obj = github.get_pull(int(pr["number"]))
        files = list(pr_obj.get_files())
        changed_files = [str(f.filename) for f in files]

        issue_number = resolve_issue_number_for_pr(github, owner, repo, pr_obj, changed_files)
        if not issue_number:
            return

        issue = github.get_issue(issue_number)
        labels = {label.name for label in issue.labels}
        assignees = {a.login for a in issue.assignees}

        if "ready-to-implement" not in labels:
            return
        if "oz-agent" not in assignees:
            return

        # Build a synthetic event payload in the format expected by
        # create_implementation_from_issue.main().
        synthetic_event = {
            "issue": {
                "number": issue.number,
                "title": issue.title,
                "body": issue.body or "",
                "labels": [{"name": label.name} for label in issue.labels],
                "assignees": [{"login": a.login} for a in issue.assignees],
            },
            "repository": event["repository"],
            "sender": event.get("sender", {}),
        }

        tmp_fd, tmp_event_path = tempfile.mkstemp(suffix=".json")
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as handle:
                json.dump(synthetic_event, handle)
            os.environ["GITHUB_EVENT_PATH"] = tmp_event_path

            from create_implementation_from_issue import main as run_implementation

            run_implementation()
        finally:
            if os.path.exists(tmp_event_path):
                os.unlink(tmp_event_path)


if __name__ == "__main__":
    main()
