from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def optional_env(name: str) -> str:
    return os.environ.get(name, "").strip()


def repo_slug() -> str:
    return require_env("GITHUB_REPOSITORY")


def repo_parts() -> tuple[str, str]:
    owner, repo = repo_slug().split("/", 1)
    return owner, repo


def workspace() -> Path:
    return Path(os.environ.get("GITHUB_WORKSPACE") or os.getcwd())


def load_event() -> dict[str, Any]:
    event_path = require_env("GITHUB_EVENT_PATH")
    with open(event_path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def read_text_if_exists(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def parse_mcp_servers(raw_value: str, cwd: Path) -> dict[str, Any] | None:
    raw = raw_value.strip()
    if not raw:
        return None

    candidate_path = Path(raw)
    if not candidate_path.is_absolute():
        candidate_path = cwd / candidate_path

    if candidate_path.exists():
        raw = candidate_path.read_text(encoding="utf-8")

    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise RuntimeError("WARP_AGENT_MCP must decode to a JSON object")
    return parsed
