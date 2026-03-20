from __future__ import annotations

from typing import Iterable

from oz_automation.context import get_repo_ref, load_event
from oz_automation.github_client import (
    get_repository,
    issue_author_login,
    labels_to_names,
    list_comments,
    list_pulls_by_head,
    upsert_comment,
)
from oz_automation.oz_client import (
    get_pull_request_urls,
    get_session_link,
    start_run,
    wait_for_run,
    wait_for_session_link,
)


WORKFLOW_NAME = "create-plan-from-issue"


def _member_comments_text(comments: Iterable) -> str:
    filtered = [
        f"- {comment.user.login if comment.user else 'unknown'} ({comment.created_at.isoformat()}): {comment.body or ''}"
        for comment in comments
        if getattr(comment, "author_association", "") in {"MEMBER", "OWNER"}
    ]
    return "\n".join(filtered) if filtered else "None."


def _build_status_lines(message: str, session_link: str = "", extra: list[str] | None = None) -> list[str]:
    lines = [message]
    if session_link:
        lines.extend(["", f"Session: {session_link}"])
    if extra:
        lines.extend(["", *extra])
    return lines


def main() -> int:
    event = load_event()
    repo_ref = get_repo_ref(event)
    repo = get_repository(repo_ref)
    issue = repo.get_issue(number=event["issue"]["number"])
    default_branch = (event.get("repository") or {}).get("default_branch") or repo.default_branch
    comments_text = _member_comments_text(list_comments(issue))
    branch_name = f"oz-agent/plan-issue-{issue.number}"
    pr_title = f"Plan: {issue.title}"

    upsert_comment(
        issue,
        WORKFLOW_NAME,
        ["Oz is starting work on an implementation plan for this issue."],
    )

    labels = ", ".join(labels_to_names(issue.labels)) or "None"
    assignees = ", ".join(assignee.login for assignee in issue.assignees) or "None"
    prompt = f"""Create and publish a plan pull request for GitHub Issue #{issue.number} in {repo_ref.full_name}.

Issue details:
- Title: {issue.title}
- Author: @{issue_author_login(issue)}
- Labels: {labels}
- Assignees: {assignees}
- Default branch: {default_branch}
- Required plan branch: {branch_name}
- Required pull request title: {pr_title}
- The pull request should target `{default_branch}`.

Issue description:
{issue.body or "No description provided."}

Organization-member comments:
{comments_text}

Publishing requirements:
- Use the repository skill `{repo_ref.full_name}:create-plan`.
- Create or update `plans/issue-{issue.number}.md`.
- Commit only the plan file.
- Create or update the pull request for `{branch_name}` targeting `{default_branch}`.
- Use the pull request body to summarize the plan, assumptions, and open questions.
- Do not commit temporary scratch files or unrelated changes.
"""

    run_id = start_run(
        prompt=prompt,
        title=f"Create plan for issue #{issue.number}",
        skill=f"{repo_ref.full_name}:create-plan",
        config_name=f"plan-issue-{issue.number}",
    )
    session_link = wait_for_session_link(run_id)
    upsert_comment(
        issue,
        WORKFLOW_NAME,
        _build_status_lines(
            "Oz is working on an implementation plan for this issue.",
            session_link=session_link,
        ),
    )
    run = wait_for_run(run_id, poll_interval_seconds=10)
    session_link = get_session_link(run) or session_link
    pr_urls = get_pull_request_urls(run)
    if not pr_urls:
        pulls = list_pulls_by_head(repo, repo_ref.owner, branch_name, state="all")
        pr_urls = [pull.html_url for pull in pulls]

    if run.state == "SUCCEEDED" and pr_urls:
        upsert_comment(
            issue,
            WORKFLOW_NAME,
            _build_status_lines(
                f"I created or updated a plan pull request for this issue: {pr_urls[0]}",
                session_link=session_link,
            ),
        )
        return 0

    if run.state == "SUCCEEDED":
        upsert_comment(
            issue,
            WORKFLOW_NAME,
            _build_status_lines(
                "I completed the run, but no plan pull request was detected.",
                session_link=session_link,
            ),
        )
        return 0

    error_message = getattr(getattr(run, "status_message", None), "message", None) or "The plan run did not complete successfully."
    upsert_comment(
        issue,
        WORKFLOW_NAME,
        _build_status_lines(
            f"I started working on a plan for this issue, but the run ended unsuccessfully: {error_message}",
            session_link=session_link,
        ),
    )
    raise RuntimeError(error_message)
