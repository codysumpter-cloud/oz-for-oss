from __future__ import annotations

from textwrap import dedent

from oz_workflows.env import optional_env, repo_parts, workspace
from oz_workflows.oz_client import build_agent_config, run_agent


def main() -> None:
    owner, repo = repo_parts()
    days = optional_env("LOOKBACK_DAYS") or "7"

    prompt = dedent(
        f"""
        Update the PR review skills for repository {owner}/{repo}.

        Use the repository's local `update-pr-review` skill as the base workflow.

        Cloud Workflow Requirements:
        - You are running in a cloud environment with the repository already checked out.
        - Run the feedback aggregation script with a {days}-day lookback window.
        - The aggregated feedback includes a `review_type` field per PR: `"code"` or `"spec"`.
        - Route feedback from `"code"` PRs to `.agents/skills/review-pr/SKILL.md` and feedback from `"spec"` PRs to `.agents/skills/review-spec/SKILL.md`.
        - Update each skill independently based on its category of feedback. Skip a skill if its category has no actionable feedback.
        - If you produce changes, commit them to a new branch named `oz-agent/update-pr-review` and push that branch to origin.
        - Open a pull request for the changes if a branch is pushed, and tag @captainsafia as a reviewer.
        - If no skill update is warranted based on the feedback, do not push a branch or open a PR.
        """
    ).strip()

    config = build_agent_config(
        config_name="update-pr-review",
        workspace=workspace(),
        environment_env_names=[
            "WARP_AGENT_REVIEW_ENVIRONMENT_ID",
            "WARP_AGENT_ENVIRONMENT_ID",
        ],
    )
    run_agent(
        prompt=prompt,
        skill_name="update-pr-review",
        title="Update PR review skill from feedback",
        config=config,
    )


if __name__ == "__main__":
    main()
