from __future__ import annotations
from contextlib import closing
import logging

import json
import re
from pathlib import Path
from textwrap import dedent
from typing import Any, TypedDict
from github import Auth, Github
from github.File import File
from github.GithubException import GithubException

from oz_workflows.env import optional_env, repo_parts, repo_slug, require_env, workspace
from oz_workflows.helpers import (
    format_review_start_line,
    is_automation_user,
    is_spec_only_pr,
    ORG_MEMBER_ASSOCIATIONS,
    POWERED_BY_SUFFIX,
    record_run_session_link,
    resolve_spec_context_for_pr,
    WorkflowProgressComment,
)
from oz_workflows.artifacts import poll_for_artifact
from oz_workflows.oz_client import build_agent_config, run_agent
from oz_workflows.repo_local import (
    format_repo_local_prompt_section,
    resolve_repo_local_skill_path,
)
from oz_workflows.triage import format_stakeholders_for_prompt, load_stakeholders

logger = logging.getLogger(__name__)

# Maximum number of human reviewers to request from STAKEHOLDERS so we don't
# over-notify maintainers on a single non-member PR.
_MAX_STAKEHOLDER_REVIEWERS = 3
# ``verdict`` values the agent is allowed to emit for non-member PRs. These
# map directly to GitHub's ``event`` parameter on the create-review endpoint.
_ALLOWED_NON_MEMBER_VERDICTS = {"APPROVE", "REQUEST_CHANGES"}


class ReviewComment(TypedDict, total=False):
    """Normalized review comment accepted by ``PullRequest.create_review``."""

    path: str
    line: int
    side: str
    body: str
    start_line: int
    start_side: str


HUNK_HEADER_PATTERN = re.compile(
    r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? \+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@"
)

SUGGESTION_BLOCK_PATTERN = re.compile(
    r"```suggestion[^\n]*\r?\n(?P<content>.*?)\r?\n```",
    re.DOTALL,
)


def _normalize_review_path(value: Any) -> str:
    path = str(value or "").strip()
    path = re.sub(r"^(a/|b/|\./)", "", path)
    return path


def _is_non_member_pr(pr: Any) -> bool:
    """Return True if the PR author is not an organization member/collaborator.

    Non-member PRs receive the review-action gate (APPROVE or
    REQUEST_CHANGES) and, on APPROVE, a review request targeted at
    matching ``.github/STAKEHOLDERS`` entries. Member/collaborator PRs
    keep the existing ``COMMENT`` behavior.

    PRs authored by automation accounts (bots, including the Oz bot
    reviewing its own PRs) always fall back to ``COMMENT`` so we never
    try to APPROVE or REQUEST_CHANGES on them; attempting an APPROVE on
    a self-authored PR is rejected by the GitHub API. Likewise, when
    ``author_association`` is missing, empty, or not a string we cannot
    positively classify the author as a non-member, so we conservatively
    fall back to the safe ``COMMENT`` path rather than assuming the
    author is a non-member.
    """
    if is_automation_user(getattr(pr, "user", None)):
        return False
    association = getattr(pr, "author_association", None)
    if not isinstance(association, str):
        return False
    normalized = association.strip().upper()
    if not normalized:
        return False
    return normalized not in ORG_MEMBER_ASSOCIATIONS


def _normalize_reviewer_logins(
    candidates: Any,
    *,
    pr_author_login: str,
    limit: int = _MAX_STAKEHOLDER_REVIEWERS,
) -> list[str]:
    """Normalize and cap a list of recommended reviewer logins from the agent.

    Strips leading ``@`` characters, drops blanks and non-string entries,
    de-duplicates while preserving first-seen order, removes the PR
    author (GitHub rejects self-review requests), and caps the result
    at ``limit`` entries so we don't over-notify maintainers.
    """
    if not isinstance(candidates, list):
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        login = candidate.strip().lstrip("@")
        if not login:
            continue
        if login.lower() == (pr_author_login or "").strip().lower():
            continue
        if login in seen:
            continue
        seen.add(login)
        normalized.append(login)
        if len(normalized) >= limit:
            break
    return normalized


def _resolve_non_member_review_action(
    review: dict[str, Any],
    *,
    pr_author_login: str,
) -> tuple[str, list[str]]:
    """Extract and validate the verdict + reviewer list for a non-member PR.

    Returns a tuple of ``(event, reviewers)`` where ``event`` is the
    GitHub ``create_review`` event string (``"APPROVE"`` or
    ``"REQUEST_CHANGES"``) and ``reviewers`` is the normalized list of
    GitHub logins to request a review from (always empty on
    ``REQUEST_CHANGES``). Raises ``ValueError`` when the agent returned
    an unsupported ``verdict``.
    """
    verdict_raw = str(review.get("verdict") or "").strip().upper()
    if verdict_raw not in _ALLOWED_NON_MEMBER_VERDICTS:
        raise ValueError(
            f"Review payload `verdict` must be one of {sorted(_ALLOWED_NON_MEMBER_VERDICTS)} for a non-member PR; got {verdict_raw!r}."
        )
    reviewers = (
        _normalize_reviewer_logins(
            review.get("recommended_reviewers"),
            pr_author_login=pr_author_login,
        )
        if verdict_raw == "APPROVE"
        else []
    )
    return verdict_raw, reviewers


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


def _line_content_for_patch(patch: str | None) -> dict[str, dict[int, str]]:
    """Return file content known from the patch, keyed by side and line number."""
    line_content: dict[str, dict[int, str]] = {"LEFT": {}, "RIGHT": {}}
    if not patch:
        return line_content

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
        text = raw_line[1:]
        if marker == "-":
            line_content["LEFT"][old_line] = text
            old_line += 1
        elif marker == "+":
            line_content["RIGHT"][new_line] = text
            new_line += 1
        elif marker == " ":
            line_content["LEFT"][old_line] = text
            line_content["RIGHT"][new_line] = text
            old_line += 1
            new_line += 1

    return line_content


def _build_diff_maps(
    files: list[File],
) -> tuple[dict[str, dict[str, set[int]]], dict[str, dict[str, dict[int, str]]]]:
    diff_line_map: dict[str, dict[str, set[int]]] = {}
    diff_content_map: dict[str, dict[str, dict[int, str]]] = {}
    for file in files:
        path = _normalize_review_path(file.filename)
        patch = file.patch
        diff_line_map[path] = _commentable_lines_for_patch(patch)
        diff_content_map[path] = _line_content_for_patch(patch)
    return diff_line_map, diff_content_map


def _build_diff_line_map(files: list[File]) -> dict[str, dict[str, set[int]]]:
    diff_line_map, _ = _build_diff_maps(files)
    return diff_line_map


def _extract_suggestion_blocks(body: str | None) -> list[list[str]]:
    """Extract the line content of each ```suggestion fenced block in the body."""
    blocks: list[list[str]] = []
    for match in SUGGESTION_BLOCK_PATTERN.finditer(body or ""):
        content = match.group("content")
        # Strip the trailing newline introduced by the closing fence, but keep
        # any internal blank lines intact. Also strip a trailing CR so that
        # CRLF-encoded bodies compare equal to patch content, which has CR
        # stripped by str.splitlines().
        lines = [line.rstrip("\r") for line in content.split("\n")]
        blocks.append(lines)
    return blocks


def _validate_suggestion_blocks(
    comment: dict[str, Any],
    diff_content_map: dict[str, dict[str, dict[int, str]]],
) -> list[str]:
    """Return a list of validation errors for the suggestion blocks in a comment.

    Checks that the suggestion block does not duplicate context lines that
    sit immediately outside the replaced `start_line`–`line` range on the
    given side of the diff.
    """
    errors: list[str] = []
    body = comment.get("body") or ""
    blocks = _extract_suggestion_blocks(body)
    if not blocks:
        return errors

    path = comment.get("path") or ""
    side = comment.get("side") or "RIGHT"
    line_no = comment.get("line")
    if not isinstance(line_no, int):
        return errors
    start_line = comment.get("start_line") or line_no
    content_for_side = diff_content_map.get(path, {}).get(side, {})

    for block_index, block_lines in enumerate(blocks):
        if not block_lines or block_lines == [""]:
            continue
        prev_context = content_for_side.get(start_line - 1)
        next_context = content_for_side.get(line_no + 1)
        first_line = block_lines[0]
        last_line = block_lines[-1]
        if prev_context is not None and first_line == prev_context:
            errors.append(
                f"suggestion block {block_index} duplicates the context line immediately above "
                f"`start_line` ({start_line - 1}); that line is not replaced and will appear twice after the suggestion is applied"
            )
        if next_context is not None and last_line == next_context:
            errors.append(
                f"suggestion block {block_index} duplicates the context line immediately below "
                f"`line` ({line_no + 1}); that line is not replaced and will appear twice after the suggestion is applied"
            )
    return errors


def _normalize_review_payload(
    review: dict[str, Any],
    diff_line_map: dict[str, dict[str, set[int]]],
    diff_content_map: dict[str, dict[str, dict[int, str]]] | None = None,
) -> tuple[str, list[ReviewComment]]:
    if not isinstance(review, dict):
        raise ValueError("Review payload must be a JSON object.")

    summary = review.get("summary") or ""
    if not isinstance(summary, str):
        raise ValueError("Review payload `summary` must be a string.")

    raw_comments = review.get("comments") or []
    if not isinstance(raw_comments, list):
        raise ValueError("Review payload `comments` must be a list.")

    normalized_comments: list[ReviewComment] = []
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

        normalized_comment: ReviewComment = {
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

        if diff_content_map is not None:
            suggestion_errors = _validate_suggestion_blocks(
                normalized_comment, diff_content_map
            )
            if suggestion_errors:
                for err in suggestion_errors:
                    errors.append(
                        f"`comments[{index}]` for `{path}:{line}` on `{side}` has an invalid suggestion block: {err}."
                    )
                continue

        normalized_comments.append(normalized_comment)

    for err in errors:
        print(f"[review-validation] Dropped comment: {err}")

    return summary.strip(), normalized_comments


def _format_review_completion_message(
    event: str,
    recommended_reviewers: list[str],
) -> str:
    """Build the progress-comment completion message for a posted review."""
    if event == "APPROVE":
        if recommended_reviewers:
            mentions = ", ".join(f"@{login}" for login in recommended_reviewers)
            return (
                "I approved this pull request and requested human review from: "
                f"{mentions}."
            )
        return (
            "I approved this pull request. No matching stakeholder was found "
            "for the changed files, so no human reviewers were requested."
        )
    if event == "REQUEST_CHANGES":
        return "I requested changes on this pull request and posted feedback."
    return "I completed the review and posted feedback on this pull request."


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
        spec_context = resolve_spec_context_for_pr(
            github,
            owner,
            repo,
            pr,
            workspace=workspace(),
        )
        changed_files: list[str] = spec_context.get("changed_files", [])
        spec_only = is_spec_only_pr(changed_files)
        # Re-review requests arrive via the `/oz-review` slash command,
        # which resolves trigger_source to the triggering comment event
        # (``issue_comment`` or ``pull_request_review_comment``). A first
        # automated review runs through ``pull_request`` / ``pr-hooks``.
        is_rereview = trigger_source in {
            "issue_comment",
            "pull_request_review_comment",
        }
        progress = WorkflowProgressComment(
            github,
            owner,
            repo,
            pr_number,
            workflow="review-pull-request",
            requester_login=requester,
        )
        progress.start(
            format_review_start_line(
                spec_only=spec_only,
                is_rereview=is_rereview,
                focus=focus,
            )
        )
        spec_sections = []
        selected_spec_pr = spec_context.get("selected_spec_pr")
        if spec_context.get("spec_context_source") == "approved-pr" and selected_spec_pr:
            spec_sections.append(
                f"Linked approved spec PR: [#{selected_spec_pr['number']}]({selected_spec_pr['url']})"
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
        supplemental_skill_line = (
            "Also apply the repository's local `security-review-spec` skill as a supplemental high-level security pass and fold any security findings into the same combined `review.json`. Do not produce a separate security review output."
            if spec_only
            else "Also apply the repository's local `security-review-pr` skill as a supplemental security pass and fold any security findings into the same combined `review.json`. Do not produce a separate security review output."
        )
        companion_path = resolve_repo_local_skill_path(workspace(), skill_name)
        if companion_path is not None:
            repo_local_section = format_repo_local_prompt_section(
                skill_name, companion_path
            )
        else:
            repo_local_section = ""

        # Non-member PRs go through an additional "review action" gate: the
        # agent is asked to emit a verdict (APPROVE or REQUEST_CHANGES) and
        # a list of matching ``.github/STAKEHOLDERS`` logins to request as
        # human reviewers, and the workflow turns those into a real
        # pull-request review plus reviewer requests. Member/collaborator
        # PRs keep the existing COMMENT-only behavior. Spec-only PRs are
        # intentionally exempted from the gate so humans stay in the loop
        # earlier for spec changes.
        is_non_member = _is_non_member_pr(pr) and not spec_only
        pr_author_login = str(
            getattr(getattr(pr, "user", None), "login", "") or ""
        )
        non_member_review_section = ""
        if is_non_member:
            stakeholders_entries = load_stakeholders(
                Path(workspace()) / ".github" / "STAKEHOLDERS"
            )
            stakeholders_block = format_stakeholders_for_prompt(
                stakeholders_entries
            )
            non_member_review_section = dedent(
                f"""
                Non-Member Review Action:
                - The PR author (@{pr_author_login or 'unknown'}) is not a
                  repository member or collaborator, so this review must
                  commit to a verdict rather than just leaving comments.
                - Choose exactly one ``verdict`` for the review, using the
                  GitHub review event naming:
                  - ``APPROVE`` when the PR looks ready for a human to
                    take over.
                  - ``REQUEST_CHANGES`` when the PR clearly needs rework
                    before a human should spend time reviewing it.
                  Never emit ``COMMENT`` for this PR.
                - Identify up to {_MAX_STAKEHOLDER_REVIEWERS} ``recommended_reviewers`` from
                  ``.github/STAKEHOLDERS`` (CODEOWNERS-style syntax; later
                  rules override earlier ones, most specific pattern wins
                  over catch-all rules) by matching the changed file paths
                  against each rule. De-duplicate across files, prefer
                  more specific rules over catch-all rules, and strip any
                  leading ``@`` from each login. Exclude the PR author
                  (@{pr_author_login or 'unknown'}) — GitHub rejects
                  self-review requests.
                - Only populate ``recommended_reviewers`` when the verdict
                  is ``APPROVE``. Set it to an empty list on
                  ``REQUEST_CHANGES``.
                - Extend the ``review.json`` shape with these two fields
                  alongside ``summary``/``comments``:
                  {{"verdict": "APPROVE" | "REQUEST_CHANGES", "recommended_reviewers": [string, ...]}}
                - Do not call GitHub yourself to post the review or to
                  request reviewers — the workflow will use these fields
                  to post the formal pull-request review and, on
                  ``APPROVE``, request reviews from the listed logins.

                Stakeholders (from ``.github/STAKEHOLDERS``):
                {stakeholders_block}
                """
            ).strip()

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
            - {supplemental_skill_line}
            - You are running in a cloud environment rather than a local workflow checkout.
            - You must check out the exact PR head branch before generating the diff. Run:
                ```
                git fetch origin {pr.head.ref}
                git checkout {pr.head.ref}
                ```
              Do NOT use FETCH_HEAD — always reference the named branch.
            - Generate the diff against the base branch using a three-dot merge-base diff:
                ```
                git diff origin/{pr.base.ref}...HEAD
                ```
              This isolates only the changes introduced by the PR.
            - Generate `pr_description.txt` and `pr_diff.txt` yourself before applying the review skill.
            - The annotated diff must use the same prefixes as the old workflow: `[OLD:n]`, `[NEW:n]`, and `[OLD:n,NEW:m]`.
            - Only include comments for files and lines that exist in the generated PR diff. If feedback does not map to a diff file or commentable diff line, put it in `summary` instead of `comments`.
            - If spec context is present above, write it to `spec_context.md` before reviewing so the repository's `check-impl-against-spec` skill can be used.
            - Do not post the final review directly.
            - After you create and validate `review.json`, upload it as an artifact via `oz artifact upload review.json` (or `oz-preview artifact upload review.json` if the `oz` CLI is not available). Either CLI is acceptable — use whichever one is installed in the environment. The subcommand is `artifact` (singular) on both CLIs; do not use `artifacts`.
            """
        ).strip()
        if repo_local_section:
            # Insert the repo-local reference between the Spec Context block
            # and the Cloud Workflow Requirements block. When no companion
            # file is present the prompt is byte-for-byte identical to the
            # pre-split shape; when one is present the agent is pointed at
            # the companion path without inlining its body.
            prompt = prompt.replace(
                "\n\nCloud Workflow Requirements:",
                "\n\n" + repo_local_section.rstrip() + "\n\nCloud Workflow Requirements:",
                1,
            )
        if non_member_review_section:
            # Append the non-member review-action block after the Cloud
            # Workflow Requirements so the base review behavior (comments
            # etc.) is still described up front, and the additional
            # verdict/stakeholder contract is laid out separately.
            prompt = prompt + "\n\n" + non_member_review_section

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
            diff_line_map, diff_content_map = _build_diff_maps(
                spec_context.get("pr_files", [])
            )
            summary, comments = _normalize_review_payload(
                review, diff_line_map, diff_content_map
            )
            if is_non_member:
                try:
                    event, recommended_reviewers = _resolve_non_member_review_action(
                        review,
                        pr_author_login=pr_author_login,
                    )
                except ValueError:
                    # The agent returned an unsupported ``verdict``.
                    # Degrade to COMMENT so any valid ``summary`` /
                    # ``comments`` still land on the PR instead of
                    # failing the whole workflow and throwing away the
                    # feedback that was produced.
                    logger.exception(
                        "Falling back to COMMENT for non-member PR #%s in %s/%s due to invalid review action payload",
                        pr_number,
                        owner,
                        repo,
                    )
                    event = "COMMENT"
                    recommended_reviewers = []
            else:
                event = "COMMENT"
                recommended_reviewers = []
            if not summary and not comments and event == "COMMENT":
                # For member PRs the legacy short-circuit stands: if the
                # agent had nothing to say, skip posting an empty review.
                # Non-member PRs always post so the verdict lands on the
                # PR even when the agent has no inline comments.
                progress.complete("I completed the review and did not identify any actionable feedback for this pull request.")
                return
            review_body = f"{summary or 'Automated review'}\n\n{POWERED_BY_SUFFIX}"
            if comments:
                pr.create_review(body=review_body, event=event, comments=comments)
            else:
                pr.create_review(body=review_body, event=event)
            if event == "APPROVE" and recommended_reviewers:
                try:
                    pr.create_review_request(reviewers=recommended_reviewers)
                except GithubException:
                    # Requesting reviewers is best-effort — an invalid
                    # login or a maintainer who cannot review this
                    # repository should not fail the workflow after the
                    # formal review has already been posted.
                    logger.exception(
                        "Failed to request reviewers %s for PR #%s in %s/%s",
                        recommended_reviewers,
                        pr_number,
                        owner,
                        repo,
                    )
            progress.complete(_format_review_completion_message(event, recommended_reviewers))
        except Exception:
            progress.report_error()
            raise


if __name__ == "__main__":
    main()
