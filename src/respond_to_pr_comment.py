from __future__ import annotations

from datetime import timedelta
from textwrap import dedent

from oz_workflows.env import load_event, optional_env, repo_parts, repo_slug, require_env, workspace
from oz_workflows.github_api import GitHubClient
from oz_workflows.helpers import (
    all_review_comments_text,
    branch_updated_since,
    build_next_steps_section,
    coauthor_prompt_lines,
    org_member_comments_text,
    resolve_coauthor_line,
    resolve_spec_context_for_pr,
    review_thread_comments_text,
    WorkflowProgressComment,
)
from oz_workflows.oz_client import build_agent_config, run_agent


def main() -> None:
    owner, repo = repo_parts()
    event = load_event()
    github_event_name = optional_env("GITHUB_EVENT_NAME")

    with GitHubClient(require_env("GH_TOKEN"), repo_slug()) as github:
        if github_event_name == "pull_request_review_comment":
            _handle_review_comment(github, owner, repo, event)
        elif github_event_name == "issue_comment":
            _handle_issue_comment(github, owner, repo, event)
        else:
            raise RuntimeError(f"Unsupported event: {github_event_name}")


def _handle_review_comment(
    github: GitHubClient,
    owner: str,
    repo: str,
    event: dict,
) -> None:
    comment = event["comment"]
    trigger_comment_id = int(comment["id"])
    pr_number = int(event["pull_request"]["number"])
    pr = github.get_pull(owner, repo, pr_number)

    # Acknowledge the comment.
    github.create_reaction_for_pull_request_review_comment(
        owner, repo, trigger_comment_id, "eyes",
    )

    # Gather thread-scoped context.
    all_review = github.list_pull_review_comments(owner, repo, pr_number)
    thread_context = review_thread_comments_text(all_review, trigger_comment_id)

    triggering_body = comment.get("body") or ""
    requester = (comment.get("user") or {}).get("login") or ""

    _run_implementation(
        github,
        owner,
        repo,
        pr,
        event=event,
        triggering_body=triggering_body,
        additional_context=thread_context,
        context_label="Review thread context (org members only)",
        requester=requester,
    )


def _handle_issue_comment(
    github: GitHubClient,
    owner: str,
    repo: str,
    event: dict,
) -> None:
    comment = event["comment"]
    trigger_comment_id = int(comment["id"])
    pr_number = int(event["issue"]["number"])
    pr = github.get_pull(owner, repo, pr_number)

    # Acknowledge the comment.
    github.create_reaction_for_issue_comment(
        owner, repo, trigger_comment_id, "eyes",
    )

    # Gather context from all issue comments and all review comments.
    issue_comments = github.list_issue_comments(owner, repo, pr_number)
    issue_comments_context = org_member_comments_text(
        issue_comments, exclude_comment_id=trigger_comment_id,
    )
    review_comments = github.list_pull_review_comments(owner, repo, pr_number)
    review_context = all_review_comments_text(review_comments)

    context_parts: list[str] = []
    if issue_comments_context:
        context_parts.append(f"Issue comments (org members only):\n{issue_comments_context}")
    if review_context:
        context_parts.append(f"Review comments (org members only):\n{review_context}")
    additional_context = "\n\n".join(context_parts)

    triggering_body = comment.get("body") or ""
    requester = (comment.get("user") or {}).get("login") or ""

    _run_implementation(
        github,
        owner,
        repo,
        pr,
        event=event,
        triggering_body=triggering_body,
        additional_context=additional_context,
        context_label="All PR discussion context (org members only)",
        requester=requester,
    )


def _run_implementation(
    github: GitHubClient,
    owner: str,
    repo: str,
    pr: dict,
    *,
    event: dict,
    triggering_body: str,
    additional_context: str,
    context_label: str,
    requester: str,
) -> None:
    pr_number = int(pr["number"])
    head_branch = pr["head"]["ref"]
    base_branch = pr["base"]["ref"]
    pr_title = pr.get("title") or ""
    pr_body = pr.get("body") or ""

    coauthor_line = resolve_coauthor_line(github, event)
    coauthor_directives = coauthor_prompt_lines(coauthor_line)

    progress = WorkflowProgressComment(
        github,
        owner,
        repo,
        pr_number,
        workflow="respond-to-pr-comment",
        event_payload=event,
        requester_login=requester,
    )
    progress.start("Oz is working on changes requested in this PR.")

    spec_context = resolve_spec_context_for_pr(
        github,
        owner,
        repo,
        pr,
        workspace=workspace(),
    )
    spec_sections: list[str] = []
    selected_spec_pr = spec_context.get("selected_spec_pr")
    if spec_context.get("spec_context_source") == "approved-pr" and selected_spec_pr:
        spec_sections.append(
            f"Linked approved spec PR: #{selected_spec_pr['number']} ({selected_spec_pr['url']})"
        )
    elif spec_context.get("spec_context_source") == "directory":
        spec_sections.append("Repository spec context was found in `specs/`.")
    for entry in spec_context.get("spec_entries", []):
        spec_sections.append(f"## {entry['path']}\n\n{entry['content']}")
    spec_context_text = (
        "\n\n".join(spec_sections).strip()
        or "No approved or repository spec context was found."
    )

    prompt = dedent(
        f"""\
        Make changes on the branch `{head_branch}` for pull request #{pr_number} in repository {owner}/{repo}.

        Pull Request Context:
        - Title: {pr_title}
        - Body: {pr_body or 'No description provided.'}
        - Base branch: {base_branch}
        - Head branch: {head_branch}

        Triggering comment from @{requester}:
        {triggering_body}

        {context_label}:
        {additional_context or '- None'}

        Spec Context:
        {spec_context_text}

        Cloud Workflow Requirements:
        - Use the repository's local `implement-issue` skill as the base workflow.
        - You are running in a cloud environment, so the caller cannot read your local diff.
        - Work on branch `{head_branch}`.
        - Fetch the existing branch and continue from it.
        - Align any implementation changes with the plan context above when present.
        - Run the most relevant validation available in the repository.
        - If you produce changes, commit them to `{head_branch}` and push that branch to origin.
        - Do not open or update the pull request yourself.
        - If no implementation diff is warranted, do not push the branch.
        {coauthor_directives}
        """
    ).strip()

    config = build_agent_config(
        config_name="respond-to-pr-comment",
        workspace=workspace(),
    )

    run = run_agent(
        prompt=prompt,
        skill_name="implement-issue",
        title=f"Respond to PR comment #{pr_number}",
        config=config,
        on_poll=lambda current_run: _on_poll(progress, current_run),
    )

    next_steps_section = build_next_steps_section(
        [
            "Review the changes pushed to this PR.",
            "Follow up with another comment if further adjustments are needed.",
        ]
    )

    if not branch_updated_since(
        github,
        owner,
        repo,
        head_branch,
        created_after=run.created_at - timedelta(minutes=1),
    ):
        progress.complete("I analyzed the request but did not produce any changes.")
        return

    progress.complete(
        f"I pushed changes to this PR based on the comment.\n\n{next_steps_section}"
    )


def _on_poll(progress: WorkflowProgressComment, run: object) -> None:
    session_link = getattr(run, "session_link", None) or ""
    progress.record_session_link(session_link)


if __name__ == "__main__":
    main()
