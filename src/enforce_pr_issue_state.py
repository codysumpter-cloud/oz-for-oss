from __future__ import annotations

import json
from textwrap import dedent

from oz_workflows.actions import set_output
from oz_workflows.env import optional_env, repo_parts, repo_slug, require_env, workspace
from oz_workflows.github_api import GitHubClient
from oz_workflows.helpers import extract_issue_numbers_from_text, WorkflowProgressComment
from oz_workflows.oz_client import build_agent_config, run_agent
from oz_workflows.transport import new_transport_token, poll_for_transport_payload


def main() -> None:
    owner, repo = repo_parts()
    pr_number = int(require_env("PR_NUMBER"))
    requester = optional_env("REQUESTER")
    with GitHubClient(require_env("GH_TOKEN"), repo_slug()) as github:
        pr = github.get_pull(owner, repo, pr_number)
        if pr["state"] != "open":
            set_output("allow_review", "false")
            return
        progress = WorkflowProgressComment(
            github,
            owner,
            repo,
            pr_number,
            workflow="enforce-pr-issue-state",
            requester_login=requester,
        )
        progress.start("Oz is checking whether this pull request is associated with a ready issue.")

        files = github.list_pull_files(owner, repo, pr_number)
        changed_files = [file["filename"] for file in files]
        has_code_changes = any(not filename.lower().endswith(".md") for filename in changed_files)
        change_kind = "implementation" if has_code_changes else "plan"
        required_label = "ready-to-implement" if has_code_changes else "ready-to-plan"
        contribution_docs_url = f"https://github.com/{owner}/{repo}/blob/main/CONTRIBUTING.md"

        explicit_issue = None
        for issue_number in extract_issue_numbers_from_text(owner, repo, pr.get("body") or ""):
            issue = github.get_issue(owner, repo, issue_number)
            if not issue.get("pull_request"):
                explicit_issue = issue
                break

        if explicit_issue:
            labels = [
                label if isinstance(label, str) else label.get("name")
                for label in explicit_issue.get("labels", [])
            ]
            if required_label in labels:
                progress.complete(
                    f"I confirmed that this pull request is associated with issue #{explicit_issue['number']} and review may continue."
                )
                set_output("allow_review", "true")
                return
            close_comment = (
                f"The PR that you've opened seems to contain {change_kind} changes and is associated with issue "
                f"#{explicit_issue['number']}, which is not marked as `{required_label}`. This PR will be "
                f"automatically closed. Please see our [contribution docs]({contribution_docs_url}) for guidance "
                "on when changes are accepted for issues."
            )
            progress.complete(close_comment)
            github.update_pull(owner, repo, pr_number, state="closed")
            set_output("allow_review", "false")
            return

        ready_issues = [
            issue
            for issue in github.list_repo_issues(owner, repo, state="open", labels=required_label)
            if not issue.get("pull_request")
        ]
        candidate_issues = [
            {
                "number": issue["number"],
                "title": issue["title"],
                "body": issue.get("body") or "",
                "url": issue["html_url"],
                "labels": [
                    label if isinstance(label, str) else label.get("name")
                    for label in issue.get("labels", [])
                ],
            }
            for issue in ready_issues
        ]

        transport_token = new_transport_token()
        prompt = dedent(
            f"""
            Determine whether pull request #{pr_number} in repository {owner}/{repo} is clearly associated with one of the ready issues below.

            Pull Request Context:
            - Title: {pr['title']}
            - Body: {pr.get('body') or 'No description provided.'}
            - Branch: {pr['head']['ref']}
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
            - Post exactly one temporary issue comment on PR #{pr_number} whose body is a single HTML comment in this exact format:
              <!-- oz-workflow-transport {{"token":"{transport_token}","kind":"issue-association","encoding":"base64","payload":"<BASE64_OF_JSON>"}} -->
            """
        ).strip()

        config = build_agent_config(
            config_name="enforce-pr-issue-state",
            workspace=workspace(),
            environment_env_names=[
                "WARP_AGENT_ENFORCEMENT_ENVIRONMENT_ID",
                "WARP_AGENT_ENVIRONMENT_ID",
            ],
        )
        run_agent(
            prompt=prompt,
            skill_name=None,
            title=f"Associate PR #{pr_number} with ready issue",
            config=config,
            on_poll=lambda current_run: _on_poll(progress, current_run),
        )
        payload, comment_id = poll_for_transport_payload(
            github,
            owner,
            repo,
            pr_number,
            token=transport_token,
            kind="issue-association",
        )
        github.delete_comment(owner, repo, comment_id)
        result = json.loads(payload["decoded_payload"])
        if result.get("matched") is True and isinstance(result.get("issue_number"), int):
            progress.complete(
                f"I confirmed that this pull request is associated with issue #{result['issue_number']} and review may continue."
            )
            set_output("allow_review", "true")
            return
        close_comment = str(result.get("close_comment") or "").strip()
        if not close_comment:
            raise RuntimeError("Oz returned no issue match without a close_comment")
        progress.complete(close_comment)
        github.update_pull(owner, repo, pr_number, state="closed")
        set_output("allow_review", "false")


def _on_poll(progress: WorkflowProgressComment, run: object) -> None:
    session_link = getattr(run, "session_link", None) or ""
    progress.record_session_link(session_link)


if __name__ == "__main__":
    main()
