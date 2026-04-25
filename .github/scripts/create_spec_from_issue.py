from __future__ import annotations
from contextlib import closing

from datetime import timedelta
from textwrap import dedent
from github import Auth, Github
from oz_workflows.artifacts import load_pr_metadata_artifact
from oz_workflows.env import (
    load_event,
    repo_parts,
    repo_slug,
    resolve_issue_number,
    workspace,
    require_env,
)
from oz_workflows.helpers import (
    branch_updated_since,
    build_next_steps_section,
    build_spec_preview_section,
    coauthor_prompt_lines,
    format_spec_complete_line,
    format_spec_start_line,
    get_login,
    is_automation_user,
    org_member_comments_text,
    record_run_session_link,
    resolve_coauthor_line,
    triggering_comment_prompt_text,
    WorkflowProgressComment,
)
from oz_workflows.oz_client import build_agent_config, run_agent, skill_file_path

SPEC_DRIVEN_IMPLEMENTATION_SKILL = "spec-driven-implementation"
WRITE_PRODUCT_SPEC_SKILL = "write-product-spec"
WRITE_TECH_SPEC_SKILL = "write-tech-spec"
CREATE_PRODUCT_SPEC_SKILL = "create-product-spec"
CREATE_TECH_SPEC_SKILL = "create-tech-spec"


def main() -> None:
    owner, repo = repo_parts()
    event = load_event()
    if is_automation_user((event.get("comment") or {}).get("user")):
        return
    issue_number = resolve_issue_number(event)
    branch_name = f"oz-agent/spec-issue-{issue_number}"
    triggering_comment_id = int((event.get("comment") or {}).get("id") or 0) or None
    with closing(Github(auth=Auth.Token(require_env("GH_TOKEN")))) as client:
        github = client.get_repo(repo_slug())
        issue_data = github.get_issue(issue_number)
        issue_title = str(issue_data.title or "")
        default_branch = str(
            getattr(github, "default_branch", "")
            or (event.get("repository") or {}).get("default_branch")
            or "main"
        )
        issue_labels = [
            str(label.name or "")
            for label in (issue_data.labels or [])
            if str(label.name or "").strip()
        ]
        issue_assignees = [
            login
            for assignee in (issue_data.assignees or [])
            if (login := get_login(assignee))
        ]
        # Only call add_to_assignees when oz-agent is not already assigned.
        # The POST /issues/{n}/assignees call is otherwise a no-op that still
        # consumes API quota on every workflow run.
        current_assignees = {get_login(assignee) for assignee in (issue_data.assignees or [])}
        if "oz-agent" not in current_assignees:
            issue_data.add_to_assignees("oz-agent")
        comments = list(issue_data.get_comments())
        comments_text = org_member_comments_text(comments, exclude_comment_id=triggering_comment_id)
        triggering_comment_text = triggering_comment_prompt_text(event)
        existing_spec_prs = list(
            github.get_pulls(state="open", head=f"{owner}:{branch_name}")
        )
        is_spec_update = bool(existing_spec_prs)
        progress = WorkflowProgressComment(
            github,
            owner,
            repo,
            issue_number,
            workflow="create-spec-from-issue",
            event_payload=event,
        )
        progress.start(format_spec_start_line(is_update=is_spec_update))
        coauthor_line = resolve_coauthor_line(client, event)
        coauthor_directives = coauthor_prompt_lines(coauthor_line)
        spec_driven_implementation_skill_path = skill_file_path(
            SPEC_DRIVEN_IMPLEMENTATION_SKILL
        )
        write_product_spec_skill_path = skill_file_path(WRITE_PRODUCT_SPEC_SKILL)
        write_tech_spec_skill_path = skill_file_path(WRITE_TECH_SPEC_SKILL)
        create_product_spec_skill_path = skill_file_path(CREATE_PRODUCT_SPEC_SKILL)
        create_tech_spec_skill_path = skill_file_path(CREATE_TECH_SPEC_SKILL)

        prompt = dedent(
            f"""
            Create product and tech specs for GitHub issue #{issue_number} in repository {owner}/{repo}.

            Issue Details:
            - Title: {issue_title}
            - Labels: {", ".join(issue_labels) or "None"}
            - Assignees: {", ".join(issue_assignees) or "None"}
            - Description: {issue_data.body or "No description provided."}

            Previous Issue Comments From Organization Members:
            {comments_text or "- None"}

            Explicit Triggering Comment:
            {triggering_comment_text or "- None"}

            Cloud Workflow Requirements:
            - You are running in a cloud environment, so the caller cannot read your local diff.
            - Start from the repository default branch `{default_branch}`.
            - Use the shared spec-first skill `{spec_driven_implementation_skill_path}` as the base workflow for this run. Prefer the consuming repository's version when present; otherwise use the checked-in oz-for-oss copy.
            - First, read the shared product-spec skill `{write_product_spec_skill_path}`, then read the Oz wrapper skill `{create_product_spec_skill_path}`, and create a product spec at `specs/GH{issue_number}/product.md`.
            - Then, read the shared tech-spec skill `{write_tech_spec_skill_path}`, then read the Oz wrapper skill `{create_tech_spec_skill_path}`, and create a tech spec at `specs/GH{issue_number}/tech.md`.
            - If you produce spec changes, write `pr-metadata.json` at the repository root containing a JSON object with these required fields:
              - `branch_name`: the branch you pushed to (use `{branch_name}` exactly).
              - `pr_title`: a conventional-commit-style PR title for the spec changes (e.g. `spec: {issue_title}`).
              - `pr_summary`: the full markdown PR body (this replaces the former `pr_description.md` contents).
            - After writing `pr-metadata.json`, upload it as an artifact via `oz artifact upload pr-metadata.json` (or `oz-preview artifact upload pr-metadata.json` if the `oz` CLI is not available). Either CLI is acceptable — use whichever one is installed in the environment. The subcommand is `artifact` (singular) on both CLIs; do not use `artifacts`.
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

        try:
            run = run_agent(
                prompt=prompt,
                skill_name=SPEC_DRIVEN_IMPLEMENTATION_SKILL,
                title=f"Create specs for issue #{issue_number}",
                config=config,
                on_poll=lambda current_run: record_run_session_link(progress, current_run),
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
            metadata = load_pr_metadata_artifact(run.run_id)
            pr_title = metadata.get("pr_title") or f"spec: {issue_title}"
            pr_body = metadata["pr_summary"]
            updated_existing = bool(existing_prs)
            if existing_prs:
                pr = existing_prs[0]
                pr.edit(title=pr_title, body=pr_body)
            else:
                pr = github.create_pull(
                    title=pr_title,
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
                f"{format_spec_complete_line(is_update=updated_existing, pr_url=pr.html_url)}\n\n"
                f"{spec_preview_section}\n\n"
                f"{next_steps_section}"
            )
        except Exception:
            progress.report_error()
            raise

if __name__ == "__main__":
    main()
