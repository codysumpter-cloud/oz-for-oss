from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from .workflow_paths import preferred_repo_roots


CONFIG_RELATIVE_PATH = Path(".github/oz/config.yml")
_GITHUB_HANDLE_PATTERN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})")


@dataclass(frozen=True)
class SelfImprovementConfig:
    reviewers: list[str] | None
    base_branch: str | None


@dataclass(frozen=True)
class WorkflowConfigDocument:
    path: Path
    data: dict[str, Any]


def resolve_repo_config_path(workspace_root: Path) -> Path | None:
    """Resolve the first available workflow config path for *workspace_root*."""
    for root in preferred_repo_roots(workspace_root):
        candidate = root / CONFIG_RELATIVE_PATH
        if candidate.is_file():
            return candidate.resolve()
    return None


def _fail(config_path: Path, message: str) -> RuntimeError:
    return RuntimeError(f"{config_path}: {message}")


def _normalize_handle(raw_value: Any, *, config_path: Path, source: str) -> str:
    if not isinstance(raw_value, str):
        raise _fail(config_path, f"{source} entries must be strings.")
    value = raw_value.strip()
    if not value:
        raise _fail(config_path, f"{source} entries must not be blank.")
    if value.startswith("@"):
        raise _fail(
            config_path,
            f"{source} entries must be GitHub handles without a leading '@'.",
        )
    if not _GITHUB_HANDLE_PATTERN.fullmatch(value):
        raise _fail(config_path, f"Invalid GitHub handle {value!r} in {source}.")
    return value


def _parse_reviewers_list(
    raw_value: Any,
    *,
    config_path: Path,
    source: str,
) -> list[str]:
    if not isinstance(raw_value, list):
        raise _fail(config_path, f"{source} must be a list of GitHub handles.")
    return [
        _normalize_handle(item, config_path=config_path, source=source)
        for item in raw_value
    ]


def _parse_base_branch(
    raw_value: Any,
    *,
    config_path: Path,
    source: str,
) -> str | None:
    if not isinstance(raw_value, str):
        raise _fail(config_path, f"{source} must be a string branch name or 'auto'.")
    value = raw_value.strip()
    if not value:
        raise _fail(config_path, f"{source} must not be blank.")
    if value == "auto":
        return None
    return value


def _parse_env_reviewers(config_path: Path) -> list[str] | None:
    if "SELF_IMPROVEMENT_REVIEWERS" not in os.environ:
        return None
    raw_value = os.environ["SELF_IMPROVEMENT_REVIEWERS"].strip()
    if not raw_value:
        raise _fail(
            config_path,
            "SELF_IMPROVEMENT_REVIEWERS must be a comma-separated list of handles.",
        )
    return _parse_reviewers_list(
        [part.strip() for part in raw_value.split(",")],
        config_path=config_path,
        source="SELF_IMPROVEMENT_REVIEWERS",
    )


def _parse_env_base_branch(config_path: Path) -> str | None:
    if "SELF_IMPROVEMENT_BASE_BRANCH" not in os.environ:
        return None
    raw_value = os.environ["SELF_IMPROVEMENT_BASE_BRANCH"]
    return _parse_base_branch(
        raw_value,
        config_path=config_path,
        source="SELF_IMPROVEMENT_BASE_BRANCH",
    )


@lru_cache(maxsize=None)
def _load_workflow_config_document_from_path(config_path: Path) -> WorkflowConfigDocument:
    try:
        raw_data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise _fail(config_path, "Invalid YAML in .github/oz/config.yml.") from exc
    except OSError as exc:
        raise _fail(config_path, "Unable to read .github/oz/config.yml.") from exc

    if raw_data is None:
        raw_data = {}
    if not isinstance(raw_data, dict):
        raise _fail(config_path, "The config root must be a YAML mapping.")

    version = raw_data.get("version")
    if version != 1:
        raise _fail(config_path, "Unsupported config version; expected version: 1.")

    return WorkflowConfigDocument(path=config_path, data=raw_data)


def load_workflow_config_document(workspace_root: Path) -> WorkflowConfigDocument:
    """Load and validate the resolved workflow config document once."""
    config_path = resolve_repo_config_path(workspace_root)
    if config_path is None:
        raise RuntimeError(
            "Unable to locate .github/oz/config.yml in either the consuming "
            "repository workspace or the checked-out workflow code."
        )
    return _load_workflow_config_document_from_path(config_path)


def load_self_improvement_config(workspace_root: Path) -> SelfImprovementConfig:
    """Load and validate the resolved self-improvement workflow config."""
    document = load_workflow_config_document(workspace_root)
    config_path = document.path
    raw_data = document.data

    self_improvement = raw_data.get("self_improvement")
    if self_improvement is None:
        self_improvement = {}
    if not isinstance(self_improvement, dict):
        raise _fail(config_path, "self_improvement must be a YAML mapping.")

    unknown_keys = sorted(
        key
        for key in self_improvement.keys()
        if key not in {"reviewers", "base_branch"}
    )
    if unknown_keys:
        raise _fail(
            config_path,
            "Unknown self_improvement keys: " + ", ".join(unknown_keys),
        )

    reviewers: list[str] | None = None
    if "reviewers" in self_improvement:
        reviewers = _parse_reviewers_list(
            self_improvement["reviewers"],
            config_path=config_path,
            source="self_improvement.reviewers",
        )

    base_branch: str | None = None
    if "base_branch" in self_improvement:
        base_branch = _parse_base_branch(
            self_improvement["base_branch"],
            config_path=config_path,
            source="self_improvement.base_branch",
        )

    env_reviewers = _parse_env_reviewers(config_path)
    if env_reviewers is not None:
        reviewers = env_reviewers

    env_base_branch = _parse_env_base_branch(config_path)
    if "SELF_IMPROVEMENT_BASE_BRANCH" in os.environ:
        base_branch = env_base_branch

    return SelfImprovementConfig(reviewers=reviewers, base_branch=base_branch)
