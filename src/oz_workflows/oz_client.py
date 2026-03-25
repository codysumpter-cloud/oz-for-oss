from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from oz_agent_sdk import OzAPI

from .actions import notice, warning
from .env import optional_env, parse_mcp_servers, repo_slug, require_env


TERMINAL_STATES = {"SUCCEEDED", "FAILED", "ERROR", "CANCELLED"}


def build_oz_client() -> OzAPI:
    return OzAPI(
        api_key=require_env("WARP_API_KEY"),
        base_url="https://staging.warp.dev/api/v1",
        default_headers={
            "X-Warp-Origin-Token": require_env("STAGING_ORIGIN_TOKEN"),
        },
    )


def build_agent_config(
    *,
    config_name: str,
    workspace: Path,
    environment_env_names: list[str],
) -> dict[str, Any]:
    environment_id = ""
    for env_name in environment_env_names:
        value = optional_env(env_name)
        if value:
            environment_id = value
            break
    if not environment_id:
        raise RuntimeError(
            f"Missing Oz environment configuration. Set one of: {', '.join(environment_env_names)}"
        )

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


def skill_spec(skill_name: str) -> str:
    if ":" in skill_name:
        return skill_name
    skill_path = skill_name
    if not skill_path.endswith("SKILL.md"):
        skill_path = f".agents/skills/{skill_name}/SKILL.md"
    return f"{repo_slug()}:{skill_path}"


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
