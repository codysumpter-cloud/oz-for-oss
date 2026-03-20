from __future__ import annotations

import json
import os

from oz_automation.context import get_repo_ref, load_event
from oz_automation.github_client import (
    extract_issue_numbers,
    get_non_pr_issue,
    get_pull_changed_files,
    get_repository,
    labels_to_names,
    list_open_issues_with_label,
)
from oz_automation.outputs import set_output
from oz_automation.oz_client import start_run, wait_for_run


def _close_comment(issue_number: int, required_label: str, has_code_changes: bool, docs_url: str) -> str:
    if has_code_changes:
        return (
            f"The PR that you've opened seems to contain code changes and is associated with issue #{issue_number}, "
            f"which is not marked as `{required_label}`. This PR will be automatically closed. Please see our "
            f"[contribution docs]({docs_url}) for guidance on when code changes are accepted for issues."
        )
    return (
        f"The PR that you've opened seems to contain plan changes and is associated with issue #{issue_number}, "
        f"which is not marked as `{required_label}`. This PR will be automatically closed. Please see our "
        f"[contribution docs]({docs_url}) for guidance on when plan changes are accepted for issues."
    )


def main() -> int:
    event = load_event()
    repo_ref = get_repo_ref(event)
    repo = get_repository(repo_ref)
    pr_number = int(os.getenv("PR_NUMBER", "0"))
    if pr_number <= 0:
        raise RuntimeError("PR_NUMBER must be set for enforce-pr-issue-state.")

    pr = repo.get_pull(pr_number)
    if pr.state != "open":
        set_output("allow_review", "false")
        return 0

    changed_files = get_pull_changed_files(pr)
    non_markdown_files = [path for path in changed_files if not path.lower().endswith(".md")]
    has_code_changes = len(non_markdown_files) > 0
    required_label = "ready-to-implement" if has_code_changes else "ready-to-plan"
    docs_url = f"https://github.com/{repo_ref.full_name}#readme"

    explicit_issue_numbers = extract_issue_numbers(pr.body or "", repo_ref.owner, repo_ref.repo)
    for issue_number in explicit_issue_numbers:
        issue = get_non_pr_issue(repo, issue_number)
        if issue is None:
            continue
        labels = labels_to_names(issue.labels)
        if required_label in labels:
            set_output("allow_review", "true")
            return 0
        repo.get_issue(number=pr.number).create_comment(
            _close_comment(issue_number, required_label, has_code_changes, docs_url)
        )
        pr.edit(state="closed")
        set_output("allow_review", "false")
        return 0

    candidate_issues = [
        {
            "number": issue.number,
            "title": issue.title,
            "body": issue.body or "",
            "url": issue.html_url,
            "labels": labels_to_names(issue.labels),
        }
        for issue in list_open_issues_with_label(repo, required_label)
    ]

    prompt = f"""Determine whether pull request #{pr.number} in {repo_ref.full_name} is clearly associated with one of the ready issues below.

Pull request details:
- Title: {pr.title}
- URL: {pr.html_url}
- Base branch: {pr.base.ref}
- Head branch: {pr.head.ref}
- Change kind: {"implementation" if has_code_changes else "plan"}
- Required issue label: {required_label}
- Changed files: {", ".join(changed_files) if changed_files else "None"}

Pull request body:
{pr.body or "No description provided."}

Candidate ready issues:
{json.dumps(candidate_issues, indent=2)}

Rules:
- If the PR is clearly associated with one of the candidate issues, do not make any GitHub changes.
- If no candidate issue is a clear match, comment on the pull request with this exact message and then close the pull request:
{_close_comment(123456789, required_label, has_code_changes, docs_url).replace("123456789", "<issue-number>")}
- Replace `<issue-number>` in the comment with the most plausible explicitly referenced issue number if one exists, otherwise omit the number and say the PR could not be matched to an issue marked `{required_label}`.
- Do not modify repository code or branches.
"""

    run_id = start_run(
        prompt=prompt,
        title=f"Enforce issue-state for PR #{pr.number}",
        config_name=f"enforce-pr-{pr.number}",
    )
    run = wait_for_run(run_id, poll_interval_seconds=10)
    refreshed_pr = repo.get_pull(pr_number)

    if run.state != "SUCCEEDED" and refreshed_pr.state == "open":
        error_message = getattr(getattr(run, "status_message", None), "message", None) or "The enforcement run did not complete successfully."
        raise RuntimeError(error_message)

    set_output("allow_review", "true" if refreshed_pr.state == "open" else "false")
    return 0
