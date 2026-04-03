from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from oz_agent_sdk import OzAPI

from .actions import notice, warning
from .env import optional_env, parse_mcp_servers, repo_slug, require_env, workspace


TERMINAL_STATES = {"SUCCEEDED", "FAILED", "ERROR", "CANCELLED"}
DEFAULT_OZ_API_BASE_URL = "https://staging.warp.dev/api/v1"
DEFAULT_OZ_ORIGIN_TOKEN_ENV_NAME = "STAGING_ORIGIN_TOKEN"


def oz_api_base_url() -> str:
    """Return the configured Oz API base URL."""
    return optional_env("WARP_API_BASE_URL") or DEFAULT_OZ_API_BASE_URL


def oz_origin_token() -> str:
    """Return the origin token required for Oz API requests."""
    origin_token_env_name = (
        optional_env("WARP_ORIGIN_TOKEN_ENV_NAME") or DEFAULT_OZ_ORIGIN_TOKEN_ENV_NAME
    )
    return require_env(origin_token_env_name)


def build_oz_client() -> OzAPI:
    """Build an authenticated Oz SDK client for GitHub Actions workflows."""
    return OzAPI(
        api_key=require_env("WARP_API_KEY"),
        base_url=oz_api_base_url(),
        default_headers={
            "X-Warp-Origin-Token": oz_origin_token(),
            "x-oz-api-source": "GITHUB_ACTION",
        },
    )


def build_agent_config(
    *,
    config_name: str,
    workspace: Path,
) -> dict[str, Any]:
    """Build the agent configuration payload sent to the Oz API."""
    environment_id = optional_env("WARP_ENVIRONMENT_ID")
    if not environment_id:
        raise RuntimeError("Missing Oz environment configuration. Set WARP_ENVIRONMENT_ID")

    config: dict[str, Any] = {
        "environment_id": environment_id,
        "name": config_name,
    }
    model_id = optional_env("WARP_AGENT_MODEL")
    if model_id:
        config["model_id"] = model_id

    mcp_raw = optional_env("WARP_AGENT_MCP")
    if mcp_raw:
        config["mcp_servers"] = parse_mcp_servers(mcp_raw, workspace)

    profile = optional_env("WARP_AGENT_PROFILE")
    if profile:
        warning(
            "WARP_AGENT_PROFILE is set, but the Oz Python SDK does not expose CLI profile support. Ignoring it."
        )
    return config


def _normalize_skill_path(skill_name: str) -> str:
    """Normalize a short skill name into a repository-relative skill path."""
    if skill_name.endswith("SKILL.md"):
        return skill_name
    return f".agents/skills/{skill_name}/SKILL.md"


def _workflow_code_root() -> Path:
    """Return the checked-out workflow code root when available."""
    configured_path = optional_env("WORKFLOW_CODE_PATH")
    if configured_path:
        root = Path(configured_path)
        if not root.is_absolute():
            root = workspace() / root
        return root
    return Path(__file__).resolve().parents[3]


def _resolve_skill_location(skill_name: str) -> tuple[str, str, Path]:
    """Resolve a skill to the repo slug, relative path, and on-disk file location."""
    if ":" in skill_name:
        repo, skill_path = skill_name.split(":", 1)
        return repo, skill_path, Path(skill_path)

    skill_path = _normalize_skill_path(skill_name)
    consumer_repo_slug = repo_slug()
    consumer_repo_root = workspace()
    workflow_repo_root = _workflow_code_root()
    workflow_repo_slug = optional_env("WORKFLOW_CODE_REPOSITORY") or consumer_repo_slug

    candidates = [(consumer_repo_slug, consumer_repo_root)]
    if (workflow_repo_slug, workflow_repo_root) != (consumer_repo_slug, consumer_repo_root):
        candidates.append((workflow_repo_slug, workflow_repo_root))

    for candidate_repo_slug, candidate_root in candidates:
        candidate_path = candidate_root / skill_path
        if candidate_path.is_file():
            return candidate_repo_slug, skill_path, candidate_path

    checked_locations = ", ".join(
        str(candidate_root / skill_path) for _candidate_repo_slug, candidate_root in candidates
    )
    raise RuntimeError(
        f"Unable to resolve skill {skill_name!r}. Checked: {checked_locations}"
    )


def skill_file_path(skill_name: str) -> str:
    """Resolve a skill to the workspace-relative file path that the agent should read."""
    _repo_slug, skill_path, resolved_path = _resolve_skill_location(skill_name)
    if ":" in skill_name:
        return skill_path
    try:
        return resolved_path.relative_to(workspace()).as_posix()
    except ValueError:
        return resolved_path.as_posix()


def skill_spec(skill_name: str) -> str:
    """Resolve a skill name into a fully qualified spec, preferring consumer repo overrides."""
    resolved_repo_slug, skill_path, _resolved_path = _resolve_skill_location(skill_name)
    if ":" in skill_name:
        return skill_name
    return f"{resolved_repo_slug}:{skill_path}"


def run_agent(
    *,
    prompt: str,
    skill_name: str | None,
    title: str,
    config: dict[str, Any],
    on_poll: Callable[[Any], None] | None = None,
    poll_interval_seconds: int = 10,
    timeout_seconds: int = 60 * 60,
) -> Any:
    """Run an Oz agent and poll until it reaches a terminal state."""
    client = build_oz_client()
    request: dict[str, Any] = {
        "prompt": prompt,
        "title": title,
        "config": config,
        "team": True,
    }
    if skill_name:
        request["skill"] = skill_spec(skill_name)

    response = client.agent.run(**request)
    run_id = response.run_id
    deadline = time.monotonic() + timeout_seconds
    last_state = None

    while True:
        run = client.agent.runs.retrieve(run_id)
        state = str(run.state)
        if state != last_state:
            notice(f"Oz run {run_id} state: {state}")
            last_state = state
        if on_poll:
            on_poll(run)
        if state in TERMINAL_STATES:
            if state != "SUCCEEDED":
                status = getattr(run, "status_message", None)
                message = getattr(status, "message", None) if status else None
                raise RuntimeError(message or f"Oz run {run_id} finished in state {state}")
            return run
        if time.monotonic() >= deadline:
            raise RuntimeError(f"Oz run {run_id} did not finish before timeout")
        time.sleep(poll_interval_seconds)
