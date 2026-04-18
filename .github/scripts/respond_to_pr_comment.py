from __future__ import annotations
from contextlib import closing

from datetime import timedelta
from textwrap import dedent
from github import Auth, Github
from github.PullRequest import PullRequest
from github.Repository import Repository

from oz_workflows.artifacts import try_load_resolved_review_comments_artifact
from oz_workflows.env import load_event, optional_env, repo_parts, repo_slug, require_env, workspace
from oz_workflows.helpers import (
    all_review_comments_text,
    branch_updated_since,
    build_next_steps_section,
    coauthor_prompt_lines,
    format_pr_comment_start_line,
    is_automation_user,
    org_member_comments_text,
    post_resolved_review_comment_replies,
    record_run_session_link,
    resolve_coauthor_line,
    resolve_spec_context_for_pr,
    review_thread_comments_text,
    WorkflowProgressComment,
)
from oz_workflows.oz_client import build_agent_config, run_agent


def main() -> None:
    owner, repo = repo_parts()
    event = load_event()
    if is_automation_user((event.get("comment") or {}).get("user")):
        return
    github_event_name = optional_env("GITHUB_EVENT_NAME")
    with closing(Github(auth=Auth.Token(require_env("GH_TOKEN")))) as client:
        github = client.get_repo(repo_slug())
        if github_event_name == "pull_request_review_comment":
            _handle_review_comment(client, github, owner, repo, event)
        elif github_event_name == "issue_comment":
            _handle_issue_comment(client, github, owner, repo, event)
        else:
            raise RuntimeError(f"Unsupported event: {github_event_name}")


def _handle_review_comment(
    client: Github,
    github: Repository,
    owner: str,
    repo: str,
    event: dict,
) -> None:
    comment = event["comment"]
    trigger_comment_id = int(comment["id"])
    pr_number = int(event["pull_request"]["number"])
    pr = github.get_pull(pr_number)
    pr.get_review_comment(trigger_comment_id).create_reaction("eyes")
    all_review = list(pr.get_review_comments())
    thread_context = review_thread_comments_text(all_review, trigger_comment_id)

    triggering_body = comment.get("body") or ""
    requester = (comment.get("user") or {}).get("login") or ""

    _run_implementation(
        client,
        github,
        owner,
        repo,
        pr,
        event=event,
        triggering_body=triggering_body,
        additional_context=thread_context,
        context_label="Review thread context (org members only)",
        requester=requester,
        review_reply_target=(pr, trigger_comment_id),
    )


def _handle_issue_comment(
    client: Github,
    github: Repository,
    owner: str,
    repo: str,
    event: dict,
) -> None:
    comment = event["comment"]
    trigger_comment_id = int(comment["id"])
    pr_number = int(event["issue"]["number"])
    pr = github.get_pull(pr_number)
    pr.get_issue_comment(trigger_comment_id).create_reaction("eyes")
    issue_comments = list(pr.get_issue_comments())
    issue_comments_context = org_member_comments_text(
        issue_comments,
        exclude_comment_id=trigger_comment_id,
    )
    review_comments = list(pr.get_review_comments())
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
        client,
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
    client: Github,
    github: Repository,
    owner: str,
    repo: str,
    pr: PullRequest,
    *,
    event: dict,
    triggering_body: str,
    additional_context: str,
    context_label: str,
    requester: str,
    review_reply_target: tuple[PullRequest, int] | None = None,
) -> None:
    pr_number = pr.number
    head_branch = pr.head.ref
    base_branch = pr.base.ref
    pr_title = pr.title or ""
    pr_body = pr.body or ""

    coauthor_line = resolve_coauthor_line(client, event)
    coauthor_directives = coauthor_prompt_lines(coauthor_line)

    spec_context = resolve_spec_context_for_pr(
        github,
        owner,
        repo,
        pr,
        workspace=workspace(),
    )
    has_spec_context = bool(spec_context.get("spec_entries"))
    progress = WorkflowProgressComment(
        github,
        owner,
        repo,
        pr_number,
        workflow="respond-to-pr-comment",
        event_payload=event,
        requester_login=requester,
        review_reply_target=review_reply_target,
    )
    progress.start(
        format_pr_comment_start_line(
            is_review_reply=review_reply_target is not None,
            has_spec_context=has_spec_context,
        )
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

        Resolved Review Comment Reporting:
        - If any of your changes addresses one or more existing PR review comments (inline comments on the code in this PR, as surfaced in the review context above), record them so the workflow can close the loop on those review threads.
        - Only include review comments whose underlying concern is actually resolved by the change you produced in this run. Do not guess or speculate.
        - Limit reported comment ids to numeric GitHub review comment ids drawn from the review context above. Do not invent ids and do not include issue-comment ids.
        - Write the report to `resolved_review_comments.json` at the repository root with exactly this shape:
          {{
            "resolved_review_comments": [
              {{"comment_id": <int: GitHub review comment id>, "summary": "<markdown summary of how the comment was addressed, referencing files/changes>"}}
            ]
          }}
        - Each `summary` must be a short, reviewer-facing explanation (1-3 sentences) describing what changed.
        - Validate the JSON with `jq` after writing it.
        - Upload it as an artifact via `oz-dev artifact upload resolved_review_comments.json`. The subcommand is `artifact` (singular); do not use `artifacts`.
        - Do not upload the artifact when no review comments were resolved. Omitting the file is the correct signal that no review threads need to be closed.
        {coauthor_directives}
        """
    ).strip()

    config = build_agent_config(
        config_name="respond-to-pr-comment",
        workspace=workspace(),
    )

    try:
        run = run_agent(
            prompt=prompt,
            skill_name="implement-issue",
            title=f"Respond to PR comment #{pr_number}",
            config=config,
            on_poll=lambda current_run: record_run_session_link(progress, current_run),
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

        # Only honor the resolved-review-comments payload when the branch
        # was actually updated. Without a code change there is nothing to
        # tie the "resolved" claim back to, so skip replies/thread
        # resolution rather than noisily closing threads for a no-op run.
        resolved_review_comments = try_load_resolved_review_comments_artifact(run.run_id)
        if resolved_review_comments:
            post_resolved_review_comment_replies(
                client,
                owner,
                repo,
                pr,
                resolved_review_comments,
            )

        completion_sections = [
            "I pushed changes to this PR based on the comment.",
        ]
        if resolved_review_comments:
            count = len(resolved_review_comments)
            noun = "review comment" if count == 1 else "review comments"
            completion_sections.append(
                f"Replied to and attempted to resolve {count} {noun} that this run addressed."
            )
        completion_sections.append(next_steps_section)
        progress.complete("\n\n".join(completion_sections))
    except Exception:
        progress.report_error()
        raise

if __name__ == "__main__":
    main()
