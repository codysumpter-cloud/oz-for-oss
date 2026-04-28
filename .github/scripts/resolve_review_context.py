from __future__ import annotations

import re
from contextlib import closing
from typing import Any

from github import Auth, Github

from oz_workflows.actions import notice, set_output
from oz_workflows.env import load_event, optional_env, repo_slug
from oz_workflows.helpers import is_automation_user


# The slash command intentionally has no capture group: any text after
# ``/oz-review`` (or ``@oz-agent /review``) is ignored so commenters
# cannot inject a free-form prompt into the agent's review run.
SLASH_COMMAND_PATTERN = re.compile(
    r"(?:^|\s)(?:/oz-review|@oz-agent\s+/review)\b", re.IGNORECASE
)

# Maximum number of explicit ``/oz-review`` invocations the workflow will
# act on per pull request. The cap covers both PR conversation comments
# and inline review-thread comments combined so a single PR can
# accumulate at most this many manually requested reviews. Re-reviews
# triggered by the automatic ``pull_request_target`` events do not count
# against this limit.
MAX_EXPLICIT_INVOCATIONS_PER_PR = 3


def _count_explicit_invocations(
    client: Github, repo_full_name: str, pr_number: int
) -> int:
    """Return the number of ``/oz-review`` slash-command comments on a PR.

    Counts both PR conversation (issue) comments and inline review
    comments. The triggering comment that just landed is included in
    this count because GitHub has already persisted it by the time the
    workflow runs. Comments authored by automation accounts (bots) are
    excluded so a chatty bot cannot exhaust the per-PR throttle on
    behalf of human reviewers.
    """
    repo = client.get_repo(repo_full_name)
    pr = repo.get_pull(pr_number)
    count = 0
    for comment in pr.get_issue_comments():
        body = getattr(comment, "body", "") or ""
        if not SLASH_COMMAND_PATTERN.search(body):
            continue
        if is_automation_user(getattr(comment, "user", None)):
            continue
        count += 1
    for comment in pr.get_review_comments():
        body = getattr(comment, "body", "") or ""
        if not SLASH_COMMAND_PATTERN.search(body):
            continue
        if is_automation_user(getattr(comment, "user", None)):
            continue
        count += 1
    return count


def _resolve_comment_match(
    event: dict[str, Any], event_name: str
) -> tuple[bool, str, str, str]:
    """Resolve the slash-command intent for a comment-based event.

    Returns ``(matched, pr_number, requester, comment_id)`` where
    ``matched`` indicates that the comment carries an explicit
    ``/oz-review`` (or equivalent ``@oz-agent /review``) invocation
    from a non-automation user on a PR with a valid positive number.
    The PR number is empty when there is no associated pull request.
    ``comment_id`` is only populated for PR conversation comments
    because downstream reaction handling uses the issue-comment API.
    Any text following the slash command is intentionally discarded so
    commenters cannot supply a free-form prompt to the review agent.
    """
    if event_name == "issue_comment":
        issue = event.get("issue") or {}
        is_pr = bool(issue.get("pull_request"))
        pr_number = str(issue.get("number") or "") if is_pr else ""
    elif event_name == "pull_request_review_comment":
        pull_request = event.get("pull_request") or {}
        is_pr = True
        pr_number = str(pull_request.get("number") or "")
    else:
        return False, "", "", ""

    comment = event.get("comment") or {}
    body = comment.get("body") or ""
    match = SLASH_COMMAND_PATTERN.search(body)
    requester = (comment.get("user") or {}).get("login") or ""
    comment_id = (
        str(comment.get("id") or "")
        if event_name == "issue_comment"
        else ""
    )
    has_valid_pr_number = pr_number.isdigit() and int(pr_number) > 0
    matched = (
        is_pr
        and has_valid_pr_number
        and bool(match)
        and not is_automation_user(comment.get("user"))
    )
    return matched, pr_number, requester, comment_id


def main() -> None:
    event = load_event()
    github_event_name = optional_env("GITHUB_EVENT_NAME")

    should_review = False
    pr_number = ""
    trigger_source = github_event_name
    requester = optional_env("GITHUB_ACTOR")
    comment_id = ""
    is_explicit_invocation = False

    if github_event_name == "workflow_dispatch":
        candidate = optional_env("DISPATCH_PR_NUMBER")
        if candidate.isdigit() and int(candidate) > 0:
            should_review = True
            pr_number = candidate
    elif github_event_name in {"issue_comment", "pull_request_review_comment"}:
        matched, candidate_pr, candidate_requester, candidate_comment_id = (
            _resolve_comment_match(event, github_event_name)
        )
        if candidate_requester:
            requester = candidate_requester
        comment_id = candidate_comment_id
        if matched:
            should_review = True
            pr_number = candidate_pr
            is_explicit_invocation = True

    # Cap the number of explicit ``/oz-review`` invocations the workflow
    # acts on per PR so a single PR cannot pull the agent into an
    # arbitrarily long re-review loop. We only enforce the cap when the
    # current event is itself an explicit slash-command invocation; the
    # automatic ``pull_request_target`` review path is handled by
    # ``review-pull-request.yml`` and does not flow through this script.
    if should_review and is_explicit_invocation and pr_number:
        token = optional_env("GH_TOKEN") or optional_env("GITHUB_TOKEN")
        repo_full_name = optional_env("GITHUB_REPOSITORY") or repo_slug()
        if token and repo_full_name:
            try:
                with closing(Github(auth=Auth.Token(token))) as client:
                    invocation_count = _count_explicit_invocations(
                        client, repo_full_name, int(pr_number)
                    )
            except Exception:
                # Fail open: if the throttle lookup itself fails for any
                # reason (transient API error, permissions issue, etc.)
                # we still honor the request rather than silently
                # dropping a legitimate review trigger.
                invocation_count = 0
            if invocation_count > MAX_EXPLICIT_INVOCATIONS_PER_PR:
                notice(
                    "Skipping /oz-review: this PR has reached the limit of "
                    f"{MAX_EXPLICIT_INVOCATIONS_PER_PR} explicit /oz-review "
                    "invocations."
                )
                should_review = False

    set_output("should_review", "true" if should_review else "false")
    set_output("pr_number", pr_number if should_review else "")
    set_output("trigger_source", trigger_source)
    set_output("requester", requester)
    set_output("comment_id", comment_id)
    if not should_review:
        notice("PR review orchestration skipped after context resolution.")


if __name__ == "__main__":
    main()
