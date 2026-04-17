from __future__ import annotations

import subprocess
from pathlib import Path
from textwrap import dedent

from oz_workflows.env import optional_env, repo_parts, workspace
from oz_workflows.oz_client import build_agent_config, run_agent
from oz_workflows.repo_local import WriteSurfaceViolation, assert_write_surface


UPDATE_BRANCH = "oz-agent/update-dedupe"
ALLOWED_PREFIXES: tuple[str, ...] = (
    ".agents/skills/dedupe-issue-local/",
)


def main() -> None:
    owner, repo = repo_parts()
    days = optional_env("LOOKBACK_DAYS") or "7"

    prompt = dedent(
        f"""
        Update the repo-local dedupe companion skill for repository {owner}/{repo}.

        Use the repository's local `update-dedupe` skill as the base workflow.

        Cloud Workflow Requirements:
        - You are running in a cloud environment with the repository already checked out.
        - Run the feedback aggregation script with a {days}-day lookback window.
        - The aggregated feedback is restricted to closed-as-duplicate signals. Other triage signals are handled by the separate `update-triage` loop.
        - Route feedback into `.agents/skills/dedupe-issue-local/SKILL.md` only.
        - Do NOT edit the core skill at `.agents/skills/dedupe-issue/SKILL.md`. It is the cross-repo contract and is read-only from this loop.
        - Do NOT edit `.agents/skills/triage-issue-local/SKILL.md` or any file under `.github/scripts/`.
        - The allowed write surface is strictly `.agents/skills/dedupe-issue-local/`.
        - If you produce changes, commit them to a local branch named `{UPDATE_BRANCH}` but do NOT push the branch yourself. The Python entrypoint will run a write-surface guard and push only when the guard passes.
        - If no companion update is warranted based on the feedback, do not create a commit. Leave the working tree clean.
        """
    ).strip()

    config = build_agent_config(
        config_name="update-dedupe",
        workspace=workspace(),
    )
    run_agent(
        prompt=prompt,
        skill_name="update-dedupe",
        title="Update dedupe companion skill from closed-as-duplicate signals",
        config=config,
    )

    maybe_push_update_branch(workspace(), UPDATE_BRANCH)


def maybe_push_update_branch(repo_root: Path, branch: str) -> None:
    """Enforce the write surface, then push ``branch`` to origin when a diff exists."""
    if not _branch_exists(repo_root, branch):
        return
    changed_files = _changed_files_since_origin_main(repo_root, branch)
    if not changed_files:
        return
    assert_write_surface(
        changed_files,
        allowed_prefixes=list(ALLOWED_PREFIXES),
        loop_name="update-dedupe",
    )
    subprocess.run(
        ["git", "push", "origin", branch],
        cwd=str(repo_root),
        check=True,
    )


def _branch_exists(repo_root: Path, branch: str) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", f"refs/heads/{branch}"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _changed_files_since_origin_main(repo_root: Path, branch: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", f"origin/main...{branch}"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


if __name__ == "__main__":
    try:
        main()
    except WriteSurfaceViolation as exc:
        raise SystemExit(str(exc))
