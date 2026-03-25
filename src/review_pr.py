from __future__ import annotations

import json
from textwrap import dedent

from oz_workflows.env import optional_env, repo_parts, repo_slug, require_env, workspace
from oz_workflows.github_api import GitHubClient
from oz_workflows.helpers import resolve_plan_context_for_pr, WorkflowProgressComment
from oz_workflows.oz_client import build_agent_config, run_agent
from oz_workflows.transport import new_transport_token, poll_for_transport_payload


def main() -> None:
    owner, repo = repo_parts()
    pr_number = int(require_env("PR_NUMBER"))
    trigger_source = require_env("TRIGGER_SOURCE")
    requester = require_env("REQUESTER")
    focus = optional_env("REVIEW_FOCUS")
    comment_id_raw = optional_env("COMMENT_ID")

    with GitHubClient(require_env("GH_TOKEN"), repo_slug()) as github:
        pr = github.get_pull(owner, repo, pr_number)
        if pr["state"] != "open":
            return

        if comment_id_raw:
            github.create_reaction_for_issue_comment(owner, repo, int(comment_id_raw), "eyes")
        progress = WorkflowProgressComment(
            github,
            owner,
            repo,
            pr_number,
            workflow="review-pull-request",
            requester_login=requester,
        )
        progress.start("Oz is reviewing this pull request.")

        plan_context = resolve_plan_context_for_pr(
            github,
            owner,
            repo,
            pr,
            workspace=workspace(),
        )
        plan_sections = []
        selected_plan_pr = plan_context.get("selected_plan_pr")
        if plan_context.get("plan_context_source") == "approved-pr" and selected_plan_pr:
            plan_sections.append(
                f"Linked approved plan PR: #{selected_plan_pr['number']} ({selected_plan_pr['url']})"
            )
        elif plan_context.get("plan_context_source") == "directory":
            plan_sections.append("Repository plan context was found in `plans/`.")
        for entry in plan_context.get("plan_entries", []):
            plan_sections.append(f"## {entry['path']}\n\n{entry['content']}")
        plan_context_text = "\n\n".join(plan_sections).strip() or "No approved or repository plan context was found for this PR."
        issue_line = (
            f"#{plan_context['issue_number']}"
            if plan_context.get("issue_number")
            else "No associated issue resolved for plan lookup."
        )

        transport_token = new_transport_token()
        focus_line = (
            f"Additional focus from @{requester}: {focus}"
            if focus
            else (
                f"The review was requested by @{requester} via /oz-review. Perform a general review if no extra guidance was provided."
                if trigger_source == "issue_comment"
                else "Perform a general review of the pull request."
            )
        )
        prompt = dedent(
            f"""
            Review pull request #{pr_number} in repository {owner}/{repo}.

            Pull Request Context:
            - Title: {pr['title']}
            - Body: {pr.get('body') or 'No description provided.'}
            - Base branch: {pr['base']['ref']}
            - Head branch: {pr['head']['ref']}
            - Trigger: {trigger_source}
            - {focus_line}
            - Issue: {issue_line}

            Plan Context:
            {plan_context_text}

            Cloud Workflow Requirements:
            - Use the repository's local `review-pr` skill as the base workflow.
            - You are running in a cloud environment rather than a local workflow checkout.
            - Fetch the PR branch, generate `pr_description.txt`, and generate `pr_diff.txt` yourself before applying the review skill.
            - The annotated diff must use the same prefixes as the old workflow: `[OLD:n]`, `[NEW:n]`, and `[OLD:n,NEW:m]`.
            - If plan context is present above, write it to `implementation_plan_context.md` before reviewing so the repository's `check-impl-against-plan` skill can be used.
            - Do not post the final review directly.
            - After you create and validate `review.json`, post exactly one temporary issue comment on PR #{pr_number} whose body is a single HTML comment in this exact format:
              <!-- oz-workflow-transport {{"token":"{transport_token}","kind":"review-json","encoding":"base64","payload":"<BASE64_OF_REVIEW_JSON>"}} -->
            """
        ).strip()

        config = build_agent_config(
            config_name="review-pull-request",
            workspace=workspace(),
            environment_env_names=[
                "WARP_AGENT_REVIEW_ENVIRONMENT_ID",
                "WARP_AGENT_ENVIRONMENT_ID",
            ],
        )
        run_agent(
            prompt=prompt,
            skill_name="review-pr",
            title=f"PR review #{pr_number}",
            config=config,
            on_poll=lambda current_run: _on_poll(progress, current_run),
        )
        payload, transport_comment_id = poll_for_transport_payload(
            github,
            owner,
            repo,
            pr_number,
            token=transport_token,
            kind="review-json",
        )
        github.delete_comment(owner, repo, transport_comment_id)
        review = json.loads(payload["decoded_payload"])
        summary = str(review.get("summary") or "").strip()
        comments = []
        for raw_comment in review.get("comments", []):
            path = str(raw_comment.get("path") or "").strip().removeprefix("a/").removeprefix("b/").removeprefix("./")
            line = raw_comment.get("line")
            body = str(raw_comment.get("body") or "").strip()
            if not path or not isinstance(line, int) or line <= 0 or not body:
                continue
            normalized = {
                "path": path,
                "line": line,
                "side": raw_comment.get("side") if raw_comment.get("side") in {"LEFT", "RIGHT"} else "RIGHT",
                "body": body,
            }
            start_line = raw_comment.get("start_line")
            if isinstance(start_line, int) and 0 < start_line < line:
                normalized["start_line"] = start_line
                normalized["start_side"] = normalized["side"]
            comments.append(normalized)
        if not summary and not comments:
            progress.complete("I completed the review and did not identify any actionable feedback for this pull request.")
            return
        github.create_review(
            owner,
            repo,
            pr_number,
            body=summary or "Automated review by Oz",
            event="COMMENT",
            comments=comments or None,
        )
        progress.complete("I completed the review and posted feedback on this pull request.")


def _on_poll(progress: WorkflowProgressComment, run: object) -> None:
    session_link = getattr(run, "session_link", None) or ""
    progress.record_session_link(session_link)


if __name__ == "__main__":
    main()
