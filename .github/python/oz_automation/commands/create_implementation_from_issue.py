from __future__ import annotations

from typing import Iterable

from oz_automation.context import get_repo_ref, load_event
from oz_automation.github_client import (
    get_file_text,
    get_repository,
    issue_author_login,
    labels_to_names,
    list_comments,
    list_pulls_by_head,
    upsert_comment,
)
from oz_automation.outputs import append_summary
from oz_automation.oz_client import (
    get_pull_request_urls,
    get_session_link,
    start_run,
    wait_for_run,
    wait_for_session_link,
)


WORKFLOW_NAME = "create-implementation-from-issue"
SKILL_PATH = ".agents/skills/implement-issue/SKILL.md"


def _member_comments_text(comments: Iterable) -> str:
    filtered = [
        f"- {comment.user.login if comment.user else 'unknown'} ({comment.created_at.isoformat()}): {comment.body or ''}"
        for comment in comments
        if getattr(comment, "author_association", "") in {"MEMBER", "OWNER"}
    ]
    return "\n".join(filtered) if filtered else "None."


def _plan_pr_context(repo, repo_ref, issue_number: int) -> tuple[dict | None, list[dict]]:
    expected_branch = f"oz-agent/plan-issue-{issue_number}"
    matching_pulls = list_pulls_by_head(repo, repo_ref.owner, expected_branch, state="all")
    approved: list[dict] = []
    unapproved: list[dict] = []
    for pr in matching_pulls:
        labels = labels_to_names(pr.labels)
        files = [file.filename for file in pr.get_files()]
        record = {
            "number": pr.number,
            "url": pr.html_url,
            "head_ref": pr.head.ref,
            "updated_at": pr.updated_at,
            "labels": labels,
            "plan_files": [path for path in files if path.startswith("plans/")],
        }
        if "plan-approved" in labels:
            approved.append(record)
        else:
            unapproved.append(record)
    approved.sort(key=lambda item: item["updated_at"], reverse=True)
    return (approved[0] if approved else None, unapproved)


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

    selected_plan_pr, unapproved_plan_prs = _plan_pr_context(repo, repo_ref, issue.number)
    directory_plan_path = f"plans/issue-{issue.number}.md"
    directory_plan_text = get_file_text(repo, directory_plan_path, ref=default_branch)
    should_noop = selected_plan_pr is None and directory_plan_text is None and len(unapproved_plan_prs) > 0

    if should_noop:
        append_summary(
            "Linked plan PRs exist for this issue but none are labeled `plan-approved`: "
            + ", ".join(f"#{pr['number']}" for pr in unapproved_plan_prs)
        )
        return 0

    upsert_comment(
        issue,
        WORKFLOW_NAME,
        ["Oz is working on an implementation for this issue."],
        legacy_bodies=["Oz is working on an implementation for this issue."],
    )

    plan_context = "No linked approved plan PR or repository plan file was found."
    target_branch = f"oz-agent/implement-issue-{issue.number}"
    pr_title = f"Implement issue #{issue.number}: {issue.title}"
    if selected_plan_pr:
        target_branch = selected_plan_pr["head_ref"]
        pr_title = f"Implement issue #{issue.number}: {issue.title}"
        plan_sections: list[str] = [f"Approved plan PR: {selected_plan_pr['url']}"]
        for path in selected_plan_pr["plan_files"]:
            plan_text = get_file_text(repo, path, ref=selected_plan_pr["head_ref"])
            if plan_text:
                plan_sections.append(f"## {path}\n{plan_text.strip()}")
        plan_context = "\n\n".join(plan_sections)
    elif directory_plan_text:
        plan_context = f"## {directory_plan_path}\n{directory_plan_text.strip()}"

    labels = ", ".join(labels_to_names(issue.labels)) or "None"
    assignees = ", ".join(assignee.login for assignee in issue.assignees) or "None"
    skill_spec = f"{repo_ref.full_name}:{SKILL_PATH}"
    prompt = f"""Implement and publish GitHub Issue #{issue.number} in {repo_ref.full_name}.

Issue details:
- Title: {issue.title}
- Author: @{issue_author_login(issue)}
- Labels: {labels}
- Assignees: {assignees}
- Default branch: {default_branch}
- Required target branch: {target_branch}
- Required pull request title: {pr_title}

Issue description:
{issue.body or "No description provided."}

Organization-member comments:
{comments_text}

Plan context:
{plan_context}

Publishing requirements:
- Use the repository skill `{skill_spec}`.
- Keep the implementation scoped to this issue.
- Publish directly to `{target_branch}`.
- Create or update the pull request titled `{pr_title}`.
- If `{target_branch}` already belongs to an approved plan PR, continue work on that existing pull request instead of opening a new one.
- Use the pull request body to summarize the implementation, validation performed, and any follow-up notes.
- Do not commit temporary scratch files or unrelated changes.
"""

    run_id = start_run(
        prompt=prompt,
        title=f"Implement issue #{issue.number}",
        skill=skill_spec,
        config_name=f"implement-issue-{issue.number}",
    )
    session_link = wait_for_session_link(run_id)
    upsert_comment(
        issue,
        WORKFLOW_NAME,
        _build_status_lines(
            "Oz is working on an implementation for this issue.",
            session_link=session_link,
        ),
        legacy_bodies=["Oz is working on an implementation for this issue."],
    )
    run = wait_for_run(run_id, poll_interval_seconds=10)
    session_link = get_session_link(run) or session_link

    pr_urls = get_pull_request_urls(run)
    if not pr_urls:
        pulls = list_pulls_by_head(repo, repo_ref.owner, target_branch, state="all")
        pr_urls = [pull.html_url for pull in pulls]

    if run.state == "SUCCEEDED" and pr_urls:
        upsert_comment(
            issue,
            WORKFLOW_NAME,
            _build_status_lines(
                f"I created or updated an implementation pull request for this issue: {pr_urls[0]}",
                session_link=session_link,
            ),
            legacy_bodies=["Oz is working on an implementation for this issue."],
        )
        return 0

    if run.state == "SUCCEEDED":
        upsert_comment(
            issue,
            WORKFLOW_NAME,
            _build_status_lines(
                "I completed the implementation run, but no pull request was detected.",
                session_link=session_link,
            ),
            legacy_bodies=["Oz is working on an implementation for this issue."],
        )
        return 0

    error_message = getattr(getattr(run, "status_message", None), "message", None) or "The implementation run did not complete successfully."
    upsert_comment(
        issue,
        WORKFLOW_NAME,
        _build_status_lines(
            f"I started working on an implementation for this issue, but the run ended unsuccessfully: {error_message}",
            session_link=session_link,
        ),
        legacy_bodies=["Oz is working on an implementation for this issue."],
    )
    raise RuntimeError(error_message)
