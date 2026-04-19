from __future__ import annotations
from contextlib import closing

import json
from textwrap import dedent
from github import Auth, Github

from oz_workflows.actions import set_output
from oz_workflows.env import optional_env, repo_parts, repo_slug, require_env, workspace
from oz_workflows.helpers import (
    extract_issue_numbers_from_text,
    format_enforce_start_line,
    ORG_MEMBER_ASSOCIATIONS,
    WorkflowProgressComment,
)
from oz_workflows.artifacts import poll_for_artifact
from oz_workflows.oz_client import build_agent_config, run_agent


def _is_pr_author_org_member(pr: dict) -> bool:
    """Return True if the PR author is an organization member or owner."""
    association = pr.get("author_association", "") if isinstance(pr, dict) else getattr(pr, "author_association", "")
    return association in ORG_MEMBER_ASSOCIATIONS


def main() -> None:
    owner, repo = repo_parts()
    pr_number = int(require_env("PR_NUMBER"))
    requester = optional_env("REQUESTER")
    with closing(Github(auth=Auth.Token(require_env("GH_TOKEN")))) as client:
        github = client.get_repo(repo_slug())
        pr = github.get_pull(pr_number)
        pr_issue = pr.as_issue()
        if pr.state != "open":
            set_output("allow_review", "false")
            return
        if _is_pr_author_org_member(pr):
            set_output("allow_review", "true")
            return
        progress = WorkflowProgressComment(
            github,
            owner,
            repo,
            pr_number,
            workflow="enforce-pr-issue-state",
            requester_login=requester,
        )
        files = list(pr.get_files())
        changed_files = [str(file.filename) for file in files]
        has_code_changes = any(not filename.lower().endswith(".md") for filename in changed_files)
        change_kind = "implementation" if has_code_changes else "spec"
        required_label = "ready-to-implement" if has_code_changes else "ready-to-spec"
        pr_labels = [label.name for label in pr_issue.labels]
        has_plan_approved = "plan-approved" in pr_labels
        contribution_docs_url = f"https://github.com/{owner}/{repo}/blob/main/CONTRIBUTING.md"

        explicit_issue = None
        for issue_number in extract_issue_numbers_from_text(owner, repo, pr.body or ""):
            issue = github.get_issue(issue_number)
            if not issue.pull_request:
                explicit_issue = issue
                break

        # Only post the state-aware start line on paths that will
        # actually reach ``progress.complete(...)``. Posting a start
        # line and then immediately deleting it via ``cleanup()`` on
        # the allow paths would still notify subscribers about a
        # comment they never see, so run the deterministic allow
        # short-circuits first and start the progress comment only
        # right before a path that posts a final user-visible update.
        # ``cleanup()`` is still called on the allow paths so that any
        # orphan progress comments left behind by a previous run on
        # the same PR are removed.
        if explicit_issue:
            labels = [label.name for label in explicit_issue.labels]
            if required_label in labels or (not has_code_changes and has_plan_approved):
                progress.cleanup()
                set_output("allow_review", "true")
                return
            progress.start(
                format_enforce_start_line(
                    explicit_issue=True,
                    change_kind=change_kind,
                )
            )
            close_comment = (
                f"The PR that you've opened seems to contain {change_kind} changes and is associated with issue "
                f"#{explicit_issue.number}, which is not marked as `{required_label}`. This PR will be "
                f"automatically closed. Please see our [contribution docs]({contribution_docs_url}) for guidance "
                "on when changes are accepted for issues."
            )
            progress.complete(close_comment)
            pr.edit(state="closed")
            set_output("allow_review", "false")
            return

        if not has_code_changes and has_plan_approved:
            progress.cleanup()
            set_output("allow_review", "true")
            return

        progress.start(
            format_enforce_start_line(
                explicit_issue=False,
                change_kind=change_kind,
            )
        )

        ready_issues = [
            issue
            for issue in github.get_issues(state="open", labels=[required_label])
            if not issue.pull_request
        ]
        candidate_issues = [
            {
                "number": issue.number,
                "title": issue.title,
                "body": issue.body or "",
                "url": issue.html_url,
                "labels": [label.name for label in issue.labels],
            }
            for issue in ready_issues
        ]

        prompt = dedent(
            f"""
            Determine whether pull request #{pr_number} in repository {owner}/{repo} is clearly associated with one of the ready issues below.

            Pull Request Context:
            - Title: {pr.title}
            - Body: {pr.body or 'No description provided.'}
            - Branch: {pr.head.ref}
            - Change kind: {change_kind}
            - Required issue label: {required_label}
            - Changed files:
            {chr(10).join(f"  - {filename}" for filename in changed_files) or "  - No changed files found."}

            Candidate Ready Issues JSON:
            {json.dumps(candidate_issues, indent=2)}

            Output requirements:
            - Decide whether there is a clear match.
            - Produce JSON with exactly this shape:
              {{"matched": boolean, "issue_number": number | null, "rationale": string, "close_comment": string}}
            - If there is no clear match, set `close_comment` to a concise PR comment explaining that this {change_kind} PR could not be matched to an issue marked `{required_label}` and include this contribution docs link: {contribution_docs_url}
            - Do not close the PR yourself.
            - Validate the JSON with `jq`.
            - After validating the JSON, upload it as an artifact via `oz-dev artifact upload issue_association.json`. The subcommand is `artifact` (singular); do not use `artifacts`.
            """
        ).strip()

        session_links: list[str] = []
        config = build_agent_config(
            config_name="enforce-pr-issue-state",
            workspace=workspace(),
        )
        run = run_agent(
            prompt=prompt,
            skill_name=None,
            title=f"Associate PR #{pr_number} with ready issue",
            config=config,
            on_poll=lambda current_run: _capture_session_link(session_links, current_run),
        )
        result = poll_for_artifact(run.run_id, filename="issue_association.json")
        if result.get("matched") is True and isinstance(result.get("issue_number"), int):
            progress.cleanup()
            set_output("allow_review", "true")
            return
        close_comment = str(result.get("close_comment") or "").strip()
        if not close_comment:
            raise RuntimeError("Oz returned no issue match without a close_comment")
        final_sections = [close_comment]
        if session_links:
            final_sections.append(f"Session: [view on Warp]({session_links[-1]})")
        progress.complete("\n\n".join(final_sections))
        pr.edit(state="closed")
        set_output("allow_review", "false")


def _capture_session_link(session_links: list[str], run: object) -> None:
    session_link = (getattr(run, "session_link", None) or "").strip()
    if session_link and (not session_links or session_links[-1] != session_link):
        session_links.append(session_link)


if __name__ == "__main__":
    main()
