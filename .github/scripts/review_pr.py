from __future__ import annotations
from contextlib import closing

import json
import re
from textwrap import dedent
from typing import Any
from github import Auth, Github

from oz_workflows.env import optional_env, repo_parts, repo_slug, require_env, workspace
from oz_workflows.helpers import (
    is_spec_only_pr,
    record_run_session_link,
    resolve_spec_context_for_pr,
    WorkflowProgressComment,
)
from oz_workflows.artifacts import poll_for_artifact
from oz_workflows.oz_client import build_agent_config, run_agent

HUNK_HEADER_PATTERN = re.compile(
    r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? \+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@"
)


def _normalize_review_path(value: Any) -> str:
    path = str(value or "").strip()
    path = re.sub(r"^(a/|b/|\./)", "", path)
    return path


def _commentable_lines_for_patch(patch: str | None) -> dict[str, set[int]]:
    commentable_lines = {"LEFT": set(), "RIGHT": set()}
    if not patch:
        return commentable_lines

    old_line: int | None = None
    new_line: int | None = None

    for raw_line in patch.splitlines():
        header_match = HUNK_HEADER_PATTERN.match(raw_line)
        if header_match:
            old_line = int(header_match.group("old_start"))
            new_line = int(header_match.group("new_start"))
            continue
        if old_line is None or new_line is None or raw_line.startswith("\\"):
            continue
        marker = raw_line[:1]
        if marker == "-":
            commentable_lines["LEFT"].add(old_line)
            old_line += 1
        elif marker == "+":
            commentable_lines["RIGHT"].add(new_line)
            new_line += 1
        elif marker == " ":
            commentable_lines["LEFT"].add(old_line)
            commentable_lines["RIGHT"].add(new_line)
            old_line += 1
            new_line += 1

    return commentable_lines


def _build_diff_line_map(pr: Any) -> dict[str, dict[str, set[int]]]:
    return {
        _normalize_review_path(file.filename): _commentable_lines_for_patch(
            getattr(file, "patch", None)
        )
        for file in pr.get_files()
    }


def _normalize_review_payload(
    review: dict[str, Any], diff_line_map: dict[str, dict[str, set[int]]]
) -> tuple[str, list[dict[str, Any]]]:
    if not isinstance(review, dict):
        raise ValueError("Review payload must be a JSON object.")

    summary = review.get("summary") or ""
    if not isinstance(summary, str):
        raise ValueError("Review payload `summary` must be a string.")

    raw_comments = review.get("comments") or []
    if not isinstance(raw_comments, list):
        raise ValueError("Review payload `comments` must be a list.")

    normalized_comments: list[dict[str, Any]] = []
    errors: list[str] = []

    for index, raw_comment in enumerate(raw_comments):
        if not isinstance(raw_comment, dict):
            errors.append(f"`comments[{index}]` must be an object.")
            continue

        path = _normalize_review_path(raw_comment.get("path"))
        line = raw_comment.get("line")
        body = str(raw_comment.get("body") or "").strip()
        side = raw_comment.get("side") if raw_comment.get("side") in {"LEFT", "RIGHT"} else "RIGHT"

        if not path:
            errors.append(f"`comments[{index}]` is missing `path`.")
            continue
        if path not in diff_line_map:
            errors.append(
                f"`comments[{index}]` references `{path}`, which is not part of the PR diff. Move that feedback to `summary` instead."
            )
            continue
        if not isinstance(line, int) or line <= 0:
            errors.append(
                f"`comments[{index}]` for `{path}` must include a positive integer `line`."
            )
            continue
        if not body:
            errors.append(f"`comments[{index}]` for `{path}` is missing `body`.")
            continue

        allowed_lines = diff_line_map[path][side]
        if line not in allowed_lines:
            errors.append(
                f"`comments[{index}]` references `{path}:{line}` on `{side}`, which is not commentable in the PR diff."
            )
            continue

        normalized_comment: dict[str, Any] = {
            "path": path,
            "line": line,
            "side": side,
            "body": body,
        }

        if "start_line" in raw_comment and raw_comment.get("start_line") is not None:
            start_line = raw_comment.get("start_line")
            if not isinstance(start_line, int) or start_line <= 0 or start_line >= line:
                errors.append(
                    f"`comments[{index}]` for `{path}` has invalid `start_line`; it must be a positive integer smaller than `line`."
                )
                continue
            if start_line not in allowed_lines:
                errors.append(
                    f"`comments[{index}]` references `{path}:{start_line}` on `{side}` as `start_line`, which is not commentable in the PR diff."
                )
                continue
            normalized_comment["start_line"] = start_line
            normalized_comment["start_side"] = side

        normalized_comments.append(normalized_comment)

    for err in errors:
        print(f"[review-validation] Dropped comment: {err}")

    return summary.strip(), normalized_comments


def main() -> None:
    owner, repo = repo_parts()
    pr_number = int(require_env("PR_NUMBER"))
    trigger_source = require_env("TRIGGER_SOURCE")
    requester = require_env("REQUESTER")
    focus = optional_env("REVIEW_FOCUS")
    comment_id_raw = optional_env("COMMENT_ID")
    with closing(Github(auth=Auth.Token(require_env("GH_TOKEN")))) as client:
        github = client.get_repo(repo_slug())
        pr = github.get_pull(pr_number)
        if pr.state != "open":
            return
        if comment_id_raw:
            pr.get_issue_comment(int(comment_id_raw)).create_reaction("eyes")
        progress = WorkflowProgressComment(
            github,
            owner,
            repo,
            pr_number,
            workflow="review-pull-request",
            requester_login=requester,
        )
        progress.start("Oz is reviewing this pull request.")

        spec_context = resolve_spec_context_for_pr(
            github,
            owner,
            repo,
            pr,
            workspace=workspace(),
        )
        spec_sections = []
        selected_spec_pr = spec_context.get("selected_spec_pr")
        if spec_context.get("spec_context_source") == "approved-pr" and selected_spec_pr:
            spec_sections.append(
                f"Linked approved spec PR: #{selected_spec_pr['number']} ({selected_spec_pr['url']})"
            )
        elif spec_context.get("spec_context_source") == "directory":
            spec_sections.append("Repository spec context was found in `specs/`.")
        for entry in spec_context.get("spec_entries", []):
            spec_sections.append(f"## {entry['path']}\n\n{entry['content']}")
        spec_context_text = "\n\n".join(spec_sections).strip() or "No approved or repository spec context was found for this PR."
        issue_line = (
            f"#{spec_context['issue_number']}"
            if spec_context.get("issue_number")
            else "No associated issue resolved for spec lookup."
        )

        changed_files: list[str] = spec_context.get("changed_files", [])
        spec_only = is_spec_only_pr(changed_files)
        skill_name = "review-spec" if spec_only else "review-pr"

        focus_line = (
            f"Additional focus from @{requester}: {focus}"
            if focus
            else (
                f"The review was requested by @{requester} via a review command. Perform a general review if no extra guidance was provided."
                if trigger_source == "issue_comment"
                else "Perform a general review of the pull request."
            )
        )
        prompt = dedent(
            f"""
            Review pull request #{pr_number} in repository {owner}/{repo}.

            Pull Request Context:
            - Title: {pr.title}
            - Body: {pr.body or 'No description provided.'}
            - Base branch: {pr.base.ref}
            - Head branch: {pr.head.ref}
            - Trigger: {trigger_source}
            - {focus_line}
            - Issue: {issue_line}

            Spec Context:
            {spec_context_text}

            Cloud Workflow Requirements:
            - Use the repository's local `{skill_name}` skill as the base workflow.
            - You are running in a cloud environment rather than a local workflow checkout.
            - Fetch the PR branch, generate `pr_description.txt`, and generate `pr_diff.txt` yourself before applying the review skill.
            - The annotated diff must use the same prefixes as the old workflow: `[OLD:n]`, `[NEW:n]`, and `[OLD:n,NEW:m]`.
            - Only include comments for files and lines that exist in the generated PR diff. If feedback does not map to a diff file or commentable diff line, put it in `summary` instead of `comments`.
            - If spec context is present above, write it to `spec_context.md` before reviewing so the repository's `check-impl-against-spec` skill can be used.
            - Do not post the final review directly.
            - After you create and validate `review.json`, upload it as an artifact via `oz-dev artifact upload review.json`. The subcommand is `artifact` (singular); do not use `artifacts`.
            """
        ).strip()

        config = build_agent_config(
            config_name="review-pull-request",
            workspace=workspace(),
        )
        try:
            run = run_agent(
                prompt=prompt,
                skill_name=skill_name,
                title=f"PR review #{pr_number}",
                config=config,
                on_poll=lambda current_run: record_run_session_link(progress, current_run),
            )
            review = poll_for_artifact(run.run_id, filename="review.json")
            diff_line_map = _build_diff_line_map(pr)
            summary, comments = _normalize_review_payload(review, diff_line_map)
            if not summary and not comments:
                progress.complete("I completed the review and did not identify any actionable feedback for this pull request.")
                return
            if comments:
                pr.create_review(body=summary or "Automated review by Oz", event="COMMENT", comments=comments)
            else:
                pr.create_review(body=summary or "Automated review by Oz", event="COMMENT")
            progress.complete("I completed the review and posted feedback on this pull request.")
        except Exception:
            progress.report_error()
            raise

if __name__ == "__main__":
    main()
