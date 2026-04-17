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
