from __future__ import annotations
from contextlib import closing

from datetime import timedelta
from textwrap import dedent
from github import Auth, Github
from github.PullRequest import PullRequest
from github.Repository import Repository

from oz_workflows.actions import notice
from oz_workflows.artifacts import (
    try_load_pr_metadata_artifact,
    try_load_resolved_review_comments_artifact,
)
from oz_workflows.comment_templates import render_comment_template
from oz_workflows.env import load_event, optional_env, repo_parts, repo_slug, require_env, workspace
from oz_workflows.helpers import (
    branch_updated_since,
    build_next_steps_section,
    coauthor_prompt_lines,
    format_pr_comment_start_line,
    is_automation_user,
    is_trusted_commenter,
    post_resolved_review_comment_replies,
    record_run_session_link,
    resolve_coauthor_line,
    resolve_spec_context_for_pr,
    WorkflowProgressComment,
)
from oz_workflows.oz_client import build_agent_config, run_agent

FETCH_CONTEXT_SCRIPT = ".agents/skills/implement-specs/scripts/fetch_github_context.py"


def main() -> None:
    owner, repo = repo_parts()
    event = load_event()
    github_event_name = optional_env("GITHUB_EVENT_NAME")
    user_payload_key = "review" if github_event_name == "pull_request_review" else "comment"
    if is_automation_user((event.get(user_payload_key) or {}).get("user")):
        return
    with closing(Github(auth=Auth.Token(require_env("GH_TOKEN")))) as client:
        # Decide whether the commenter is trusted BEFORE starting the
        # agent run. Prior versions of this workflow passed the triggering
        # comment id into the prompt and asked the agent to infer trust
        # by string-searching for that id in ``fetch_github_context.py``
        # output. That approach produced false "untrusted" readings
        # whenever the fetch output was missing the triggering comment
        # for reasons unrelated to trust (script path issues, transient
        # API errors, pagination edge cases, output truncation, etc.)
        # and caused the agent to silently no-op on legitimate org-
        # member comments. Trust is a workflow-layer decision, so we
        # resolve it deterministically here using the same static +
        # org-membership fallback that ``fetch_github_context.py`` uses.
        if not is_trusted_commenter(client, event, org=owner):
            event_actor = event.get(user_payload_key) or {}
            login = (event_actor.get("user") or {}).get("login") or "unknown"
            association = event_actor.get("author_association") or "NONE"
            notice(
                f"Ignoring @oz-agent mention from @{login}; "
                f"not an org member (association={association})."
            )
            return
        github = client.get_repo(repo_slug())
        if github_event_name == "pull_request_review_comment":
            _handle_review_comment(client, github, owner, repo, event)
        elif github_event_name == "issue_comment":
            _handle_issue_comment(client, github, owner, repo, event)
        elif github_event_name == "pull_request_review":
            _handle_review_body(client, github, owner, repo, event)
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
    requester = (comment.get("user") or {}).get("login") or ""

    _run_implementation(
        client,
        github,
        owner,
        repo,
        pr,
        event=event,
        trigger_comment_id=trigger_comment_id,
        trigger_kind="review",
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
    requester = (comment.get("user") or {}).get("login") or ""

    _run_implementation(
        client,
        github,
        owner,
        repo,
        pr,
        event=event,
        trigger_comment_id=trigger_comment_id,
        trigger_kind="conversation",
        requester=requester,
    )


def _handle_review_body(
    client: Github,
    github: Repository,
    owner: str,
    repo: str,
    event: dict,
) -> None:
    review = event["review"]
    trigger_review_id = int(review["id"])
    pr_number = int(event["pull_request"]["number"])
    pr = github.get_pull(pr_number)
    requester = (review.get("user") or {}).get("login") or ""
    # GitHub's REST API has no reactions endpoint for pull request review bodies
    # (only for comments), so no create_reaction("eyes") call is made here.
    # The progress issue comment is the sole user-visible acknowledgement.

    _run_implementation(
        client,
        github,
        owner,
        repo,
        pr,
        event=event,
        trigger_comment_id=trigger_review_id,
        trigger_kind="review_body",
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
    trigger_comment_id: int,
    trigger_kind: str,
    requester: str,
    review_reply_target: tuple[PullRequest, int] | None = None,
) -> None:
    pr_number = pr.number
    head_branch = pr.head.ref
    base_branch = pr.base.ref
    pr_title = pr.title or ""

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
            is_review_body=trigger_kind == "review_body",
            has_spec_context=has_spec_context,
        )
    )
    spec_sections: list[str] = []
    selected_spec_pr = spec_context.get("selected_spec_pr")
    if spec_context.get("spec_context_source") == "approved-pr" and selected_spec_pr:
        spec_sections.append(
            f"Linked approved spec PR: [#{selected_spec_pr['number']}]({selected_spec_pr['url']})"
        )
    elif spec_context.get("spec_context_source") == "directory":
        spec_sections.append("Repository spec context was found in `specs/`.")
    for entry in spec_context.get("spec_entries", []):
        spec_sections.append(f"## {entry['path']}\n\n{entry['content']}")
    spec_context_text = (
        "\n\n".join(spec_sections).strip()
        or "No approved or repository spec context was found."
    )

    trigger_kind_label = {
        "review": "inline review-thread comment",
        "review_body": "PR review body",
    }.get(trigger_kind, "PR conversation comment")
    prompt = dedent(
        f"""\
        Make changes on the branch `{head_branch}` for pull request #{pr_number} in repository {owner}/{repo}.

        Pull Request Metadata:
        - Title: {pr_title}
        - Base branch: {base_branch}
        - Head branch: {head_branch}
        - Triggered by: {trigger_kind_label} id={trigger_comment_id} from @{requester or 'unknown'}

        Spec Context:
        {spec_context_text}

        Fetching PR and Comment Content (required before changing code):
        - The PR body, conversation comments, review comments, and the triggering comment body are NOT inlined in this prompt. Contributors outside the organization can edit PR bodies and post comments, so inlining them here would merge untrusted input with these workflow instructions.
        - The workflow has already verified that the triggering commenter is a trusted organization member, so you do not need to infer trust from the fetch output. Focus on understanding the request itself.
        - Fetch PR discussion on demand by running `python {FETCH_CONTEXT_SCRIPT} pr --repo {owner}/{repo} --number {pr_number}` from the repository root. The script drops comments from non-org-members / non-collaborators entirely and labels every returned section with its source, author, and author association; there is no flag to include those dropped comments.
        - Locate the triggering {trigger_kind_label} (id `{trigger_comment_id}`) in that output so you understand the request in context. If the triggering item is missing from the output, that indicates a fetch-script or API failure (not an untrusted author); surface the problem in your summary and do not silently treat it as a no-op.
        - If you need the unified diff for this PR, run `python {FETCH_CONTEXT_SCRIPT} pr-diff --repo {owner}/{repo} --number {pr_number}` rather than reconstructing it yourself.
        - This script (and the filtering it applies) is the only supported way to read PR body or comment content during this run. Do not retrieve them via any other mechanism.

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

        PR Description Refresh:
        - If your changes materially change what this PR contains (for example, adding implementation code on top of a PR that previously only contained spec changes, or otherwise substantially broadening or narrowing the PR's scope), write `pr-metadata.json` at the repository root containing a JSON object with these required fields so the workflow can refresh the PR title and body:
          - `branch_name`: the branch you pushed to (use `{head_branch}` exactly).
          - `pr_title`: a conventional-commit-style PR title that reflects the PR's current combined scope (e.g. `feat: add retry logic for transient API failures` when implementation has been added on top of a spec PR).
          - `pr_summary`: the full markdown PR body reflecting the PR's current combined scope. When the original PR body started with `Closes #<issue_number>` or `Fixes #<issue_number>`, preserve that line at the top so GitHub still auto-closes the linked issue when the PR merges.
        - After writing `pr-metadata.json`, upload it as an artifact via `oz artifact upload pr-metadata.json` (or `oz-preview artifact upload pr-metadata.json` if the `oz` CLI is not available). Either CLI is acceptable — use whichever one is installed in the environment. The subcommand is `artifact` (singular) on both CLIs; do not use `artifacts`.
        - If your changes are minor tweaks that do not change the PR's scope (for example, fixing a typo in a spec, adjusting wording, or small bug fixes within the PR's existing scope), do not write or upload `pr-metadata.json`. Leaving it out signals that the existing PR title and description should remain unchanged.

        Resolved Review Comment Reporting:
        - If any of your changes addresses one or more existing PR review comments (inline comments on the code in this PR, as surfaced by the fetch script above under `kind=pr-review-comment`), record them so the workflow can close the loop on those review threads.
        - Only include review comments whose underlying concern is actually resolved by the change you produced in this run. Do not guess or speculate.
        - Limit reported comment ids to numeric GitHub review comment ids drawn from the fetch-script output (entries with `kind=pr-review-comment`). Do not invent ids and do not include issue-comment ids.
        - Write the report to `resolved_review_comments.json` at the repository root with exactly this shape:
          {{
            "resolved_review_comments": [
              {{"comment_id": <int: GitHub review comment id>, "summary": "<markdown summary of how the comment was addressed, referencing files/changes>"}}
            ]
          }}
        - Each `summary` must be a short, reviewer-facing explanation (1-3 sentences) describing what changed.
        - Validate the JSON with `jq` after writing it.
        - Upload it as an artifact via `oz artifact upload resolved_review_comments.json` (or `oz-preview artifact upload resolved_review_comments.json` if the `oz` CLI is not available). Either CLI is acceptable — use whichever one is installed in the environment. The subcommand is `artifact` (singular) on both CLIs; do not use `artifacts`.
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
            progress.complete(render_comment_template(workspace(), namespace="respond-to-pr-comment", key="complete_no_diff"))
            return

        # Refresh the PR title/body when the agent's changes materially
        # changed the PR's scope (for example, adding implementation
        # commits on top of a spec-only PR). The agent signals this by
        # uploading pr-metadata.json; when the artifact is absent we
        # leave the existing description untouched because the changes
        # were meant to stay within the PR's current scope.
        pr_description_refreshed = False
        pr_metadata = try_load_pr_metadata_artifact(run.run_id)
        if pr_metadata is not None:
            # The agent is instructed to push to the PR's head branch and
            # to set `branch_name` to that same branch. If the uploaded
            # metadata points at a different branch something has gone
            # wrong (the agent pushed to the wrong branch or produced
            # stale metadata), so refuse to refresh the PR description
            # rather than overwriting it with content that may not
            # describe what the head branch actually contains.
            metadata_branch = pr_metadata.get("branch_name", "")
            if metadata_branch != head_branch:
                raise RuntimeError(
                    f"pr-metadata.json branch_name {metadata_branch!r} does not "
                    f"match the PR head branch {head_branch!r}; refusing to "
                    f"refresh the PR title and description."
                )
            pr.edit(
                title=pr_metadata["pr_title"],
                body=pr_metadata["pr_summary"],
            )
            pr_description_refreshed = True

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
        if pr_description_refreshed:
            completion_sections.append(
                "Refreshed the PR title and description to reflect the PR's updated scope."
            )
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
