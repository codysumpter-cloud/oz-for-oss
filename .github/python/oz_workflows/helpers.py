from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .github_api import GitHubClient


ISSUE_PATTERN = re.compile(r"(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?|refs?|implements?|issue)\s*:?\s+#(\d+)", re.IGNORECASE)


def parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def org_member_comments_text(comments: list[dict[str, Any]]) -> str:
    selected = [
        comment
        for comment in comments
        if comment.get("author_association") in {"MEMBER", "OWNER"}
    ]
    if not selected:
        return ""
    return "\n".join(
        f"- {comment.get('user', {}).get('login') or 'unknown'} ({comment.get('created_at')}): {comment.get('body') or ''}"
        for comment in selected
    )


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


def upsert_status_comment(
    github: GitHubClient,
    owner: str,
    repo: str,
    issue_number: int,
    *,
    event_payload: dict[str, Any],
    workflow: str,
    status_line: str,
) -> dict[str, Any]:
    metadata = comment_metadata(workflow, issue_number)
    comments = github.list_issue_comments(owner, repo, issue_number)
    existing = next(
        (
            comment
            for comment in comments
            if isinstance(comment.get("body"), str)
            and (metadata in comment["body"] or comment["body"].strip() == status_line)
        ),
        None,
    )
    if existing:
        updated_body = append_comment_sections(str(existing.get("body") or ""), metadata, [status_line])
        updated = github.update_comment(owner, repo, int(existing["id"]), updated_body)
        updated["_oz_metadata"] = metadata
        updated["_oz_created"] = False
        return updated
    assigner_login = resolve_oz_assigner_login(
        github,
        owner,
        repo,
        issue_number,
        event_payload=event_payload,
    )
    initial_sections = [status_line]
    if assigner_login:
        initial_sections.insert(0, f"@{assigner_login}")
    created = github.create_comment(
        owner,
        repo,
        issue_number,
        build_comment_body("\n\n".join(initial_sections), metadata),
    )
    created["_oz_metadata"] = metadata
    created["_oz_created"] = True
    return created


def update_status_comment(
    github: GitHubClient,
    owner: str,
    repo: str,
    comment_id: int,
    *,
    status_line: str,
    metadata: str,
    session_link: str | None = None,
) -> None:
    existing = github.get_comment(owner, repo, comment_id)
    sections = [status_line]
    if session_link:
        sections.append(f"Sharing session at: {session_link}")
    updated_body = append_comment_sections(str(existing.get("body") or ""), metadata, sections)
    github.update_comment(owner, repo, comment_id, updated_body)


def build_plan_preview_section(owner: str, repo: str, branch_name: str, issue_number: int) -> str:
    plan_path = f"plans/issue-{issue_number}.md"
    preview_url = f"https://github.com/{owner}/{repo}/blob/{branch_name}/{plan_path}"
    return f"Preview generated plan: [{plan_path}]({preview_url})"


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
