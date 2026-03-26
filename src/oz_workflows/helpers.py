from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .github_api import GitHubClient


ISSUE_PATTERN = re.compile(r"(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?|refs?|implements?|issue)\s*:?\s+#(\d+)", re.IGNORECASE)


def parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def org_member_comments_text(
    comments: list[dict[str, Any]],
    *,
    exclude_comment_id: int | None = None,
) -> str:
    selected = [
        comment
        for comment in comments
        if comment.get("author_association") in {"MEMBER", "OWNER"}
        and int(comment.get("id") or 0) != exclude_comment_id
    ]
    if not selected:
        return ""
    return "\n".join(
        f"- {comment.get('user', {}).get('login') or 'unknown'} ({comment.get('created_at')}): {comment.get('body') or ''}"
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


def comment_metadata(workflow: str, issue_number: int) -> str:
    return f'<!-- oz-agent-metadata: {{"type":"issue-status","workflow":"{workflow}","issue":{issue_number}}} -->'


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


def append_comment_sections(existing_body: str, metadata: str, sections: list[str]) -> str:
    content, metadata = split_comment_body(existing_body, metadata)
    normalized_sections = [section.strip() for section in sections if section and section.strip()]
    if not content:
        return build_comment_body("\n\n".join(normalized_sections), metadata)

    updated = content
    for section in normalized_sections:
        if section not in updated:
            updated = f"{updated}\n\n{section}"
    return build_comment_body(updated, metadata)


def resolve_oz_assigner_login(
    github: GitHubClient,
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

    events = github.list_issue_events(owner, repo, issue_number)
    matching_events = [
        event
        for event in events
        if event.get("event") == "assigned"
        and (event.get("assignee") or {}).get("login") == "oz-agent"
    ]
    if not matching_events:
        return (event_payload.get("sender") or {}).get("login") or ""

    matching_events.sort(
        key=lambda event: parse_datetime(event.get("created_at") or "1970-01-01T00:00:00Z"),
        reverse=True,
    )
    return (matching_events[0].get("actor") or {}).get("login") or ""

def resolve_progress_requester_login(
    github: GitHubClient,
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
        github: GitHubClient,
        owner: str,
        repo: str,
        issue_number: int,
        *,
        workflow: str,
        event_payload: dict[str, Any] | None = None,
        requester_login: str = "",
    ) -> None:
        self.github = github
        self.owner = owner
        self.repo = repo
        self.issue_number = issue_number
        self.workflow = workflow
        self.event_payload = event_payload or {}
        self.requester_login = requester_login
        self.metadata = comment_metadata(workflow, issue_number)
        self.comment_id: int | None = None

    def start(self, status_line: str) -> None:
        self._append_sections([status_line])

    def record_session_link(self, session_link: str) -> None:
        if not session_link.strip():
            return
        self._append_sections([f"Sharing session at: {session_link.strip()}"])

    def complete(self, status_line: str) -> None:
        self._append_sections([status_line])

    def cleanup(self) -> None:
        """Delete the progress comment if one exists from this or a previous run."""
        if self.comment_id is not None:
            self.github.delete_comment(self.owner, self.repo, self.comment_id)
            self.comment_id = None
            return
        existing = self._get_or_find_existing_comment()
        if existing is not None:
            self.github.delete_comment(self.owner, self.repo, int(existing["id"]))
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
            created = self.github.create_comment(
                self.owner,
                self.repo,
                self.issue_number,
                build_comment_body("\n\n".join(normalized_sections), self.metadata),
            )
            self.comment_id = int(created["id"])
            return
        updated_body = append_comment_sections(str(existing.get("body") or ""), self.metadata, normalized_sections)
        self.github.update_comment(self.owner, self.repo, int(existing["id"]), updated_body)
        self.comment_id = int(existing["id"])

    def _get_or_find_existing_comment(self) -> dict[str, Any] | None:
        if self.comment_id is not None:
            return self.github.get_comment(self.owner, self.repo, self.comment_id)
        comments = self.github.list_issue_comments(self.owner, self.repo, self.issue_number)
        existing = next(
            (
                comment
                for comment in comments
                if isinstance(comment.get("body"), str) and self.metadata in comment["body"]
            ),
            None,
        )
        if existing:
            self.comment_id = int(existing["id"])
        return existing


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


def conventional_commit_prefix(labels: list[dict[str, Any] | str], *, default: str = "feat") -> str:
    """Derive a conventional-commit type prefix from issue labels.

    Returns the first matching prefix found by scanning *labels* against a
    known mapping, or *default* when no label matches.
    """
    for label in labels:
        name = (label if isinstance(label, str) else label.get("name") or "").lower()
        if name in _LABEL_TO_COMMIT_TYPE:
            return _LABEL_TO_COMMIT_TYPE[name]
    return default


def build_plan_preview_section(owner: str, repo: str, branch_name: str, issue_number: int) -> str:
    plan_path = f"plans/issue-{issue_number}.md"
    preview_url = f"https://github.com/{owner}/{repo}/blob/{branch_name}/{plan_path}"
    return f"Preview generated plan: [{plan_path}]({preview_url})"


def build_next_steps_section(steps: list[str]) -> str:
    normalized_steps = [step.strip() for step in steps if step and step.strip()]
    if not normalized_steps:
        return ""
    return "Next steps:\n" + "\n".join(f"- {step}" for step in normalized_steps)


def branch_exists(github: GitHubClient, owner: str, repo: str, branch: str) -> bool:
    return github.get_ref(owner, repo, f"heads/{branch}") is not None


def branch_updated_since(
    github: GitHubClient,
    owner: str,
    repo: str,
    branch: str,
    *,
    created_after: datetime,
) -> bool:
    ref = github.get_ref(owner, repo, f"heads/{branch}")
    if not ref:
        return False
    sha = ref.get("object", {}).get("sha")
    if not sha:
        return False
    commit = github.get_commit(owner, repo, sha)
    committed_at = parse_datetime(commit["commit"]["committer"]["date"])
    return committed_at >= created_after


def find_matching_plan_prs(
    github: GitHubClient,
    owner: str,
    repo: str,
    issue_number: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    expected_plan_branch = f"oz-agent/plan-issue-{issue_number}"
    matching = github.list_pulls(owner, repo, state="all", head=f"{owner}:{expected_plan_branch}")
    approved: list[dict[str, Any]] = []
    unapproved: list[dict[str, Any]] = []
    for pr in matching:
        labels = [
            label if isinstance(label, str) else label.get("name")
            for label in pr.get("labels", [])
        ]
        files = github.list_pull_files(owner, repo, int(pr["number"]))
        plan_files = [
            file["filename"]
            for file in files
            if file["filename"].startswith("plans/")
        ]
        entry = {
            "number": pr["number"],
            "url": pr["html_url"],
            "updated_at": pr["updated_at"],
            "head_ref_name": pr["head"]["ref"],
            "head_repo_full_name": (pr.get("head") or {}).get("repo", {}).get("full_name", ""),
            "plan_files": plan_files,
        }
        if "plan-approved" in labels:
            approved.append(entry)
        else:
            unapproved.append(entry)
    approved.sort(key=lambda item: parse_datetime(item["updated_at"]), reverse=True)
    unapproved.sort(key=lambda item: parse_datetime(item["updated_at"]), reverse=True)
    return approved, unapproved


def read_local_plan_file(workspace: Path, issue_number: int) -> tuple[str, str] | None:
    path = workspace / "plans" / f"issue-{issue_number}.md"
    if not path.exists():
        return None
    return (f"plans/issue-{issue_number}.md", path.read_text(encoding="utf-8").strip())


def resolve_plan_context_for_issue(
    github: GitHubClient,
    owner: str,
    repo: str,
    issue_number: int,
    *,
    workspace: Path,
) -> dict[str, Any]:
    approved, unapproved = find_matching_plan_prs(github, owner, repo, issue_number)
    selected = approved[0] if approved else None
    local_plan = read_local_plan_file(workspace, issue_number)
    if selected and selected["head_repo_full_name"] != f"{owner}/{repo}":
        raise RuntimeError(
            f"Linked approved plan PR #{selected['number']} uses branch "
            f"{selected['head_repo_full_name']}:{selected['head_ref_name']}, which this workflow cannot push to."
        )

    plan_context_source = "approved-pr" if selected else "directory" if local_plan else ""
    plan_entries: list[dict[str, str]] = []
    if selected:
        for path in selected["plan_files"]:
            content = github.get_contents_text(owner, repo, path, ref=selected["head_ref_name"])
            if content is None:
                continue
            plan_entries.append({"path": path, "content": content.strip()})
    elif local_plan:
        path, content = local_plan
        plan_entries.append({"path": path, "content": content})

    return {
        "selected_plan_pr": selected,
        "approved_plan_prs": approved,
        "unapproved_plan_prs": unapproved,
        "plan_context_source": plan_context_source,
        "plan_entries": plan_entries,
    }


def _is_org_member(comment: dict[str, Any]) -> bool:
    return comment.get("author_association") in {"MEMBER", "OWNER"}


def _format_review_comment(comment: dict[str, Any]) -> str:
    login = (comment.get("user") or {}).get("login") or "unknown"
    created = comment.get("created_at") or ""
    body = comment.get("body") or ""
    path = comment.get("path") or ""
    prefix = f"{path}: " if path else ""
    return f"- {prefix}{login} ({created}): {body}"


def review_thread_comments_text(
    all_review_comments: list[dict[str, Any]],
    trigger_comment_id: int,
) -> str:
    """Extract and format the review thread containing *trigger_comment_id*.

    Thread identification uses ``in_reply_to_id``: the root comment has no
    ``in_reply_to_id`` and replies point to the root's ``id``.
    """
    by_id: dict[int, dict[str, Any]] = {int(c["id"]): c for c in all_review_comments}

    # Walk up from the trigger comment to find the thread root.
    root_id = trigger_comment_id
    while True:
        comment = by_id.get(root_id)
        if not comment:
            break
        parent = comment.get("in_reply_to_id")
        if parent is None or int(parent) not in by_id:
            break
        root_id = int(parent)

    # Collect all comments in this thread.
    thread = [
        c
        for c in all_review_comments
        if int(c["id"]) == root_id or c.get("in_reply_to_id") == root_id
    ]
    filtered = [c for c in thread if _is_org_member(c)]
    if not filtered:
        return ""
    return "\n".join(_format_review_comment(c) for c in filtered)


def all_review_comments_text(review_comments: list[dict[str, Any]]) -> str:
    """Format all review comments grouped by file path, filtered to org members."""
    filtered = [c for c in review_comments if _is_org_member(c)]
    if not filtered:
        return ""

    by_path: dict[str, list[dict[str, Any]]] = {}
    for c in filtered:
        path = c.get("path") or "(no file)"
        by_path.setdefault(path, []).append(c)

    sections: list[str] = []
    for path, comments in by_path.items():
        lines = [f"File: {path}"]
        for c in comments:
            login = (c.get("user") or {}).get("login") or "unknown"
            created = c.get("created_at") or ""
            body = c.get("body") or ""
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
    github: GitHubClient,
    owner: str,
    repo: str,
    pr: dict[str, Any],
    changed_files: list[str],
) -> int | None:
    branch_issue_matches = [
        int(match.group(1))
        for match in re.finditer(r"(?:^|/)(?:plan|implement)-issue-(\d+)(?:$|[/-])", pr["head"]["ref"])
    ]
    plan_file_issue_numbers = [
        int(match.group(1))
        for filename in changed_files
        for match in [re.match(r"^plans/issue-(\d+)\.md$", filename)]
        if match
    ]
    explicit_issue_numbers = extract_issue_numbers_from_text(owner, repo, pr.get("body") or "")
    candidates = list(dict.fromkeys(branch_issue_matches + plan_file_issue_numbers + explicit_issue_numbers))
    for candidate in candidates:
        issue = github.get_issue(owner, repo, candidate)
        if not issue.get("pull_request"):
            return candidate
    return None


def resolve_plan_context_for_pr(
    github: GitHubClient,
    owner: str,
    repo: str,
    pr: dict[str, Any],
    *,
    workspace: Path,
) -> dict[str, Any]:
    files = github.list_pull_files(owner, repo, int(pr["number"]))
    changed_files = [file["filename"] for file in files]
    issue_number = resolve_issue_number_for_pr(github, owner, repo, pr, changed_files)
    if not issue_number:
        return {
            "issue_number": None,
            "plan_context_source": "",
            "selected_plan_pr": None,
            "plan_entries": [],
        }
    plan_context = resolve_plan_context_for_issue(
        github,
        owner,
        repo,
        issue_number,
        workspace=workspace,
    )
    plan_context["issue_number"] = issue_number
    return plan_context
