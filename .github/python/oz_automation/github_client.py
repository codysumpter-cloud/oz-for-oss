from __future__ import annotations

import json
import os
import re
from base64 import b64decode
from typing import Iterable, Sequence

from github import Auth, Github
from github.Issue import Issue
from github.IssueComment import IssueComment
from github.Label import Label
from github.NamedUser import NamedUser
from github.PullRequest import PullRequest
from github.Repository import Repository

from oz_automation.context import RepoRef, require_env


def get_client() -> Github:
    token = (
        os.getenv("GH_TOKEN", "").strip()
        or os.getenv("GITHUB_TOKEN", "").strip()
    )
    if not token:
        token = require_env("INPUT_GITHUB_TOKEN")
    return Github(auth=Auth.Token(token))


def get_repository(repo_ref: RepoRef) -> Repository:
    return get_client().get_repo(repo_ref.full_name)


def list_comments(issue: Issue) -> list[IssueComment]:
    return list(issue.get_comments())


def issue_metadata(workflow: str, issue_number: int) -> str:
    payload = json.dumps(
        {"type": "issue-status", "workflow": workflow, "issue": issue_number},
        separators=(",", ":"),
    )
    return f"<!-- oz-agent-metadata: {payload} -->"


def compose_body(lines: Sequence[str], metadata: str) -> str:
    rendered = [line for line in lines if line is not None]
    rendered.extend(["", metadata])
    return "\n".join(rendered)


def find_matching_comment(
    comments: Iterable[IssueComment],
    metadata: str,
    legacy_bodies: Sequence[str] | None = None,
) -> IssueComment | None:
    legacy_bodies = legacy_bodies or ()
    for comment in comments:
        body = comment.body or ""
        if metadata in body:
            return comment
        if body.strip() in legacy_bodies:
            return comment
    return None


def upsert_comment(
    issue: Issue,
    workflow: str,
    body_lines: Sequence[str],
    legacy_bodies: Sequence[str] | None = None,
) -> IssueComment:
    metadata = issue_metadata(workflow, issue.number)
    body = compose_body(body_lines, metadata)
    existing = find_matching_comment(list_comments(issue), metadata, legacy_bodies)
    if existing:
        existing.edit(body=body)
        return existing
    return issue.create_comment(body)


def remove_assignee(issue: Issue, login: str) -> None:
    issue.remove_from_assignees(login)


def list_pulls_by_head(
    repo: Repository,
    owner: str,
    branch: str,
    state: str = "open",
) -> list[PullRequest]:
    return list(repo.get_pulls(state=state, head=f"{owner}:{branch}"))


def labels_to_names(labels: Iterable[Label | str]) -> list[str]:
    names: list[str] = []
    for label in labels:
        if isinstance(label, str):
            names.append(label)
        else:
            names.append(label.name)
    return [name for name in names if name]


def get_pull_changed_files(pr: PullRequest) -> list[str]:
    return [file.filename for file in pr.get_files()]


def get_file_text(repo: Repository, path: str, ref: str | None = None) -> str | None:
    try:
        content = repo.get_contents(path, ref=ref) if ref else repo.get_contents(path)
    except Exception:
        return None

    if isinstance(content, list):
        return None
    if content.encoding == "base64":
        return b64decode(content.content).decode("utf-8")
    return content.decoded_content.decode("utf-8")


def get_label(repo: Repository, label_name: str) -> Label | None:
    try:
        return repo.get_label(label_name)
    except Exception:
        return None


def list_open_issues_with_label(repo: Repository, label_name: str) -> list[Issue]:
    label = get_label(repo, label_name)
    if label is None:
        return []
    return [issue for issue in repo.get_issues(state="open", labels=[label]) if issue.pull_request is None]


def create_reaction(comment: IssueComment, content: str) -> None:
    comment.create_reaction(content)


def get_non_pr_issue(repo: Repository, issue_number: int) -> Issue | None:
    issue = repo.get_issue(number=issue_number)
    if issue.pull_request is not None:
        return None
    return issue


def extract_issue_numbers(text: str, owner: str, repo: str) -> list[int]:
    same_repo_pattern = re.compile(
        rf"https://github\.com/{re.escape(owner)}/{re.escape(repo)}/issues/(\d+)",
        re.IGNORECASE,
    )
    explicit_patterns = [
        re.compile(r"(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?|refs?|implements?|issue)\s*:?\s*#(\d+)", re.IGNORECASE),
        same_repo_pattern,
    ]
    values: list[int] = []
    for pattern in explicit_patterns:
        values.extend(int(match) for match in pattern.findall(text or ""))
    return sorted(set(values))


def issue_author_login(issue: Issue) -> str:
    user = issue.user
    if isinstance(user, NamedUser):
        return user.login
    return getattr(user, "login", "unknown")
