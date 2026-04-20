"""Helpers for resolving and referencing repo-local companion skills.

Core agent skills in ``.agents/skills/<agent>/SKILL.md`` express the stable
cross-repo contract. Companion skills in ``.agents/skills/<agent>-local/SKILL.md``
live in the consuming repository's checkout and specialize the override
categories the core skill explicitly allows. These helpers let prompt-
construction code resolve a companion file and embed a fenced section that
references (not inlines) the companion file when one exists.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


_FRONTMATTER_PATTERN = re.compile(
    r"\A\s*---\s*\n.*?\n---\s*\n?",
    re.DOTALL,
)


def _body_without_frontmatter(raw_text: str) -> str:
    """Return *raw_text* with an optional leading YAML frontmatter block removed."""
    return _FRONTMATTER_PATTERN.sub("", raw_text, count=1)


def resolve_repo_local_skill_path(
    workspace: Path, core_skill_name: str
) -> Path | None:
    """Resolve the repo-local companion skill path for *core_skill_name*.

    Returns the absolute path to ``.agents/skills/<core_skill_name>-local/SKILL.md``
    in the consuming repository's *workspace* when the file exists and contains
    non-frontmatter body content; otherwise returns ``None``.

    A missing file, an empty file, or a file that contains only YAML
    frontmatter (no body) is treated as absent so the caller can omit the
    companion reference entirely.
    """
    if not core_skill_name or not core_skill_name.strip():
        return None

    candidate = (
        Path(workspace)
        / ".agents"
        / "skills"
        / f"{core_skill_name}-local"
        / "SKILL.md"
    )
    try:
        if not candidate.is_file():
            return None
        raw_text = candidate.read_text(encoding="utf-8")
    except OSError:
        return None

    body = _body_without_frontmatter(raw_text).strip()
    if not body:
        return None
    return candidate.resolve()


def format_repo_local_prompt_section(
    core_skill_name: str, companion_path: Path
) -> str:
    """Return the fenced prompt section that references *companion_path*.

    The section intentionally contains only a path reference plus an
    override reminder. The companion body is never inlined into the prompt
    string; the agent is instructed to read the referenced file via its
    usual skill-read path.
    """
    return (
        f"## Repository-specific guidance for `{core_skill_name}`\n"
        f"Read and follow the companion skill at `{companion_path}` in the "
        "consuming repository's checkout. Its guidance may override only the "
        "categories your core skill marks as overridable. It must not change "
        "the core skill's output schema, severity labels, or safety rules.\n"
    )


# Write-surface guard used by the narrowed self-improvement loops.
#
# Each ``update-<agent>`` Python entrypoint runs ``git diff --name-only
# <base>...<branch>`` before pushing and passes the result to
# :func:`assert_write_surface` with the loop's allowed prefixes. Any file
# outside those prefixes aborts the run so the loop cannot silently expand
# its write surface into the core skill files or the workflow scripts.
class WriteSurfaceViolation(RuntimeError):
    """Raised when a self-improvement loop touched disallowed files."""


def assert_write_surface(
    changed_files: list[str],
    *,
    allowed_prefixes: list[str],
    loop_name: str,
) -> None:
    """Validate that every entry in *changed_files* starts with an allowed prefix.

    *allowed_prefixes* is a list of repository-root-relative prefixes
    (for example ``.agents/skills/review-pr-local/``). A file matches when
    its normalized path starts with any prefix.
    """
    normalized_prefixes = [p.replace("\\", "/") for p in allowed_prefixes if p]
    violations: list[str] = []
    for raw_path in changed_files:
        path = raw_path.strip()
        if not path:
            continue
        path = path.replace("\\", "/")
        if not any(path.startswith(prefix) for prefix in normalized_prefixes):
            violations.append(path)
    if violations:
        pretty = ", ".join(violations)
        allowed = ", ".join(normalized_prefixes) or "(none)"
        raise WriteSurfaceViolation(
            f"{loop_name} attempted to write outside its allowed surface. "
            f"Disallowed paths: {pretty}. Allowed prefixes: {allowed}."
        )


# Shared push/PR plumbing for the narrowed self-improvement loops.
#
# Each ``update-<agent>`` Python entrypoint invokes Oz, which leaves a
# local commit on ``oz-agent/update-<agent>`` without pushing. The
# entrypoint then calls :func:`maybe_push_update_branch` to run the
# write-surface guard, push the branch to ``origin`` only when the guard
# passes, and open a pull request so a human reviewer is notified.


def branch_exists(repo_root: Path, branch: str) -> bool:
    """Return ``True`` when ``refs/heads/<branch>`` exists under *repo_root*."""
    result = subprocess.run(
        ["git", "rev-parse", "--verify", f"refs/heads/{branch}"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def changed_files_since_origin_main(repo_root: Path, branch: str) -> list[str]:
    """Return the list of paths changed on *branch* relative to ``origin/main``."""
    result = subprocess.run(
        ["git", "diff", "--name-only", f"origin/main...{branch}"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


def _pr_exists_for_branch(repo_root: Path, branch: str) -> bool:
    """Return ``True`` when an open PR already targets *branch* as its head.

    Uses ``gh pr list --head`` which scopes to open PRs by default. Returns
    ``False`` on any gh/authentication error so the caller falls back to
    attempting ``gh pr create`` and surfaces any real failure from there.
    """
    result = subprocess.run(
        ["gh", "pr", "list", "--head", branch, "--json", "number"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False
    stdout = result.stdout.strip()
    # ``gh pr list --json number`` returns ``[]`` when there are no open PRs
    # against the head and a non-empty JSON array when there is at least one.
    return bool(stdout) and stdout != "[]"


def maybe_push_update_branch(
    repo_root: Path,
    branch: str,
    *,
    allowed_prefixes: list[str],
    loop_name: str,
    pr_title: str,
    pr_body: str,
    base_branch: str = "main",
    reviewer: str | None = None,
) -> None:
    """Enforce the write surface, push *branch*, and open a PR if one is missing.

    When the agent left a local commit on *branch*, collect the changed
    paths against ``origin/main`` and pass them to
    :func:`assert_write_surface`. A violation aborts the loop rather than
    silently widening the surface. When the guard passes the branch is
    pushed and a PR is opened (tagging *reviewer* when provided) so a human
    reviewer is notified instead of the branch landing silently. When no
    local commit exists, do nothing.
    """
    if not branch_exists(repo_root, branch):
        return
    changed_files = changed_files_since_origin_main(repo_root, branch)
    if not changed_files:
        return
    assert_write_surface(
        changed_files,
        allowed_prefixes=allowed_prefixes,
        loop_name=loop_name,
    )
    subprocess.run(
        ["git", "push", "origin", branch],
        cwd=str(repo_root),
        check=True,
    )
    # Creating the PR is the new notification step. Prior versions of each
    # entrypoint told the agent to open the PR itself; pulling that into
    # the Python entrypoint ensures the branch is never pushed silently.
    if _pr_exists_for_branch(repo_root, branch):
        return
    create_cmd = [
        "gh",
        "pr",
        "create",
        "--head",
        branch,
        "--base",
        base_branch,
        "--title",
        pr_title,
        "--body",
        pr_body,
    ]
    if reviewer:
        create_cmd.extend(["--reviewer", reviewer])
    subprocess.run(create_cmd, cwd=str(repo_root), check=True)
