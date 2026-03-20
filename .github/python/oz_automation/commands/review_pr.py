from __future__ import annotations

import os

from oz_automation.context import get_repo_ref, load_event
from oz_automation.github_client import create_reaction, get_repository
from oz_automation.oz_client import start_run, wait_for_run


def main() -> int:
    repo_ref = get_repo_ref(load_event())
    repo = get_repository(repo_ref)
    pr_number = int(os.getenv("PR_NUMBER", "0"))
    if pr_number <= 0:
        raise RuntimeError("PR_NUMBER must be set for review-pr.")

    pr = repo.get_pull(pr_number)
    if pr.state != "open":
        return 0

    comment_id = os.getenv("COMMENT_ID", "").strip()
    if comment_id.isdigit() and int(comment_id) > 0:
        comment = repo.get_issue_comment(int(comment_id))
        create_reaction(comment, "eyes")

    requester = os.getenv("REQUESTER", "").strip() or os.getenv("GITHUB_ACTOR", "")
    trigger_source = os.getenv("TRIGGER_SOURCE", "").strip() or "workflow_call"
    review_focus = os.getenv("REVIEW_FOCUS", "").strip()
    focus_line = (
        f"Additional focus from @{requester}: {review_focus}"
        if review_focus
        else (
            f"The review was requested by @{requester} via /oz-review. Perform a general review if no extra guidance was provided."
            if trigger_source == "issue_comment"
            else "Perform a general review of the pull request."
        )
    )

    prompt = f"""Review pull request #{pr.number} in {repo_ref.full_name} and publish the review directly on GitHub.

Pull request details:
- Title: {pr.title}
- URL: {pr.html_url}
- Base branch: {pr.base.ref}
- Head branch: {pr.head.ref}
- Trigger source: {trigger_source}
- {focus_line}

Requirements:
- Use the repository skill `{repo_ref.full_name}:review-pr`.
- Inspect the pull request diff directly using GitHub-aware tools in the environment.
- Post the review directly to GitHub with inline comments when appropriate.
- Do not modify the code, open branches, or create pull requests as part of this review run.
"""

    run_id = start_run(
        prompt=prompt,
        title=f"PR review #{pr.number}",
        skill=f"{repo_ref.full_name}:review-pr",
        config_name=f"review-pr-{pr.number}",
    )
    run = wait_for_run(run_id, poll_interval_seconds=10)
    if run.state != "SUCCEEDED":
        error_message = getattr(getattr(run, "status_message", None), "message", None) or "The review run did not complete successfully."
        raise RuntimeError(error_message)
    return 0
