from __future__ import annotations

from datetime import timedelta
from textwrap import dedent

from oz_workflows.env import load_event, repo_parts, repo_slug, workspace, require_env
from oz_workflows.github_api import GitHubClient
from oz_workflows.helpers import (
    branch_updated_since,
    build_next_steps_section,
    build_plan_preview_section,
    org_member_comments_text,
    update_status_comment,
    upsert_status_comment,
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

    with GitHubClient(require_env("GH_TOKEN"), repo_slug()) as github:
        comments = github.list_issue_comments(owner, repo, issue_number)
        comments_text = org_member_comments_text(comments)
        status_comment = upsert_status_comment(
            github,
            owner,
            repo,
            issue_number,
            event_payload=event,
            workflow="create-plan-from-issue",
            status_line="Oz is starting work on an implementation plan for this issue.",
        )
        comment_id = int(status_comment["id"])
        metadata = status_comment["_oz_metadata"]
        last_session_link = {"value": ""}

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
            on_poll=lambda current_run: _on_poll(
                github,
                owner,
                repo,
                comment_id,
                metadata,
                last_session_link,
                current_run,
                "Oz is starting work on an implementation plan for this issue.",
            ),
        )

        if not branch_updated_since(
            github,
            owner,
            repo,
            branch_name,
            created_after=run.created_at - timedelta(minutes=1),
        ):
            update_status_comment(
                github,
                owner,
                repo,
                comment_id,
                status_line="I analyzed this issue but did not produce a plan diff.",
                metadata=metadata,
            )
            return

        existing_prs = github.list_pulls(owner, repo, state="open", head=f"{owner}:{branch_name}")
        pr_body = (
            f"Automated plan update for issue #{issue_number}."
            + (f"\n\nSession: {run.session_link}" if run.session_link else "")
        )
        if existing_prs:
            pr = github.update_pull(
                owner,
                repo,
                int(existing_prs[0]["number"]),
                title=f"Plan: {issue_title}",
                body=pr_body,
            )
        else:
            pr = github.create_pull(
                owner,
                repo,
                title=f"Plan: {issue_title}",
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
        update_status_comment(
            github,
            owner,
            repo,
            comment_id,
            status_line=(
                f"I created a plan PR for this issue: {pr['html_url']}\n\n"
                f"{plan_preview_section}\n\n"
                f"{next_steps_section}"
            ),
            metadata=metadata,
        )


def _on_poll(
    github: GitHubClient,
    owner: str,
    repo: str,
    comment_id: int,
    metadata: str,
    last_session_link: dict[str, str],
    run: object,
    status_line: str,
) -> None:
    session_link = getattr(run, "session_link", None) or ""
    if not session_link or session_link == last_session_link["value"]:
        return
    update_status_comment(
        github,
        owner,
        repo,
        comment_id,
        status_line=status_line,
        metadata=metadata,
        session_link=session_link,
    )
    last_session_link["value"] = session_link


if __name__ == "__main__":
    main()
