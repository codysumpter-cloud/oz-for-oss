from __future__ import annotations
from contextlib import closing

from datetime import timedelta
from textwrap import dedent
from github import Auth, Github

from oz_workflows.actions import append_summary
from oz_workflows.env import load_event, repo_parts, repo_slug, workspace, require_env
from oz_workflows.helpers import (
    branch_updated_since,
    build_next_steps_section,
    build_pr_body,
    coauthor_prompt_lines,
    conventional_commit_prefix,
    is_automation_user,
    org_member_comments_text,
    record_run_session_link,
    resolve_coauthor_line,
    resolve_spec_context_for_issue,
    triggering_comment_prompt_text,
    WorkflowProgressComment,
)
from oz_workflows.oz_client import build_agent_config, run_agent, skill_file_path

IMPLEMENT_SPECS_SKILL = "implement-specs"
SPEC_DRIVEN_IMPLEMENTATION_SKILL = "spec-driven-implementation"
IMPLEMENT_ISSUE_SKILL = "implement-issue"


def main() -> None:
    owner, repo = repo_parts()
    event = load_event()
    if is_automation_user((event.get("comment") or {}).get("user")):
        return
    issue = event["issue"]
    issue_number = int(issue["number"])
    issue_title = issue["title"]
    default_branch = event["repository"]["default_branch"]
    triggering_comment_id = int((event.get("comment") or {}).get("id") or 0) or None
    with closing(Github(auth=Auth.Token(require_env("GH_TOKEN")))) as client:
        github = client.get_repo(repo_slug())
        issue_data = github.get_issue(issue_number)
        issue_data.add_to_assignees("oz-agent")
        comments = list(issue_data.get_comments())
        comments_text = org_member_comments_text(comments, exclude_comment_id=triggering_comment_id)
        triggering_comment_text = triggering_comment_prompt_text(event)
        spec_context = resolve_spec_context_for_issue(
            github,
            owner,
            repo,
            issue_number,
            workspace=workspace(),
        )
        selected_spec_pr = spec_context["selected_spec_pr"]
        target_branch = (
            selected_spec_pr["head_ref_name"]
            if selected_spec_pr
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
            not selected_spec_pr
            and not spec_context["spec_entries"]
            and len(spec_context["unapproved_spec_prs"]) > 0
        )
        if should_noop:
            progress.complete(
                "I did not start implementation because linked spec PR(s) exist for this issue but none are labeled `plan-approved`: "
                + ", ".join(f"#{pr['number']}" for pr in spec_context["unapproved_spec_prs"])
            )
            append_summary(
                "Linked spec PR(s) exist for this issue but none are labeled `plan-approved`: "
                + ", ".join(f"#{pr['number']}" for pr in spec_context["unapproved_spec_prs"])
            )
            return
        next_steps_section = build_next_steps_section(
            [
                "Review the implementation changes in the PR.",
                "Complete any manual verification needed for this issue before merging.",
            ]
        )

        spec_sections = []
        if spec_context["spec_context_source"] == "approved-pr" and selected_spec_pr:
            spec_sections.append(
                f"Linked approved spec PR: #{selected_spec_pr['number']} ({selected_spec_pr['url']})"
            )
        elif spec_context["spec_context_source"] == "directory":
            spec_sections.append("Repository spec file(s) associated with this issue were found in `specs/`.")
        for entry in spec_context["spec_entries"]:
            spec_sections.append(f"## {entry['path']}\n\n{entry['content']}")
        spec_context_text = "\n\n".join(spec_sections).strip() or "No approved or repository spec context was found."

        coauthor_line = resolve_coauthor_line(client, event)
        coauthor_directives = coauthor_prompt_lines(coauthor_line)
        implement_specs_skill_path = skill_file_path(IMPLEMENT_SPECS_SKILL)
        spec_driven_implementation_skill_path = skill_file_path(
            SPEC_DRIVEN_IMPLEMENTATION_SKILL
        )
        implement_issue_skill_path = skill_file_path(IMPLEMENT_ISSUE_SKILL)

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
            {spec_context_text}

            Cloud Workflow Requirements:
            - Use the shared implementation skills `{implement_specs_skill_path}` and `{spec_driven_implementation_skill_path}` as the base workflow for this run. Prefer the consuming repository's versions when present; otherwise use the checked-in oz-for-oss copies.
            - Read the Oz wrapper skill `{implement_issue_skill_path}` and apply its instructions for `spec_context.md`, `issue_comments.txt`, and `implementation_summary.md`.
            - You are running in a cloud environment, so the caller cannot read your local diff.
            - Work on branch `{target_branch}`.
            - If that branch already exists, fetch it and continue from it. Otherwise create it from `{default_branch}`.
            - Align the implementation with the plan context above when present.
            - Run the most relevant validation available in the repository.
            - If you produce changes, commit them to `{target_branch}` and push that branch to origin.
            - Do not open or update the pull request yourself.
            - If no implementation diff is warranted, do not push the branch.
            {coauthor_directives}
            """
        ).strip()

        config = build_agent_config(
            config_name="create-implementation-from-issue",
            workspace=workspace(),
        )

        try:
            run = run_agent(
                prompt=prompt,
                skill_name=IMPLEMENT_SPECS_SKILL,
                title=f"Implement issue #{issue_number}",
                config=config,
                on_poll=lambda current_run: record_run_session_link(progress, current_run),
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

            if selected_spec_pr:
                github.get_pull(int(selected_spec_pr["number"])).edit(title=f"{commit_type}: {issue_title}")
                progress.complete(
                    f"I pushed implementation updates to the linked approved spec PR: {selected_spec_pr['url']}\n\n"
                    f"{next_steps_section}"
                )
                return

            existing_prs = list(github.get_pulls(state="open", head=f"{owner}:{target_branch}"))
            pr_body = build_pr_body(
                github,
                owner,
                repo,
                issue_number=issue_number,
                head=target_branch,
                base=default_branch,
                session_link=getattr(run, "session_link", None) or "",
                closing_keyword="Closes",
            )
            if existing_prs:
                pr = existing_prs[0]
                pr.edit(body=pr_body)
            else:
                pr = github.create_pull(
                    title=f"{commit_type}: {issue_title}",
                    head=target_branch,
                    base=default_branch,
                    body=pr_body,
                    draft=True,
                )
            progress.complete(
                f"I created or updated a draft implementation PR for this issue: {pr.html_url}\n\n"
                f"{next_steps_section}"
            )
        except Exception:
            progress.report_error()
            raise

if __name__ == "__main__":
    main()
