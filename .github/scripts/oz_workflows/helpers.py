from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from github import Github
from github.GithubException import UnknownObjectException
from github.Repository import Repository


# Author associations that indicate organization membership.
ORG_MEMBER_ASSOCIATIONS: set[str] = {"COLLABORATOR", "MEMBER", "OWNER"}

ISSUE_PATTERN = re.compile(r"(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?|refs?|implements?|issue)\s*:?\s+#(\d+)", re.IGNORECASE)


def parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _field(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _login(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("login") or "")
    return str(getattr(item, "login", "") or "")


def _timestamp_text(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return str(value or "")


def _label_name(label: Any) -> str:
    if isinstance(label, str):
        return label
    return str(_field(label, "name", "") or "")


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


def org_member_comments_text(
    comments: list[Any],
    *,
    exclude_comment_id: int | None = None,
) -> str:
    selected = [
        comment
        for comment in comments
        if _field(comment, "author_association") in ORG_MEMBER_ASSOCIATIONS
        and int(_field(comment, "id") or 0) != exclude_comment_id
    ]
    if not selected:
        return ""
    return "\n".join(
        f"- {_login(_field(comment, 'user')) or 'unknown'} ({_timestamp_text(_field(comment, 'created_at'))}): {_field(comment, 'body') or ''}"
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


def comment_metadata(workflow: str, issue_number: int, *, run_id: str = "") -> str:
    if run_id:
        return f'<!-- oz-agent-metadata: {{"type":"issue-status","workflow":"{workflow}","issue":{issue_number},"run_id":"{run_id}"}} -->'
    return f'<!-- oz-agent-metadata: {{"type":"issue-status","workflow":"{workflow}","issue":{issue_number}}} -->'


def _workflow_metadata_prefix(workflow: str, issue_number: int) -> str:
    """Return the stable metadata prefix shared by all runs of the same workflow on an issue."""
    return f'<!-- oz-agent-metadata: {{"type":"issue-status","workflow":"{workflow}","issue":{issue_number}'


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
        if _field(event, "event") == "assigned"
        and _login(_field(event, "assignee")) == "oz-agent"
    ]
    if not matching_events:
        return (event_payload.get("sender") or {}).get("login") or ""

    matching_events.sort(
        key=lambda event: (
            _field(event, "created_at").astimezone(timezone.utc)
            if isinstance(_field(event, "created_at"), datetime)
            else parse_datetime(str(_field(event, "created_at") or "1970-01-01T00:00:00Z"))
        ),
        reverse=True,
    )
    return _login(_field(matching_events[0], "actor"))


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
    ) -> None:
        self.github = github
        self.owner = owner
        self.repo = repo
        self.issue_number = issue_number
        self.workflow = workflow
        self.event_payload = event_payload or {}
        self.requester_login = requester_login
        self.run_id = uuid.uuid4().hex
        self.metadata = comment_metadata(workflow, issue_number, run_id=self.run_id)
        self._workflow_prefix = _workflow_metadata_prefix(workflow, issue_number)
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
            try:
                _delete_issue_comment(
                    self.github,
                    self.owner,
                    self.repo,
                    self.issue_number,
                    self.comment_id,
                )
            except Exception:
                pass
            self.comment_id = None
            return
        while True:
            existing = self._find_any_workflow_comment()
            if existing is None:
                break
            try:
                _delete_issue_comment(
                    self.github,
                    self.owner,
                    self.repo,
                    self.issue_number,
                    int(_field(existing, "id")),
                )
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
            created = _create_issue_comment(
                self.github,
                self.owner,
                self.repo,
                self.issue_number,
                build_comment_body("\n\n".join(normalized_sections), self.metadata),
            )
            self.comment_id = int(_field(created, "id"))
            return
        updated_body = append_comment_sections(str(_field(existing, "body") or ""), self.metadata, normalized_sections)
        _update_issue_comment(
            self.github,
            self.owner,
            self.repo,
            self.issue_number,
            int(_field(existing, "id")),
            updated_body,
        )
        self.comment_id = int(_field(existing, "id"))

    def _find_any_workflow_comment(self) -> Any | None:
        """Find any progress comment for this workflow on this issue, regardless of run."""
        comments = _list_issue_comments(self.github, self.owner, self.repo, self.issue_number)
        return next(
            (
                comment
                for comment in comments
                if isinstance(_field(comment, "body"), str)
                and self._workflow_prefix in (_field(comment, "body") or "")
            ),
            None,
        )

    def _get_or_find_existing_comment(self) -> Any | None:
        if self.comment_id is not None:
            try:
                return _get_issue_comment(
                    self.github,
                    self.owner,
                    self.repo,
                    self.comment_id,
                    issue_number=self.issue_number,
                )
            except UnknownObjectException:
                self.comment_id = None
        comments = _list_issue_comments(self.github, self.owner, self.repo, self.issue_number)
        existing = next(
            (
                comment
                for comment in comments
                if isinstance(_field(comment, "body"), str) and self.metadata in str(_field(comment, "body") or "")
            ),
            None,
        )
        if existing:
            self.comment_id = int(_field(existing, "id"))
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


def conventional_commit_prefix(labels: list[Any], *, default: str = "feat") -> str:
    """Derive a conventional-commit type prefix from issue labels.

    Returns the first matching prefix found by scanning *labels* against a
    known mapping, or *default* when no label matches.
    """
    for label in labels:
        name = _label_name(label).lower()
        if name in _LABEL_TO_COMMIT_TYPE:
            return _LABEL_TO_COMMIT_TYPE[name]
    return default


# Accounts created on or after this date use the ``ID+login`` noreply format.
# See https://docs.github.com/en/account-and-profile/reference/email-addresses-reference#your-noreply-email-address
_NOREPLY_ID_CUTOFF = datetime(2017, 7, 18, tzinfo=timezone.utc)


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

    name = (_field(user, "name") if user else None) or login
    user_id = _field(user, "id") if user else None
    created_at = _field(user, "created_at") if user else None
    email = _noreply_email(login, user_id, created_at)
    return f"Co-Authored-By: {name} <{email}>"


def coauthor_prompt_lines(coauthor_line: str) -> str:
    """Return prompt directive lines for co-authorship."""
    if coauthor_line:
        return (
            f"- Include the following co-author attribution at the end of every commit message: {coauthor_line}\n"
            f"            - Do not attempt to resolve the co-author identity yourself (e.g. via GET /user). Use exactly the line provided above."
        )
    return "- Do not include any Co-Authored-By lines in commit messages."


def build_spec_preview_section(owner: str, repo: str, branch_name: str, issue_number: int) -> str:
    product_path = f"specs/issue-{issue_number}/product.md"
    tech_path = f"specs/issue-{issue_number}/tech.md"
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
            msg = (_field(commit, "commit") or {}).get("message") or ""
        else:
            msg = getattr(_field(commit, "commit"), "message", "") or ""
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
        commit = _field(branch_ref, "commit")
        commit_data = _field(commit, "commit")
        committer = _field(commit_data, "committer")
        commit_date = _field(committer, "date")
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
        labels = [_label_name(label) for label in pr.as_issue().labels]
        files = list(pr.get_files())
        spec_files = [
            str(file.filename)
            for file in files
            if str(file.filename).startswith("specs/")
        ]
        entry = {
            "number": pr.number,
            "url": pr.html_url,
            "updated_at": _timestamp_text(pr.updated_at),
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
    spec_dir = workspace / "specs" / f"issue-{issue_number}"
    results: list[tuple[str, str]] = []
    for name in ("product.md", "tech.md"):
        path = spec_dir / name
        if path.exists():
            rel = f"specs/issue-{issue_number}/{name}"
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
    return _field(comment, "author_association") in ORG_MEMBER_ASSOCIATIONS


def _format_review_comment(comment: Any) -> str:
    login = _login(_field(comment, "user")) or "unknown"
    created = _timestamp_text(_field(comment, "created_at"))
    body = _field(comment, "body") or ""
    path = _field(comment, "path") or ""
    prefix = f"{path}: " if path else ""
    return f"- {prefix}{login} ({created}): {body}"


def review_thread_comments_text(
    all_review_comments: list[Any],
    trigger_comment_id: int,
) -> str:
    """Extract and format the review thread containing *trigger_comment_id*."""
    by_id: dict[int, Any] = {int(_field(c, "id")): c for c in all_review_comments}

    root_id = trigger_comment_id
    while True:
        comment = by_id.get(root_id)
        if not comment:
            break
        parent = _field(comment, "in_reply_to_id")
        if parent is None or int(parent) not in by_id:
            break
        root_id = int(parent)

    thread = [
        c
        for c in all_review_comments
        if int(_field(c, "id")) == root_id or _field(c, "in_reply_to_id") == root_id
    ]
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
        path = _field(c, "path") or "(no file)"
        by_path.setdefault(path, []).append(c)

    sections: list[str] = []
    for path, comments in by_path.items():
        lines = [f"File: {path}"]
        for c in comments:
            login = _login(_field(c, "user")) or "unknown"
            created = _timestamp_text(_field(c, "created_at"))
            body = _field(c, "body") or ""
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
    head_ref = str(_field(_field(pr, "head"), "ref") or "")
    branch_issue_matches = [
        int(match.group(1))
        for match in re.finditer(r"(?:^|/)(?:spec|implement)-issue-(\d+)(?:$|[/-])", head_ref)
    ]
    spec_file_issue_numbers = [
        int(match.group(1))
        for filename in changed_files
        for match in [re.match(r"^specs/issue-(\d+)/(?:product|tech)\.md$", filename)]
        if match
    ]
    explicit_issue_numbers = extract_issue_numbers_from_text(owner, repo, str(_field(pr, "body") or ""))
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
