from __future__ import annotations

import json
import os
import time
from typing import Any

from oz_agent_sdk import OzAPI

from oz_automation.context import require_env


TERMINAL_STATES = {"SUCCEEDED", "FAILED", "CANCELLED", "ERROR", "BLOCKED"}


def _normalize_mcp_servers(raw_value: str | None) -> dict[str, Any]:
    if not raw_value:
        return {}
    parsed = json.loads(raw_value)
    if isinstance(parsed, dict) and "mcpServers" in parsed and isinstance(parsed["mcpServers"], dict):
        return parsed["mcpServers"]
    if not isinstance(parsed, dict):
        raise RuntimeError("WARP_AGENT_MCP must decode to a JSON object.")
    return parsed


def _github_mcp_config() -> dict[str, Any]:
    token = os.getenv("GH_TOKEN", "").strip() or os.getenv("GITHUB_TOKEN", "").strip()
    if not token:
        return {}
    return {
        "github": {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-github"],
            "env": {"GITHUB_TOKEN": token},
        }
    }


def build_run_config(*, name: str | None = None, include_github_mcp: bool = True) -> dict[str, Any]:
    config: dict[str, Any] = {
        "environment_id": require_env("WARP_AGENT_ENVIRONMENT_ID"),
    }
    model_id = os.getenv("WARP_AGENT_MODEL", "").strip()
    if model_id:
        config["model_id"] = model_id
    if name:
        config["name"] = name

    mcp_servers = _normalize_mcp_servers(os.getenv("WARP_AGENT_MCP"))
    if include_github_mcp:
        for key, value in _github_mcp_config().items():
            mcp_servers.setdefault(key, value)
    if mcp_servers:
        config["mcp_servers"] = mcp_servers
    return config


def get_client() -> OzAPI:
    return OzAPI(api_key=require_env("WARP_API_KEY"))


def start_run(
    *,
    prompt: str,
    title: str,
    skill: str | None = None,
    config_name: str | None = None,
    include_github_mcp: bool = True,
) -> str:
    body: dict[str, Any] = {
        "prompt": prompt,
        "title": title,
        "config": build_run_config(name=config_name, include_github_mcp=include_github_mcp),
    }
    if skill:
        body["skill"] = skill
    response = get_client().agent.run(**body)
    return response.run_id


def get_run(run_id: str) -> Any:
    return get_client().agent.runs.retrieve(run_id)


def wait_for_run(
    run_id: str,
    *,
    poll_interval_seconds: int = 10,
    timeout_seconds: int = 60 * 60,
) -> Any:
    started = time.monotonic()
    latest = get_run(run_id)
    while latest.state not in TERMINAL_STATES:
        if time.monotonic() - started > timeout_seconds:
            raise TimeoutError(f"Oz run {run_id} did not complete within {timeout_seconds} seconds.")
        time.sleep(poll_interval_seconds)
        latest = get_run(run_id)
    return latest


def get_session_link(run: Any) -> str:
    return getattr(run, "session_link", None) or ""


def get_pull_request_urls(run: Any) -> list[str]:
    urls: list[str] = []
    for artifact in getattr(run, "artifacts", None) or []:
        if getattr(artifact, "artifact_type", None) == "PULL_REQUEST":
            data = getattr(artifact, "data", None)
            url = getattr(data, "url", None) if data else None
            if url:
                urls.append(url)
    return urls
