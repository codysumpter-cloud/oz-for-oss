from __future__ import annotations
from contextlib import closing

from datetime import timedelta
from textwrap import dedent
from github import Auth, Github

from oz_workflows.env import load_event, repo_parts, repo_slug, workspace, require_env
from oz_workflows.helpers import (
    branch_updated_since,
    build_next_steps_section,
    build_spec_preview_section,
    build_pr_body,
    coauthor_prompt_lines,
    org_member_comments_text,
    resolve_coauthor_line,
    triggering_comment_prompt_text,
    WorkflowProgressComment,
)
from oz_workflows.oz_client import build_agent_config, run_agent

SPEC_DRIVEN_IMPLEMENTATION_SKILL = "spec-driven-implementation"
SPEC_DRIVEN_IMPLEMENTATION_SKILL_PATH = ".agents/skills/spec-driven-implementation/SKILL.md"
WRITE_PRODUCT_SPEC_SKILL_PATH = ".agents/skills/write-product-spec/SKILL.md"
WRITE_TECH_SPEC_SKILL_PATH = ".agents/skills/write-tech-spec/SKILL.md"


def main() -> None:
    owner, repo = repo_parts()
    event = load_event()
    issue = event["issue"]
    issue_number = int(issue["number"])
    issue_title = issue["title"]
    default_branch = event["repository"]["default_branch"]
    branch_name = f"oz-agent/spec-issue-{issue_number}"
    triggering_comment_id = int((event.get("comment") or {}).get("id") or 0) or None
    with closing(Github(auth=Auth.Token(require_env("GH_TOKEN")))) as client:
        github = client.get_repo(repo_slug())
        issue_data = github.get_issue(issue_number)
        issue_data.add_to_assignees("oz-agent")
        comments = list(issue_data.get_comments())
        comments_text = org_member_comments_text(comments, exclude_comment_id=triggering_comment_id)
        triggering_comment_text = triggering_comment_prompt_text(event)
        progress = WorkflowProgressComment(
            github,
            owner,
            repo,
            issue_number,
            workflow="create-spec-from-issue",
            event_payload=event,
        )
        progress.start("Oz is starting work on product and tech specs for this issue.")
        coauthor_line = resolve_coauthor_line(client, event)
        coauthor_directives = coauthor_prompt_lines(coauthor_line)

        prompt = dedent(
            f"""
            Create product and tech specs for GitHub issue #{issue_number} in repository {owner}/{repo}.

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
            - You are running in a cloud environment, so the caller cannot read your local diff.
            - Start from the repository default branch `{default_branch}`.
            - Use the local shared skill `{SPEC_DRIVEN_IMPLEMENTATION_SKILL_PATH}` as the base spec-first workflow for this run.
            - First, read the local shared skill `{WRITE_PRODUCT_SPEC_SKILL_PATH}`, then read `.agents/skills/create-product-spec/SKILL.md` for the Oz-specific wrapper instructions, and create a product spec at `specs/issue-{issue_number}/product.md`.
            - Then, read the local shared skill `{WRITE_TECH_SPEC_SKILL_PATH}`, then read `.agents/skills/create-tech-spec/SKILL.md` for the Oz-specific wrapper instructions, and create a tech spec at `specs/issue-{issue_number}/tech.md`.
            - If you produce spec changes, commit only the spec changes to branch `{branch_name}` and push that branch to origin.
            - Do not open or update the pull request yourself.
            - If there is no worthwhile spec diff, do not push the branch.
            {coauthor_directives}
            """
        ).strip()

        config = build_agent_config(
            config_name="create-spec-from-issue",
            workspace=workspace(),
        )

        run = run_agent(
            prompt=prompt,
            skill_name=SPEC_DRIVEN_IMPLEMENTATION_SKILL,
            title=f"Create specs for issue #{issue_number}",
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
            progress.complete("I analyzed this issue but did not produce a spec diff.")
            return
        existing_prs = list(github.get_pulls(state="open", head=f"{owner}:{branch_name}"))
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
            pr = existing_prs[0]
            pr.edit(title=f"spec: {issue_title}", body=pr_body)
        else:
            pr = github.create_pull(
                title=f"spec: {issue_title}",
                head=branch_name,
                base=default_branch,
                body=pr_body,
                draft=False,
            )
        spec_preview_section = build_spec_preview_section(owner, repo, branch_name, issue_number)
        next_steps_section = build_next_steps_section(
            [
                "Review the spec PR and confirm that the proposed approach looks right.",
                "Request or make any needed spec updates before moving on to implementation.",
            ]
        )
        progress.complete(
            f"I created a spec PR for this issue: {pr.html_url}\n\n"
            f"{spec_preview_section}\n\n"
            f"{next_steps_section}"
        )


def _on_poll(progress: WorkflowProgressComment, run: object) -> None:
    session_link = getattr(run, "session_link", None) or ""
    progress.record_session_link(session_link)


if __name__ == "__main__":
    main()
