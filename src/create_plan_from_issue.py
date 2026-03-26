from __future__ import annotations

from datetime import timedelta
from textwrap import dedent

from oz_workflows.env import load_event, repo_parts, repo_slug, workspace, require_env
from oz_workflows.github_api import GitHubClient
from oz_workflows.helpers import (
    branch_updated_since,
    build_next_steps_section,
    build_plan_preview_section,
    build_pr_body,
    org_member_comments_text,
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
    branch_name = f"oz-agent/plan-issue-{issue_number}"
    triggering_comment_id = int((event.get("comment") or {}).get("id") or 0) or None

    with GitHubClient(require_env("GH_TOKEN"), repo_slug()) as github:
        github.add_assignees(owner, repo, issue_number, ["oz-agent"])
        comments = github.list_issue_comments(owner, repo, issue_number)
        comments_text = org_member_comments_text(comments, exclude_comment_id=triggering_comment_id)
        triggering_comment_text = triggering_comment_prompt_text(event)
        progress = WorkflowProgressComment(
            github,
            owner,
            repo,
            issue_number,
            workflow="create-plan-from-issue",
            event_payload=event,
        )
        progress.start("Oz is starting work on an implementation plan for this issue.")

        prompt = dedent(
            f"""
            Create a plan update for GitHub issue #{issue_number} in repository {owner}/{repo}.

            Issue Details:
            - Title: {issue_title}
            - Labels: {", ".join(label["name"] for label in issue.get("labels", [])) or "None"}
            - Assignees: {", ".join(assignee["login"] for assignee in issue.get("assignees", [])) or "None"}
            - Description: {issue.get("body") or "No description provided."}

            Previous Issue Comments From Organization Members:
            {comments_text or "- None"}

            Explicit Triggering Comment:
            {triggering_comment_text or "- None"}

            Cloud Workflow Requirements:
            - Use the repository's local `create-plan` skill as the base workflow.
            - You are running in a cloud environment, so the caller cannot read your local diff.
            - Start from the repository default branch `{default_branch}`.
            - Create or update exactly one plan file at `plans/issue-{issue_number}.md`.
            - If you produce plan changes, commit only the plan changes to branch `{branch_name}` and push that branch to origin.
            - Do not open or update the pull request yourself.
            - If there is no worthwhile plan diff, do not push the branch.
            """
        ).strip()

        config = build_agent_config(
            config_name="create-plan-from-issue",
            workspace=workspace(),
            environment_env_names=[
                "WARP_AGENT_PLAN_ENVIRONMENT_ID",
                "WARP_AGENT_ENVIRONMENT_ID",
            ],
        )

        run = run_agent(
            prompt=prompt,
            skill_name="create-plan",
            title=f"Create plan for issue #{issue_number}",
            config=config,
            on_poll=lambda current_run: _on_poll(progress, current_run),
        )

        if not branch_updated_since(
            github,
            owner,
            repo,
            branch_name,
            created_after=run.created_at - timedelta(minutes=1),
        ):
            progress.complete("I analyzed this issue but did not produce a plan diff.")
            return

        existing_prs = github.list_pulls(owner, repo, state="open", head=f"{owner}:{branch_name}")
        pr_body = build_pr_body(
            github,
            owner,
            repo,
            issue_number=issue_number,
            head=branch_name,
            base=default_branch,
            session_link=getattr(run, "session_link", None) or "",
            closing_keyword="",
        )
        if existing_prs:
            pr = github.update_pull(
                owner,
                repo,
                int(existing_prs[0]["number"]),
                title=f"plan: {issue_title}",
                body=pr_body,
            )
        else:
            pr = github.create_pull(
                owner,
                repo,
                title=f"plan: {issue_title}",
                head=branch_name,
                base=default_branch,
                body=pr_body,
                draft=False,
            )
        plan_preview_section = build_plan_preview_section(owner, repo, branch_name, issue_number)
        next_steps_section = build_next_steps_section(
            [
                "Review the plan PR and confirm that the proposed approach looks right.",
                "Request or make any needed plan updates before moving on to implementation.",
            ]
        )
        progress.complete(
            f"I created a plan PR for this issue: {pr['html_url']}\n\n"
            f"{plan_preview_section}\n\n"
            f"{next_steps_section}"
        )


def _on_poll(progress: WorkflowProgressComment, run: object) -> None:
    session_link = getattr(run, "session_link", None) or ""
    progress.record_session_link(session_link)


if __name__ == "__main__":
    main()
