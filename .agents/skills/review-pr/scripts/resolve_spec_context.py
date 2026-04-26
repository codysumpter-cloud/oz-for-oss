from __future__ import annotations

import argparse
import os
import sys
from contextlib import closing
from pathlib import Path

from github import Auth, Github


REPO_ROOT = Path(__file__).resolve().parents[4]
GITHUB_SCRIPTS = REPO_ROOT / ".github" / "scripts"
if str(GITHUB_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(GITHUB_SCRIPTS))

from oz_workflows.helpers import resolve_spec_context_for_pr  # noqa: E402


NO_SPEC_CONTEXT_MESSAGE = "No approved or repository spec context was found for this PR."


def _resolve_token() -> str:
    token = (os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or "").strip()
    if not token:
        raise SystemExit(
            "GH_TOKEN or GITHUB_TOKEN must be set to resolve PR spec context."
        )
    return token


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Resolve approved or repository spec context for a pull request."
    )
    parser.add_argument(
        "--repo",
        required=True,
        help="Repository slug in OWNER/REPO format.",
    )
    parser.add_argument(
        "--pr",
        type=int,
        required=True,
        help="Pull request number to resolve spec context for.",
    )
    return parser.parse_args()


def _format_spec_context(spec_context: dict[str, object]) -> str:
    sections: list[str] = []
    selected_spec_pr = spec_context.get("selected_spec_pr")
    source = str(spec_context.get("spec_context_source") or "")
    if (
        source == "approved-pr"
        and isinstance(selected_spec_pr, dict)
        and selected_spec_pr.get("number")
        and selected_spec_pr.get("url")
    ):
        sections.append(
            f"Linked approved spec PR: [#{selected_spec_pr['number']}]({selected_spec_pr['url']})"
        )
    elif source == "directory":
        sections.append("Repository spec context was found in `specs/`.")
    for entry in spec_context.get("spec_entries", []):
        if not isinstance(entry, dict):
            continue
        path = str(entry.get("path") or "").strip()
        content = str(entry.get("content") or "").strip()
        if not path or not content:
            continue
        sections.append(f"## {path}\n\n{content}")
    return "\n\n".join(sections).strip() or NO_SPEC_CONTEXT_MESSAGE


def main() -> None:
    args = _parse_args()
    if "/" not in args.repo:
        raise SystemExit(
            f"Invalid repository slug: {args.repo!r}. Expected OWNER/REPO."
        )
    owner, repo = args.repo.split("/", 1)
    token = _resolve_token()
    with closing(Github(auth=Auth.Token(token))) as client:
        github = client.get_repo(args.repo)
        pr = github.get_pull(args.pr)
        spec_context = resolve_spec_context_for_pr(
            github,
            owner,
            repo,
            pr,
            workspace=REPO_ROOT,
        )
    print(_format_spec_context(spec_context))


if __name__ == "__main__":
    main()
