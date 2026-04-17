from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from github import Github
from github.GithubException import UnknownObjectException
from github.PullRequest import PullRequest
from github.Repository import Repository

from .env import optional_env


# Author associations that indicate organization membership.
ORG_MEMBER_ASSOCIATIONS: set[str] = {"COLLABORATOR", "MEMBER", "OWNER"}

ISSUE_PATTERN = re.compile(r"(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?|refs?|implements?|issue)\s*:?\s+#(\d+)", re.IGNORECASE)


def parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def get_field(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def get_login(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("login") or "")
    return str(getattr(item, "login", "") or "")


def is_automation_user(user: Any) -> bool:
    """Return whether *user* is an automation account that should not trigger workflows."""
    login = get_login(user).strip().lower()
    user_type = str(get_field(user, "type", "") or "").strip().lower()
    return (
        user_type == "bot"
        or (bool(login) and login.endswith("[bot]"))
    )


def get_timestamp_text(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return str(value or "")


def get_label_name(label: Any) -> str:
    if isinstance(label, str):
        return label
    return str(get_field(label, "name", "") or "")


def format_issue_comments_for_prompt(
    comments: list[Any],
    *,
    metadata_prefix: str,
    exclude_comment_id: int | None = None,
) -> str:
    """Format human-visible issue comments for prompt context."""
    selected = [
        comment
        for comment in comments
        if int(get_field(comment, "id") or 0) != exclude_comment_id
        and metadata_prefix not in str(get_field(comment, "body") or "")
    ]
    if not selected:
        return "- None"
    formatted = []
    for comment in selected:
        user = get_login(get_field(comment, "user")) or "unknown"
        association = get_field(comment, "author_association") or "NONE"
        body = str(get_field(comment, "body") or "").strip() or "(no body)"
        formatted.append(
            f"- @{user} [{association}] ({get_timestamp_text(get_field(comment, 'created_at'))}): {body}"
        )
    return "\n".join(formatted)


def _list_issue_comments(
    github: Repository | Any,
    owner: str,
    repo: str,
    issue_number: int,
) -> list[Any]:
    if hasattr(github, "get_issue"):
        return list(github.get_issue(issue_number).get_comments())
    return list(github.list_issue_comments(owner, repo, issue_number))


def _list_issue_events(
    github: Repository | Any,
    owner: str,
    repo: str,
    issue_number: int,
) -> list[Any]:
    if hasattr(github, "get_issue"):
        return list(github.get_issue(issue_number).get_events())
    return list(github.list_issue_events(owner, repo, issue_number))


def _get_issue_comment(
    github: Repository | Any,
    owner: str,
    repo: str,
    comment_id: int,
    *,
    issue_number: int,
) -> Any:
    if hasattr(github, "get_issue"):
        return github.get_issue(issue_number).get_comment(comment_id)
    return github.get_comment(owner, repo, comment_id)


def _create_issue_comment(
    github: Repository | Any,
    owner: str,
    repo: str,
    issue_number: int,
    body: str,
) -> Any:
    if hasattr(github, "get_issue"):
        return github.get_issue(issue_number).create_comment(body)
    return github.create_comment(owner, repo, issue_number, body)


def _update_issue_comment(
    github: Repository | Any,
    owner: str,
    repo: str,
    issue_number: int,
    comment_id: int,
    body: str,
) -> Any:
    if hasattr(github, "get_issue"):
        comment = github.get_issue(issue_number).get_comment(comment_id)
        comment.edit(body)
        return comment
    return github.update_comment(owner, repo, comment_id, body)


def _delete_issue_comment(
    github: Repository | Any,
    owner: str,
    repo: str,
    issue_number: int,
    comment_id: int,
) -> None:
    if hasattr(github, "get_issue"):
        github.get_issue(issue_number).get_comment(comment_id).delete()
        return
    github.delete_comment(owner, repo, comment_id)


def _filter_review_comments_in_thread(
    all_review_comments: list[Any],
    trigger_comment_id: int,
) -> list[Any]:
    """Return review comments that belong to the thread containing *trigger_comment_id*.

    GitHub's REST API (and therefore PyGitHub) does not expose an endpoint for
    fetching a single review thread by comment id; ``pullRequestReviewThread``
    exists only in the GraphQL API. ``PullRequest.get_review_comment(id)``
    returns just the one comment, and ``get_single_review_comments(review_id)``
    scopes to a ``PullRequestReview`` batch rather than a reply thread, so we
    have to filter client-side.

    GitHub flat-threads review replies: every reply's ``in_reply_to_id`` points
    directly at the thread root regardless of which comment was quoted, so the
    root is either the triggering comment itself or the comment its
    ``in_reply_to_id`` refers to.
    """
    by_id: dict[int, Any] = {int(get_field(c, "id")): c for c in all_review_comments}
    trigger = by_id.get(trigger_comment_id)
    parent = get_field(trigger, "in_reply_to_id") if trigger is not None else None
    root_id = int(parent) if parent is not None else trigger_comment_id
    return [
        c
        for c in all_review_comments
        if int(get_field(c, "id")) == root_id or get_field(c, "in_reply_to_id") == root_id
    ]


def org_member_comments_text(
    comments: list[Any],
    *,
    exclude_comment_id: int | None = None,
) -> str:
    selected = [
        comment
        for comment in comments
        if get_field(comment, "author_association") in ORG_MEMBER_ASSOCIATIONS
        and int(get_field(comment, "id") or 0) != exclude_comment_id
    ]
    if not selected:
        return ""
    return "\n".join(
        f"- {get_login(get_field(comment, 'user')) or 'unknown'} ({get_timestamp_text(get_field(comment, 'created_at'))}): {get_field(comment, 'body') or ''}"
        for comment in selected
    )


def triggering_comment_prompt_text(event_payload: dict[str, Any]) -> str:
    comment = event_payload.get("comment")
    if not isinstance(comment, dict):
        return ""
    body = str(comment.get("body") or "").strip()
    if not body:
        return ""
    author_login = (comment.get("user") or {}).get("login") or (event_payload.get("sender") or {}).get("login") or "unknown"
    return f"@{author_login} commented:\n{body}"


def comment_metadata(
    workflow: str,
    issue_number: int,
    *,
    run_id: str = "",
    oz_run_id: str = "",
    github_run_id: str = "",
) -> str:
    payload: dict[str, Any] = {
        "type": "issue-status",
        "workflow": workflow,
        "issue": issue_number,
    }
    if run_id:
        payload["run_id"] = run_id
    if github_run_id:
        payload["github_run_id"] = github_run_id
    if oz_run_id:
        payload["oz_run_id"] = oz_run_id
    return f"<!-- oz-agent-metadata: {json.dumps(payload, separators=(',', ':'))} -->"


def _workflow_metadata_prefix(workflow: str, issue_number: int) -> str:
    """Return the stable metadata prefix shared by all runs of the same workflow on an issue."""
    return f'<!-- oz-agent-metadata: {{"type":"issue-status","workflow":"{workflow}","issue":{issue_number}'


def _strip_workflow_metadata(body: str, workflow_prefix: str) -> str:
    """Remove any metadata marker in *body* whose prefix matches *workflow_prefix*.

    The progress comment metadata marker is rebuilt mid-run when additional
    identifiers (e.g. the Oz run id) become available. This helper strips any
    existing marker for the same workflow+issue so callers can rebuild the
    body with the current metadata.
    """
    if not body or not workflow_prefix:
        return body
    start = body.find(workflow_prefix)
    if start == -1:
        return body
    end = body.find("-->", start)
    if end == -1:
        return body
    end += len("-->")
    return (body[:start] + body[end:]).strip()


def split_comment_body(body: str, metadata: str) -> tuple[str, str]:
    if metadata and metadata in body:
        content, _, _ = body.partition(metadata)
        return content.strip(), metadata
    return body.strip(), metadata


def build_comment_body(content: str, metadata: str) -> str:
    content = content.strip()
    if metadata:
        if content:
            return f"{content}\n\n{metadata}"
        return metadata
    return content

_PROGRESS_LINK_PREFIXES = (
    "Sharing session at: ",
    "View the Oz conversation: ",
)


def _workflow_run_url() -> str:
    """Build the GitHub Actions workflow run URL from environment variables."""
    server_url = optional_env("GITHUB_SERVER_URL") or "https://github.com"
    repository = optional_env("GITHUB_REPOSITORY")
    run_id = optional_env("GITHUB_RUN_ID")
    if not repository or not run_id:
        return ""
    return f"{server_url}/{repository}/actions/runs/{run_id}"


def _format_progress_link_section(session_link: str) -> str:
    normalized_link = session_link.strip()
    if "/conversation/" in normalized_link:
        return f"View the Oz conversation: {normalized_link}"
    return f"Sharing session at: {normalized_link}"


def _format_triage_session_link(session_link: str) -> str:
    """Format a session link as a markdown link for the triage workflow."""
    normalized_link = session_link.strip()
    return f"[the triage session on Warp]({normalized_link})"


def append_comment_sections(existing_body: str, metadata: str, sections: list[str]) -> str:
    content, metadata = split_comment_body(existing_body, metadata)
    normalized_sections = [section.strip() for section in sections if section and section.strip()]
    if not content:
        return build_comment_body("\n\n".join(normalized_sections), metadata)
    updated_sections = [section.strip() for section in content.split("\n\n") if section.strip()]
    for section in normalized_sections:
        if section.startswith(_PROGRESS_LINK_PREFIXES):
            updated_sections = [
                existing_section
                for existing_section in updated_sections
                if not existing_section.startswith(_PROGRESS_LINK_PREFIXES)
            ]
            updated_sections.append(section)
            continue
        if section not in updated_sections:
            updated_sections.append(section)
    return build_comment_body("\n\n".join(updated_sections), metadata)


def resolve_oz_assigner_login(
    github: Repository | Any,
    owner: str,
    repo: str,
    issue_number: int,
    *,
    event_payload: dict[str, Any],
) -> str:
    if (
        event_payload.get("action") == "assigned"
        and (event_payload.get("assignee") or {}).get("login") == "oz-agent"
    ):
        return (event_payload.get("sender") or {}).get("login") or ""

    events = _list_issue_events(github, owner, repo, issue_number)
    matching_events = [
        event
        for event in events
        if get_field(event, "event") == "assigned"
        and get_login(get_field(event, "assignee")) == "oz-agent"
    ]
    if not matching_events:
        return (event_payload.get("sender") or {}).get("login") or ""

    matching_events.sort(
        key=lambda event: (
            get_field(event, "created_at").astimezone(timezone.utc)
            if isinstance(get_field(event, "created_at"), datetime)
            else parse_datetime(str(get_field(event, "created_at") or "1970-01-01T00:00:00Z"))
        ),
        reverse=True,
    )
    return get_login(get_field(matching_events[0], "actor"))


def resolve_progress_requester_login(
    github: Repository | Any,
    owner: str,
    repo: str,
    issue_number: int,
    *,
    event_payload: dict[str, Any] | None = None,
    requester_login: str = "",
) -> str:
    normalized_requester = requester_login.strip().removeprefix("@")
    if normalized_requester:
        return normalized_requester
    payload = event_payload or {}
    comment = payload.get("comment")
    if isinstance(comment, dict):
        comment_author = (comment.get("user") or {}).get("login") or ""
        if comment_author:
            return comment_author
    sender_login = (payload.get("sender") or {}).get("login") or ""
    if sender_login:
        return sender_login
    return resolve_oz_assigner_login(
        github,
        owner,
        repo,
        issue_number,
        event_payload=payload,
    )


class WorkflowProgressComment:
    def __init__(
        self,
        github: Repository | Any,
        owner: str,
        repo: str,
        issue_number: int,
        *,
        workflow: str,
        event_payload: dict[str, Any] | None = None,
        requester_login: str = "",
        review_reply_target: tuple[object, int] | None = None,
    ) -> None:
        self.github = github
        self.owner = owner
        self.repo = repo
        self.issue_number = issue_number
        self.workflow = workflow
        self.event_payload = event_payload or {}
        self.requester_login = requester_login
        self.run_id = uuid.uuid4().hex
        self.github_run_id = optional_env("GITHUB_RUN_ID")
        self.oz_run_id: str = ""
        self.metadata = comment_metadata(
            workflow,
            issue_number,
            run_id=self.run_id,
            github_run_id=self.github_run_id,
        )
        self._workflow_prefix = _workflow_metadata_prefix(workflow, issue_number)
        self.comment_id: int | None = None
        self.session_link: str = ""
        # When set, progress updates are posted/edited as review-comment replies
        # within the triggering review thread instead of as PR-level issue
        # comments. The tuple is (pull_request, trigger_review_comment_id).
        self.review_reply_target = review_reply_target

    def start(self, status_line: str) -> None:
        self._append_sections([status_line])

    def record_session_link(self, session_link: str) -> None:
        normalized = session_link.strip()
        if not normalized:
            return
        if normalized == self.session_link:
            # The session link hasn't changed since the last successful
            # update, so there is nothing new to post.
            return
        try:
            self._append_sections([_format_progress_link_section(normalized)])
        except Exception:
            # Recording the session link happens from the run-agent poll
            # loop. A transient GitHub API failure here should not abort
            # the entire workflow run; try again on the next poll.
            return
        self.session_link = normalized

    def record_oz_run_id(self, oz_run_id: str) -> None:
        """Record the Oz agent run id and refresh the metadata marker.

        When the Oz run id becomes known mid-run (after ``client.agent.run``
        returns its run id), fold it into the comment metadata so the marker
        on the GitHub comment captures the Oz run id alongside the GitHub
        Actions run id.
        """
        normalized = (oz_run_id or "").strip()
        if not normalized or normalized == self.oz_run_id:
            return
        try:
            self.oz_run_id = normalized
            self.metadata = comment_metadata(
                self.workflow,
                self.issue_number,
                run_id=self.run_id,
                oz_run_id=self.oz_run_id,
                github_run_id=self.github_run_id,
            )
            existing = self._get_or_find_existing_comment()
            if existing is None:
                return
            existing_body = str(get_field(existing, "body") or "")
            content = _strip_workflow_metadata(existing_body, self._workflow_prefix)
            new_body = build_comment_body(content, self.metadata)
            if new_body == existing_body:
                return
            self._update_comment(int(get_field(existing, "id")), new_body)
        except Exception:
            # Refreshing the metadata marker is best-effort; a transient
            # GitHub API failure should not abort the workflow run.
            return

    def complete(self, status_line: str) -> None:
        self._append_sections([status_line])

    def report_error(self) -> None:
        """Update the progress comment to indicate a workflow failure."""
        try:
            run_url = _workflow_run_url()
            if run_url:
                message = (
                    "Oz ran into an unexpected error while working on this. "
                    f"You can view the [workflow run]({run_url}) for more details."
                )
            else:
                message = "Oz ran into an unexpected error while working on this."
            sections = [message]
            if self.session_link:
                sections.append(_format_progress_link_section(self.session_link))
            self.replace_body("\n\n".join(sections))
        except Exception:
            pass

    def replace_body(self, content: str) -> None:
        """Replace the full comment body, preserving the metadata marker."""
        requester = resolve_progress_requester_login(
            self.github,
            self.owner,
            self.repo,
            self.issue_number,
            event_payload=self.event_payload,
            requester_login=self.requester_login,
        )
        sections: list[str] = []
        if requester:
            sections.append(f"@{requester}")
        sections.append(content)
        body = build_comment_body("\n\n".join(sections), self.metadata)
        existing = self._get_or_find_existing_comment()
        if existing is None:
            created = self._create_comment(body)
            self.comment_id = int(get_field(created, "id"))
            return
        self._update_comment(int(get_field(existing, "id")), body)
        self.comment_id = int(get_field(existing, "id"))

    def cleanup(self) -> None:
        """Delete the progress comment if one exists from this or a previous run."""
        if self.comment_id is not None:
            try:
                self._delete_comment(self.comment_id)
            except Exception:
                pass
            self.comment_id = None
            return
        while True:
            existing = self._find_any_workflow_comment()
            if existing is None:
                break
            try:
                self._delete_comment(int(get_field(existing, "id")))
            except Exception:
                break
        self.comment_id = None

    def _append_sections(self, sections: list[str]) -> None:
        normalized_sections = [section.strip() for section in sections if section and section.strip()]
        requester = resolve_progress_requester_login(
            self.github,
            self.owner,
            self.repo,
            self.issue_number,
            event_payload=self.event_payload,
            requester_login=self.requester_login,
        )
        if requester:
            normalized_sections.insert(0, f"@{requester}")
        if not normalized_sections:
            return
        existing = self._get_or_find_existing_comment()
        if existing is None:
            created = self._create_comment(
                build_comment_body("\n\n".join(normalized_sections), self.metadata),
            )
            created_id = int(get_field(created, "id"))
            self._dedupe_duplicate_created_comments(keep_id=created_id)
            self.comment_id = created_id
            return
        updated_body = append_comment_sections(str(get_field(existing, "body") or ""), self.metadata, normalized_sections)
        self._update_comment(int(get_field(existing, "id")), updated_body)
        self.comment_id = int(get_field(existing, "id"))

    def _dedupe_duplicate_created_comments(self, *, keep_id: int) -> None:
        """Delete any stray comments matching this run's metadata marker.

        PyGitHub's default retry policy retries POST requests on 5xx
        responses. When GitHub returns a 5xx but actually processed the
        create-comment request server-side, those retries produce duplicate
        comments that all share this run's unique ``run_id`` metadata
        marker. Remove them here so the progress comment stays as a single
        entry; best-effort, since the duplicates are cosmetic.
        """
        try:
            comments = self._list_comments()
        except Exception:
            return
        for comment in comments:
            comment_id = int(get_field(comment, "id") or 0)
            if comment_id == keep_id or comment_id <= 0:
                continue
            body = get_field(comment, "body")
            if not isinstance(body, str) or self.metadata not in body:
                continue
            try:
                self._delete_comment(comment_id)
            except Exception:
                # Deleting duplicates is best-effort; leave extras in place
                # rather than letting cleanup errors abort the workflow.
                continue

    def _find_any_workflow_comment(self) -> Any | None:
        """Find any progress comment for this workflow on this issue, regardless of run."""
        comments = self._list_comments()
        return next(
            (
                comment
                for comment in comments
                if isinstance(get_field(comment, "body"), str)
                and self._workflow_prefix in (get_field(comment, "body") or "")
            ),
            None,
        )

    def _get_or_find_existing_comment(self) -> Any | None:
        if self.comment_id is not None:
            try:
                return self._get_comment(self.comment_id)
            except UnknownObjectException:
                self.comment_id = None
        comments = self._list_comments()
        existing = next(
            (
                comment
                for comment in comments
                if isinstance(get_field(comment, "body"), str) and self.metadata in str(get_field(comment, "body") or "")
            ),
            None,
        )
        if existing:
            self.comment_id = int(get_field(existing, "id"))
        return existing

    def _list_comments(self) -> list[Any]:
        """List candidate progress comments for the current scope."""
        if self.review_reply_target is not None:
            pr_obj, trigger_comment_id = self.review_reply_target
            pr = cast(PullRequest, pr_obj)
            all_comments = list(pr.get_review_comments())
            return _filter_review_comments_in_thread(all_comments, trigger_comment_id)
        return _list_issue_comments(self.github, self.owner, self.repo, self.issue_number)

    def _create_comment(self, body: str) -> Any:
        if self.review_reply_target is not None:
            pr_obj, trigger_comment_id = self.review_reply_target
            pr = cast(PullRequest, pr_obj)
            return pr.create_review_comment_reply(trigger_comment_id, body)
        return _create_issue_comment(
            self.github,
            self.owner,
            self.repo,
            self.issue_number,
            body,
        )

    def _get_comment(self, comment_id: int) -> Any:
        if self.review_reply_target is not None:
            pr_obj, _ = self.review_reply_target
            pr = cast(PullRequest, pr_obj)
            return pr.get_review_comment(comment_id)
        return _get_issue_comment(
            self.github,
            self.owner,
            self.repo,
            comment_id,
            issue_number=self.issue_number,
        )

    def _update_comment(self, comment_id: int, body: str) -> Any:
        if self.review_reply_target is not None:
            pr_obj, _ = self.review_reply_target
            pr = cast(PullRequest, pr_obj)
            comment = pr.get_review_comment(comment_id)
            comment.edit(body)
            return comment
        return _update_issue_comment(
            self.github,
            self.owner,
            self.repo,
            self.issue_number,
            comment_id,
            body,
        )

    def _delete_comment(self, comment_id: int) -> None:
        if self.review_reply_target is not None:
            pr_obj, _ = self.review_reply_target
            pr = cast(PullRequest, pr_obj)
            pr.get_review_comment(comment_id).delete()
            return
        _delete_issue_comment(
            self.github,
            self.owner,
            self.repo,
            self.issue_number,
            comment_id,
        )


def record_run_session_link(progress: WorkflowProgressComment, run: object) -> None:
    """Record the current Oz session link and run id on a progress comment when available."""
    oz_run_id = getattr(run, "run_id", None) or ""
    if oz_run_id:
        progress.record_oz_run_id(str(oz_run_id))
    session_link = getattr(run, "session_link", None) or ""
    progress.record_session_link(session_link)


# Maps issue label names to conventional commit type prefixes.
_LABEL_TO_COMMIT_TYPE: dict[str, str] = {
    "bug": "fix",
    "enhancement": "feat",
    "feature": "feat",
    "documentation": "docs",
    "refactor": "refactor",
    "chore": "chore",
    "performance": "perf",
    "test": "test",
    "ci": "ci",
}


def conventional_commit_prefix(labels: list[Any], *, default: str = "feat") -> str:
    """Derive a conventional-commit type prefix from issue labels.

    Returns the first matching prefix found by scanning *labels* against a
    known mapping, or *default* when no label matches.
    """
    for label in labels:
        name = get_label_name(label).lower()
        if name in _LABEL_TO_COMMIT_TYPE:
            return _LABEL_TO_COMMIT_TYPE[name]
    return default


# Accounts created on or after this date use the ``ID+login`` noreply format.
# See https://docs.github.com/en/account-and-profile/reference/email-addresses-reference#your-noreply-email-address
_NOREPLY_ID_CUTOFF = datetime(2017, 7, 18, tzinfo=timezone.utc)
_OZ_COMMIT_AUTHOR_NAME = "Oz"
_OZ_COMMIT_AUTHOR_EMAIL = "oz-agent@warp.dev"


def _noreply_email(login: str, user_id: int | None, created_at: datetime | str | None) -> str:
    """Build the GitHub noreply email for *login*."""
    if created_at is not None and user_id is not None:
        try:
            parsed_created_at = (
                created_at.astimezone(timezone.utc)
                if isinstance(created_at, datetime)
                else parse_datetime(created_at)
            )
            if parsed_created_at >= _NOREPLY_ID_CUTOFF:
                return f"{user_id}+{login}@users.noreply.github.com"
        except (ValueError, TypeError):
            pass
    return f"{login}@users.noreply.github.com"


def resolve_coauthor_line(
    github: Github | Any,
    event_payload: dict[str, Any],
) -> str:
    """Resolve a ``Co-Authored-By`` line from the event that triggered the workflow."""
    comment = event_payload.get("comment")
    login: str = ""
    if isinstance(comment, dict):
        login = (comment.get("user") or {}).get("login") or ""
    if not login:
        login = (event_payload.get("sender") or {}).get("login") or ""
    if not login:
        return ""

    try:
        user = github.get_user(login)
    except Exception:
        user = None

    name = (get_field(user, "name") if user else None) or login
    user_id = get_field(user, "id") if user else None
    created_at = get_field(user, "created_at") if user else None
    email = _noreply_email(login, user_id, created_at)
    return f"Co-Authored-By: {name} <{email}>"


def coauthor_prompt_lines(coauthor_line: str) -> str:
    """Return prompt directive lines for commit attribution."""
    lines = [
        f"- Before creating any commit, configure the local git author and committer as `{_OZ_COMMIT_AUTHOR_NAME} <{_OZ_COMMIT_AUTHOR_EMAIL}>`.",
        f"- Run `git config user.name \"{_OZ_COMMIT_AUTHOR_NAME}\"` and `git config user.email \"{_OZ_COMMIT_AUTHOR_EMAIL}\"` before committing.",
        "- Do not derive the git author or committer from the triggering issue, PR, comment, sender, or authenticated GitHub user.",
        "- Do not include issue number references (e.g. `(#N)`, `Refs #N`) in commit messages. The issue is already linked in the PR.",
    ]
    if coauthor_line:
        lines.extend(
            [
                f"- Include the following co-author attribution at the end of every commit message: {coauthor_line}",
                "- Do not attempt to resolve the co-author identity yourself (e.g. via GET /user). Use exactly the line provided above.",
            ]
        )
    else:
        lines.append("- Do not include any Co-Authored-By lines in commit messages.")
    return "\n".join(lines)

def spec_directory_name(issue_number: int) -> str:
    return f"GH{issue_number}"


def spec_directory_path(issue_number: int) -> str:
    return f"specs/{spec_directory_name(issue_number)}"


def build_spec_preview_section(owner: str, repo: str, branch_name: str, issue_number: int) -> str:
    spec_dir = spec_directory_path(issue_number)
    product_path = f"{spec_dir}/product.md"
    tech_path = f"{spec_dir}/tech.md"
    product_url = f"https://github.com/{owner}/{repo}/blob/{branch_name}/{product_path}"
    tech_url = f"https://github.com/{owner}/{repo}/blob/{branch_name}/{tech_path}"
    return (
        f"Preview generated specs:\n"
        f"- Product spec: [{product_path}]({product_url})\n"
        f"- Tech spec: [{tech_path}]({tech_url})"
    )


def _summarize_commits(commits: list[Any]) -> str:
    """Build a bulleted summary from a list of GitHub commit objects."""
    lines: list[str] = []
    max_lines = 15
    for commit in commits:
        if isinstance(commit, dict):
            msg = (get_field(commit, "commit") or {}).get("message") or ""
        else:
            msg = getattr(get_field(commit, "commit"), "message", "") or ""
        first_line = msg.split("\n", 1)[0].strip()
        if not first_line:
            continue
        if first_line.startswith("Merge "):
            continue
        lines.append(f"- {first_line}")
    if len(lines) > max_lines:
        lines = lines[:max_lines] + [f"- … and {len(lines) - max_lines} more commits"]
    return "\n".join(lines)


def build_pr_body(
    github: Repository | Any,
    owner: str,
    repo: str,
    *,
    issue_number: int,
    head: str,
    base: str,
    session_link: str = "",
    closing_keyword: str = "Closes",
) -> str:
    """Build a descriptive PR body with an optional GitHub closing keyword."""
    sections: list[str] = []

    if closing_keyword:
        sections.append(f"{closing_keyword} #{issue_number}")
    else:
        sections.append(f"Related issue: #{issue_number}")

    commits: list[Any] = []
    if hasattr(github, "compare"):
        try:
            comparison = github.compare(base, head)
        except UnknownObjectException:
            comparison = None
        if comparison is not None:
            commits = list(getattr(comparison, "commits", []) or [])
    else:
        comparison = github.compare_commits(owner, repo, base, head)
        commits = (comparison or {}).get("commits") or []
    summary = _summarize_commits(commits)
    if summary:
        sections.append(f"## Changes\n{summary}")

    if session_link:
        sections.append(f"Session: {session_link}")

    return "\n\n".join(sections)


def build_next_steps_section(steps: list[str]) -> str:
    normalized_steps = [step.strip() for step in steps if step and step.strip()]
    if not normalized_steps:
        return ""
    return "Next steps:\n" + "\n".join(f"- {step}" for step in normalized_steps)


def branch_exists(github: Repository | Any, owner: str, repo: str, branch: str) -> bool:
    if hasattr(github, "get_git_ref"):
        try:
            github.get_git_ref(f"heads/{branch}")
            return True
        except UnknownObjectException:
            return False
    return github.get_ref(owner, repo, f"heads/{branch}") is not None


def branch_updated_since(
    github: Repository | Any,
    owner: str,
    repo: str,
    branch: str,
    *,
    created_after: datetime,
) -> bool:
    if hasattr(github, "get_branch"):
        try:
            branch_ref = github.get_branch(branch)
        except UnknownObjectException:
            return False
        commit = get_field(branch_ref, "commit")
        commit_data = get_field(commit, "commit")
        committer = get_field(commit_data, "committer")
        commit_date = get_field(committer, "date")
        if not isinstance(commit_date, datetime):
            return False
        return commit_date.astimezone(timezone.utc) >= created_after

    ref = github.get_ref(owner, repo, f"heads/{branch}")
    if not ref:
        return False
    sha = ref.get("object", {}).get("sha")
    if not sha:
        return False
    commit = github.get_commit(owner, repo, sha)
    committed_at = parse_datetime(commit["commit"]["committer"]["date"])
    return committed_at >= created_after


def find_matching_spec_prs(
    github: Repository,
    owner: str,
    repo: str,
    issue_number: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    expected_spec_branch = f"oz-agent/spec-issue-{issue_number}"
    matching = list(github.get_pulls(state="all", head=f"{owner}:{expected_spec_branch}"))
    approved: list[dict[str, Any]] = []
    unapproved: list[dict[str, Any]] = []
    for pr in matching:
        labels = [get_label_name(label) for label in pr.as_issue().labels]
        files = list(pr.get_files())
        spec_files = [
            str(file.filename)
            for file in files
            if str(file.filename).startswith("specs/")
        ]
        entry = {
            "number": pr.number,
            "url": pr.html_url,
            "updated_at": get_timestamp_text(pr.updated_at),
            "head_ref_name": pr.head.ref,
            "head_repo_full_name": pr.head.repo.full_name if pr.head.repo else "",
            "spec_files": spec_files,
        }
        if "plan-approved" in labels:
            approved.append(entry)
        else:
            unapproved.append(entry)
    approved.sort(key=lambda item: parse_datetime(item["updated_at"]), reverse=True)
    unapproved.sort(key=lambda item: parse_datetime(item["updated_at"]), reverse=True)
    return approved, unapproved


def read_local_spec_files(workspace: Path, issue_number: int) -> list[tuple[str, str]]:
    spec_dir_name = spec_directory_name(issue_number)
    spec_dir = workspace / "specs" / spec_dir_name
    results: list[tuple[str, str]] = []
    for name in ("product.md", "tech.md"):
        path = spec_dir / name
        if path.exists():
            rel = f"specs/{spec_dir_name}/{name}"
            results.append((rel, path.read_text(encoding="utf-8").strip()))
    return results


def resolve_spec_context_for_issue(
    github: Repository,
    owner: str,
    repo: str,
    issue_number: int,
    *,
    workspace: Path,
) -> dict[str, Any]:
    approved, unapproved = find_matching_spec_prs(github, owner, repo, issue_number)
    selected = approved[0] if approved else None
    local_specs = read_local_spec_files(workspace, issue_number)
    if selected and selected["head_repo_full_name"] != f"{owner}/{repo}":
        raise RuntimeError(
            f"Linked approved spec PR #{selected['number']} uses branch "
            f"{selected['head_repo_full_name']}:{selected['head_ref_name']}, which this workflow cannot push to."
        )

    spec_context_source = "approved-pr" if selected else "directory" if local_specs else ""
    spec_entries: list[dict[str, str]] = []
    if selected:
        for path in selected["spec_files"]:
            try:
                content_file = github.get_contents(path, ref=selected["head_ref_name"])
            except UnknownObjectException:
                continue
            if isinstance(content_file, list):
                continue
            spec_entries.append(
                {
                    "path": path,
                    "content": content_file.decoded_content.decode("utf-8").strip(),
                }
            )
    elif local_specs:
        for path, content in local_specs:
            spec_entries.append({"path": path, "content": content})

    return {
        "selected_spec_pr": selected,
        "approved_spec_prs": approved,
        "unapproved_spec_prs": unapproved,
        "spec_context_source": spec_context_source,
        "spec_entries": spec_entries,
    }


def _is_org_member(comment: Any) -> bool:
    return get_field(comment, "author_association") in ORG_MEMBER_ASSOCIATIONS


def _format_review_comment(comment: Any) -> str:
    login = get_login(get_field(comment, "user")) or "unknown"
    created = get_timestamp_text(get_field(comment, "created_at"))
    body = get_field(comment, "body") or ""
    path = get_field(comment, "path") or ""
    prefix = f"{path}: " if path else ""
    return f"- {prefix}{login} ({created}): {body}"


def review_thread_comments_text(
    all_review_comments: list[Any],
    trigger_comment_id: int,
) -> str:
    """Extract and format the review thread containing *trigger_comment_id*."""
    thread = _filter_review_comments_in_thread(all_review_comments, trigger_comment_id)
    filtered = [c for c in thread if _is_org_member(c)]
    if not filtered:
        return ""
    return "\n".join(_format_review_comment(c) for c in filtered)


def all_review_comments_text(review_comments: list[Any]) -> str:
    """Format all review comments grouped by file path, filtered to org members."""
    filtered = [c for c in review_comments if _is_org_member(c)]
    if not filtered:
        return ""

    by_path: dict[str, list[Any]] = {}
    for c in filtered:
        path = get_field(c, "path") or "(no file)"
        by_path.setdefault(path, []).append(c)

    sections: list[str] = []
    for path, comments in by_path.items():
        lines = [f"File: {path}"]
        for c in comments:
            login = get_login(get_field(c, "user")) or "unknown"
            created = get_timestamp_text(get_field(c, "created_at"))
            body = get_field(c, "body") or ""
            lines.append(f"  - {login} ({created}): {body}")
        sections.append("\n".join(lines))
    return "\n\n".join(sections)


def extract_issue_numbers_from_text(owner: str, repo: str, text: str) -> list[int]:
    issue_numbers = {int(match.group(1)) for match in ISSUE_PATTERN.finditer(text or "")}
    same_repo_url_pattern = re.compile(
        rf"https://github\.com/{re.escape(owner)}/{re.escape(repo)}/issues/(\d+)",
        re.IGNORECASE,
    )
    issue_numbers.update(int(match.group(1)) for match in same_repo_url_pattern.finditer(text or ""))
    return sorted(issue_numbers)


def resolve_issue_number_for_pr(
    github: Repository,
    owner: str,
    repo: str,
    pr: Any,
    changed_files: list[str],
) -> int | None:
    head_ref = str(get_field(get_field(pr, "head"), "ref") or "")
    branch_issue_matches = [
        int(match.group(1))
        for match in re.finditer(r"(?:^|/)(?:spec|implement)-issue-(\d+)(?:$|[/-])", head_ref)
    ]
    spec_file_issue_numbers = [
        int(match.group(1))
        for filename in changed_files
        for match in [re.match(r"^specs/GH(\d+)/(?:product|tech)\.md$", filename)]
        if match
    ]
    explicit_issue_numbers = extract_issue_numbers_from_text(owner, repo, str(get_field(pr, "body") or ""))
    candidates = list(dict.fromkeys(branch_issue_matches + spec_file_issue_numbers + explicit_issue_numbers))
    for candidate in candidates:
        issue = github.get_issue(candidate)
        if not issue.pull_request:
            return candidate
    return None


def is_spec_only_pr(changed_files: list[str]) -> bool:
    """Return True when every changed file lives under ``specs/``."""
    return bool(changed_files) and all(
        filename.startswith("specs/") for filename in changed_files
    )


def resolve_spec_context_for_pr(
    github: Repository,
    owner: str,
    repo: str,
    pr: Any,
    *,
    workspace: Path,
) -> dict[str, Any]:
    files = list(pr.get_files())
    changed_files = [str(file.filename) for file in files]
    issue_number = resolve_issue_number_for_pr(github, owner, repo, pr, changed_files)
    if not issue_number:
        return {
            "issue_number": None,
            "spec_context_source": "",
            "selected_spec_pr": None,
            "spec_entries": [],
            "changed_files": changed_files,
        }
    spec_context = resolve_spec_context_for_issue(
        github,
        owner,
        repo,
        issue_number,
        workspace=workspace,
    )
    spec_context["issue_number"] = issue_number
    spec_context["changed_files"] = changed_files
    return spec_context
