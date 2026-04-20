from __future__ import annotations
from contextlib import closing
import logging

import json
from textwrap import dedent
from typing import Any
from github import Auth, Github
from github.GithubException import GithubException

from oz_workflows.actions import set_output
from oz_workflows.env import optional_env, repo_parts, repo_slug, require_env, workspace
from oz_workflows.helpers import (
    extract_issue_numbers_from_text,
    format_enforce_start_line,
    ORG_MEMBER_ASSOCIATIONS,
    POWERED_BY_SUFFIX,
    WorkflowProgressComment,
)
from oz_workflows.artifacts import poll_for_artifact
from oz_workflows.oz_client import build_agent_config, run_agent

logger = logging.getLogger(__name__)

# Maximum number of human reviewers to request from STAKEHOLDERS so we don't
# over-notify maintainers on a single PR.
_MAX_STAKEHOLDER_REVIEWERS = 3
# Verdict strings allowed on the agent's ``pr_review.json`` artifact. These
# map directly to GitHub's ``event`` parameter on the create-review endpoint
# (COMMENT is deliberately excluded so the agent is forced to make a call).
_ALLOWED_VERDICTS = {"APPROVE", "REQUEST_CHANGES"}


def _is_pr_author_org_member(pr: dict) -> bool:
    """Return True if the PR author is an organization member or owner."""
    association = pr.get("author_association", "") if isinstance(pr, dict) else getattr(pr, "author_association", "")
    return association in ORG_MEMBER_ASSOCIATIONS


def _normalize_reviewer_logins(
    candidates: Any,
    *,
    pr_author_login: str,
    limit: int = _MAX_STAKEHOLDER_REVIEWERS,
) -> list[str]:
    """Normalize and cap a list of recommended reviewer logins from the agent.

    Strips leading ``@`` characters, drops blanks and duplicates (preserving
    first-seen order), removes the PR author (GitHub rejects self-review
    requests), and caps the result at ``limit`` entries so we don't
    over-notify.
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


def _run_non_member_pr_review(
    github: Any,
    pr: Any,
    *,
    owner: str,
    repo: str,
    pr_number: int,
    changed_files: list[str],
    progress: WorkflowProgressComment,
) -> str:
    """Run the agent PR-review gate for a non-member PR and return the verdict.

    The agent is asked to review the PR diff, consult ``.github/STAKEHOLDERS``,
    and upload a ``pr_review.json`` artifact with fields ``verdict``,
    ``summary``, and ``recommended_reviewers``. This function then posts a
    real GitHub pull-request review and, when the verdict is APPROVE,
    requests reviews from the top matching stakeholders (capped at
    ``_MAX_STAKEHOLDER_REVIEWERS``).

    Returns the normalized verdict string (``"APPROVE"`` or
    ``"REQUEST_CHANGES"``) so callers can surface it as a workflow output.
    """
    pr_author_login = ""
    user = getattr(pr, "user", None)
    if user is not None:
        pr_author_login = str(getattr(user, "login", "") or "")

    prompt = dedent(
        f"""
        Review pull request #{pr_number} in repository {owner}/{repo}.

        Pull Request Context:
        - Title: {pr.title}
        - Body: {pr.body or 'No description provided.'}
        - Base branch: {pr.base.ref}
        - Head branch: {pr.head.ref}
        - PR author: @{pr_author_login or 'unknown'}
        - Changed files:
        {chr(10).join(f"          - {filename}" for filename in changed_files) or "          - No changed files found."}

        You are the agent review gate for a non-member pull request. Your job is to
        decide whether this PR meets the quality bar well enough to route human
        reviewers, and to recommend which stakeholders should be asked to review
        when it does.

        Workflow:
        1. Check out the PR head branch and generate the diff against the base
           branch using a three-dot merge-base diff:
              ```
              git fetch origin {pr.head.ref}
              git checkout {pr.head.ref}
              git diff origin/{pr.base.ref}...HEAD
              ```
           Do NOT use FETCH_HEAD — always reference the named branch.
        2. Review the changed files and PR description for correctness, style,
           test coverage, and obvious security concerns.
        3. Decide a verdict of exactly ``APPROVE`` or ``REQUEST_CHANGES``. Never
           emit ``COMMENT``. Prefer ``REQUEST_CHANGES`` when the PR clearly
           needs rework before a human should spend time reviewing it.
        4. Read ``.github/STAKEHOLDERS`` from the base branch of the repository
           (CODEOWNERS-style syntax; later rules take precedence, most specific
           pattern wins over catch-all rules).
        5. For each changed file, find the most specific matching stakeholder
           rule and collect the owners listed on that rule. De-duplicate across
           files, prefer more specific rules over catch-all rules, and cap the
           final list at {_MAX_STAKEHOLDER_REVIEWERS} GitHub logins. Exclude the PR author
           (@{pr_author_login or 'unknown'}) from the list — GitHub rejects
           self-review requests. Strip any leading ``@`` from each login.
        6. When the verdict is ``REQUEST_CHANGES``, set ``recommended_reviewers``
           to an empty list. Only populate ``recommended_reviewers`` when the
           verdict is ``APPROVE``.

        Output requirements:
        - Produce JSON with exactly this shape:
          {{"verdict": "APPROVE" | "REQUEST_CHANGES", "summary": string, "recommended_reviewers": [string, ...]}}
        - ``summary`` must be a short markdown-friendly review summary that will
          be posted as the body of the GitHub pull-request review. Mention the
          verdict and the main reasons.
        - Do not post the GitHub review yourself — the workflow will call the
          create-review and request-reviewers endpoints based on this artifact.
        - Validate the JSON with ``jq``.
        - After validating the JSON, upload it as an artifact via
          ``oz-dev artifact upload pr_review.json``. The subcommand is
          ``artifact`` (singular); do not use ``artifacts``.
        """
    ).strip()

    config = build_agent_config(
        config_name="enforce-pr-issue-state-review",
        workspace=workspace(),
    )
    run = run_agent(
        prompt=prompt,
        skill_name=None,
        title=f"Agent review gate for PR #{pr_number}",
        config=config,
    )
    result = poll_for_artifact(run.run_id, filename="pr_review.json")

    verdict_raw = str(result.get("verdict") or "").strip().upper()
    if verdict_raw not in _ALLOWED_VERDICTS:
        raise RuntimeError(
            f"Oz agent returned an invalid verdict {verdict_raw!r}; expected one of {sorted(_ALLOWED_VERDICTS)}"
        )
    summary = str(result.get("summary") or "").strip()
    if not summary:
        raise RuntimeError("Oz agent returned an empty review summary")
    recommended_reviewers = _normalize_reviewer_logins(
        result.get("recommended_reviewers"),
        pr_author_login=pr_author_login,
    )

    review_body = f"{summary}\n\n{POWERED_BY_SUFFIX}"
    try:
        pr.create_review(body=review_body, event=verdict_raw)
    except GithubException:
        logger.exception(
            "Failed to post agent review on PR #%s in %s/%s", pr_number, owner, repo
        )
        raise

    if verdict_raw == "APPROVE" and recommended_reviewers:
        try:
            pr.create_review_request(reviewers=recommended_reviewers)
        except GithubException:
            # Requesting reviewers is best-effort — an invalid login or a
            # maintainer who cannot review this repository should not fail
            # the whole enforcement workflow after the review itself has
            # been posted.
            logger.exception(
                "Failed to request reviewers %s for PR #%s in %s/%s",
                recommended_reviewers,
                pr_number,
                owner,
                repo,
            )

    verdict_human = "approved" if verdict_raw == "APPROVE" else "requested changes on"
    sections = [f"I {verdict_human} this pull request based on an automated review gate."]
    if verdict_raw == "APPROVE" and recommended_reviewers:
        reviewer_mentions = ", ".join(f"@{login}" for login in recommended_reviewers)
        sections.append(f"I requested human review from: {reviewer_mentions}.")
    elif verdict_raw == "APPROVE":
        sections.append(
            "I did not find a matching stakeholder for the changed files, so no human reviewers were requested."
        )
    progress.complete("\n\n".join(sections))
    return verdict_raw


def main() -> None:
    owner, repo = repo_parts()
    pr_number = int(require_env("PR_NUMBER"))
    requester = optional_env("REQUESTER")
    with closing(Github(auth=Auth.Token(require_env("GH_TOKEN")))) as client:
        github = client.get_repo(repo_slug())
        pr = github.get_pull(pr_number)
        if pr.state != "open":
            set_output("allow_review", "false")
            set_output("agent_verdict", "")
            return
        if _is_pr_author_org_member(pr):
            set_output("allow_review", "true")
            set_output("agent_verdict", "")
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
        # Markdown-only (spec) PRs are not enforced against a
        # ``ready-to-spec`` issue label. Spec PRs are free-form and do
        # not require a matching ready issue to be reviewable.
        if not has_code_changes:
            progress.cleanup()
            set_output("allow_review", "true")
            set_output("agent_verdict", "")
            return
        change_kind = "implementation"
        required_label = "ready-to-implement"
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
            if required_label in labels:
                progress.cleanup()
                verdict = _run_non_member_pr_review(
                    github,
                    pr,
                    owner=owner,
                    repo=repo,
                    pr_number=pr_number,
                    changed_files=changed_files,
                    progress=progress,
                )
                set_output("allow_review", "true")
                set_output("agent_verdict", verdict)
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
            set_output("agent_verdict", "")
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
            verdict = _run_non_member_pr_review(
                github,
                pr,
                owner=owner,
                repo=repo,
                pr_number=pr_number,
                changed_files=changed_files,
                progress=progress,
            )
            set_output("allow_review", "true")
            set_output("agent_verdict", verdict)
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
        set_output("agent_verdict", "")


def _capture_session_link(session_links: list[str], run: object) -> None:
    session_link = (getattr(run, "session_link", None) or "").strip()
    if session_link and (not session_links or session_links[-1] != session_link):
        session_links.append(session_link)


if __name__ == "__main__":
    main()
