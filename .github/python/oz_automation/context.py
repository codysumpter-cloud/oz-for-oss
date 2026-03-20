from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RepoRef:
    owner: str
    repo: str

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.repo}"


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def get_event_name() -> str:
    return require_env("GITHUB_EVENT_NAME")


def load_event() -> dict[str, Any]:
    event_path = Path(require_env("GITHUB_EVENT_PATH"))
    return json.loads(event_path.read_text(encoding="utf-8"))


def get_repo_ref(event: dict[str, Any]) -> RepoRef:
    repository = os.getenv("GITHUB_REPOSITORY", "").strip()
    if repository:
        owner, repo = repository.split("/", 1)
        return RepoRef(owner=owner, repo=repo)

    repo_payload = event.get("repository") or {}
    owner_payload = repo_payload.get("owner") or {}
    owner = owner_payload.get("login") or owner_payload.get("name")
    repo = repo_payload.get("name")
    if not owner or not repo:
        raise RuntimeError("Unable to determine repository from GitHub context.")
    return RepoRef(owner=owner, repo=repo)
