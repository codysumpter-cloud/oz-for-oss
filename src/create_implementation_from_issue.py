from __future__ import annotations

from datetime import timedelta
from textwrap import dedent

from oz_workflows.actions import append_summary
from oz_workflows.env import load_event, repo_parts, repo_slug, workspace, require_env
from oz_workflows.github_api import GitHubClient
from oz_workflows.helpers import (
    branch_updated_since,
    build_next_steps_section,
    conventional_commit_prefix,
    org_member_comments_text,
    resolve_plan_context_for_issue,
    triggering_comment_prompt_text,
    WorkflowProgressComment,
)
from oz_workflows.oz_client import build_agent_config, run_agent


def main() -> None:
    owner, repo = repo_parts()
    event = load_event()
    issue = event["issue"]
    issue_number = int(issue["number"])
    issue_title = issue["title"]
    default_branch = event["repository"]["default_branch"]
    triggering_comment_id = int((event.get("comment") or {}).get("id") or 0) or None

    with GitHubClient(require_env("GH_TOKEN"), repo_slug()) as github:
        github.add_assignees(owner, repo, issue_number, ["oz-agent"])
        comments = github.list_issue_comments(owner, repo, issue_number)
        comments_text = org_member_comments_text(comments, exclude_comment_id=triggering_comment_id)
        triggering_comment_text = triggering_comment_prompt_text(event)
        plan_context = resolve_plan_context_for_issue(
            github,
            owner,
            repo,
            issue_number,
            workspace=workspace(),
        )
        selected_plan_pr = plan_context["selected_plan_pr"]
        target_branch = (
            selected_plan_pr["head_ref_name"]
            if selected_plan_pr
            else f"oz-agent/implement-issue-{issue_number}"
        )
        progress = WorkflowProgressComment(
            github,
            owner,
            repo,
            issue_number,
            workflow="create-implementation-from-issue",
            event_payload=event,
        )
        progress.start("Oz is working on an implementation for this issue.")
        should_noop = (
            not selected_plan_pr
            and not plan_context["plan_entries"]
            and len(plan_context["unapproved_plan_prs"]) > 0
        )
        if should_noop:
            progress.complete(
                "I did not start implementation because linked plan PR(s) exist for this issue but none are labeled `plan-approved`: "
                + ", ".join(f"#{pr['number']}" for pr in plan_context["unapproved_plan_prs"])
            )
            append_summary(
                "Linked plan PR(s) exist for this issue but none are labeled `plan-approved`: "
                + ", ".join(f"#{pr['number']}" for pr in plan_context["unapproved_plan_prs"])
            )
            return
        next_steps_section = build_next_steps_section(
            [
                "Review the implementation changes in the PR.",
                "Complete any manual verification needed for this issue before merging.",
            ]
        )

        plan_sections = []
        if plan_context["plan_context_source"] == "approved-pr" and selected_plan_pr:
            plan_sections.append(
                f"Linked approved plan PR: #{selected_plan_pr['number']} ({selected_plan_pr['url']})"
            )
        elif plan_context["plan_context_source"] == "directory":
            plan_sections.append("Repository plan file(s) associated with this issue were found in `plans/`.")
        for entry in plan_context["plan_entries"]:
            plan_sections.append(f"## {entry['path']}\n\n{entry['content']}")
        plan_context_text = "\n\n".join(plan_sections).strip() or "No approved or repository plan context was found."

        prompt = dedent(
            f"""
            Create an implementation update for GitHub issue #{issue_number} in repository {owner}/{repo}.

            Issue Details:
            - Title: {issue_title}
            - Labels: {", ".join(label["name"] for label in issue.get("labels", [])) or "None"}
            - Assignees: {", ".join(assignee["login"] for assignee in issue.get("assignees", [])) or "None"}
            - Description: {issue.get("body") or "No description provided."}

            Previous Issue Comments From Organization Members:
            {comments_text or "- None"}

            Explicit Triggering Comment:
            {triggering_comment_text or "- None"}

            Plan Context:
            {plan_context_text}

            Cloud Workflow Requirements:
            - Use the repository's local `implement-issue` skill as the base workflow.
            - You are running in a cloud environment, so the caller cannot read your local diff.
            - Work on branch `{target_branch}`.
            - If that branch already exists, fetch it and continue from it. Otherwise create it from `{default_branch}`.
            - Align the implementation with the plan context above when present.
            - Run the most relevant validation available in the repository.
            - If you produce changes, commit them to `{target_branch}` and push that branch to origin.
            - Do not open or update the pull request yourself.
            - If no implementation diff is warranted, do not push the branch.
            """
        ).strip()

        config = build_agent_config(
            config_name="create-implementation-from-issue",
            workspace=workspace(),
            environment_env_names=[
                "WARP_AGENT_IMPLEMENTATION_ENVIRONMENT_ID",
                "WARP_AGENT_ENVIRONMENT_ID",
            ],
        )

        run = run_agent(
            prompt=prompt,
            skill_name="implement-issue",
            title=f"Implement issue #{issue_number}",
            config=config,
            on_poll=lambda current_run: _on_poll(progress, current_run),
        )

        if not branch_updated_since(
            github,
            owner,
            repo,
            target_branch,
            created_after=run.created_at - timedelta(minutes=1),
        ):
            progress.complete("I analyzed this issue but did not produce an implementation diff.")
            return

        commit_type = conventional_commit_prefix(issue.get("labels", []))

        if selected_plan_pr:
            github.update_pull(
                owner,
                repo,
                int(selected_plan_pr["number"]),
                title=f"{commit_type}: {issue_title}",
            )
            progress.complete(
                f"I pushed implementation updates to the linked approved plan PR: {selected_plan_pr['url']}\n\n"
                f"{next_steps_section}"
            )
            return

        existing_prs = github.list_pulls(owner, repo, state="open", head=f"{owner}:{target_branch}")
        pr_body = (
            f"Automated implementation update for issue #{issue_number}."
            + (f"\n\nSession: {run.session_link}" if run.session_link else "")
        )
        if existing_prs:
            pr = existing_prs[0]
        else:
            pr = github.create_pull(
                owner,
                repo,
                title=f"{commit_type}: {issue_title}",
                head=target_branch,
                base=default_branch,
                body=pr_body,
                draft=True,
            )
        progress.complete(
            f"I created or updated a draft implementation PR for this issue: {pr['html_url']}\n\n"
            f"{next_steps_section}"
        )


def _on_poll(progress: WorkflowProgressComment, run: object) -> None:
    session_link = getattr(run, "session_link", None) or ""
    progress.record_session_link(session_link)


if __name__ == "__main__":
    main()
