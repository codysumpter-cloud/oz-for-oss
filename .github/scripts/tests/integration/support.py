"""Shared integration-test support for oz-for-oss workflow scripts.

Integration tests exercise the full ``main()`` entry-points of the Python
workflow scripts with only the external API clients mocked:

- PyGitHub (GitHub REST API) is replaced by ``FakeGitHubClient`` and the
  ``FakeRepo``/``FakeIssue``/``FakeComment`` object graph.
- ``run_agent`` and ``poll_for_artifact`` are patched with functions that
  return pre-canned data, making every test deterministic and offline.

The objects here intentionally replicate the minimal PyGitHub surface that
the workflow scripts use so tests verify real call paths rather than just
checking that mocks were invoked.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Generator
from unittest.mock import MagicMock, patch


REPO_OWNER = "testorg"
REPO_NAME = "testrepo"
REPO_SLUG = f"{REPO_OWNER}/{REPO_NAME}"

# ---------------------------------------------------------------------------
# Fake PyGitHub objects
# ---------------------------------------------------------------------------


class FakeLabel:
    """Minimal stand-in for PyGitHub Label."""

    def __init__(self, name: str) -> None:
        self.name = name


class FakeComment:
    """Minimal stand-in for PyGitHub IssueComment."""

    def __init__(
        self,
        *,
        id_: int,
        body: str,
        user_login: str = "oz-agent[bot]",
        author_association: str = "NONE",
    ) -> None:
        self.id = id_
        self.body = body
        self.user = SimpleNamespace(login=user_login, type="Bot")
        self.author_association = author_association
        self.created_at = datetime.now(timezone.utc)
        self._deleted = False

    def edit(self, body: str) -> None:
        self.body = body

    def delete(self) -> None:
        self._deleted = True


class FakeIssue:
    """Minimal stand-in for PyGitHub Issue used in integration tests.

    Records all mutations so tests can assert on them after ``main()`` returns.
    """

    def __init__(
        self,
        number: int,
        *,
        title: str = "Test issue",
        body: str = "Issue description",
        labels: list[str] | None = None,
        user_login: str = "reporter",
        created_at: datetime | None = None,
        pull_request: dict[str, Any] | None = None,
        assignees: list[str] | None = None,
    ) -> None:
        self.number = number
        self.title = title
        self.body = body
        self._labels: list[FakeLabel] = [FakeLabel(l) for l in (labels or [])]
        self.user = SimpleNamespace(login=user_login)
        self.created_at = created_at or (
            datetime.now(timezone.utc) - timedelta(minutes=5)
        )
        self.pull_request = pull_request
        self.assignees: list[Any] = [
            SimpleNamespace(login=login) for login in (assignees or [])
        ]

        # Recorded mutations — checked by test assertions
        self.added_labels: list[str] = []
        self.removed_labels: list[str] = []
        self.removed_assignees: list[str] = []
        self._comments: list[FakeComment] = []
        self._next_comment_id = 1

    @property
    def labels(self) -> list[FakeLabel]:
        return list(self._labels)

    def add_to_labels(self, *names: str) -> None:
        self.added_labels.extend(names)
        self._labels.extend(FakeLabel(n) for n in names)

    def remove_from_labels(self, name: str) -> None:
        self.removed_labels.append(name)
        self._labels = [l for l in self._labels if l.name != name]

    def get_comments(self) -> list[FakeComment]:
        return [c for c in self._comments if not c._deleted]

    def get_comment(self, comment_id: int) -> FakeComment:
        for c in self._comments:
            if c.id == comment_id and not c._deleted:
                return c
        # Mirror PyGitHub's behaviour on missing comment
        from github.GithubException import UnknownObjectException  # type: ignore[import-untyped]
        raise UnknownObjectException(404, {"message": "Not Found"}, {})

    def create_comment(self, body: str) -> FakeComment:
        comment = FakeComment(id_=self._next_comment_id, body=body)
        self._next_comment_id += 1
        self._comments.append(comment)
        return comment

    def remove_from_assignees(self, *logins: str) -> None:
        self.removed_assignees.extend(logins)
        self.assignees = [a for a in self.assignees if a.login not in logins]

    def get_events(self) -> list[Any]:
        return []


class FakeRepo:
    """Minimal stand-in for PyGitHub Repository used in integration tests."""

    def __init__(
        self,
        *,
        labels: list[str] | None = None,
        issues: list[FakeIssue] | None = None,
    ) -> None:
        default_labels = [
            "bug",
            "enhancement",
            "documentation",
            "needs-info",
            "triaged",
            "duplicate",
            "repro:unknown",
            "repro:low",
            "repro:medium",
            "repro:high",
        ]
        self._labels: dict[str, FakeLabel] = {
            name: FakeLabel(name) for name in (labels or default_labels)
        }
        self._issues: dict[int, FakeIssue] = {
            i.number: i for i in (issues or [])
        }
        self.created_labels: list[dict[str, str]] = []

    def get_labels(self) -> list[FakeLabel]:
        return list(self._labels.values())

    def get_label(self, name: str) -> FakeLabel:
        if name not in self._labels:
            from github.GithubException import UnknownObjectException  # type: ignore[import-untyped]
            raise UnknownObjectException(404, {"message": "Label not found"}, {})
        return self._labels[name]

    def get_issue(self, number: int) -> FakeIssue:
        if number not in self._issues:
            from github.GithubException import UnknownObjectException  # type: ignore[import-untyped]
            raise UnknownObjectException(404, {"message": "Not Found"}, {})
        return self._issues[number]

    def get_issues(self, *, state: str = "open", **_: Any) -> list[FakeIssue]:
        return [
            i for i in self._issues.values() if i.pull_request is None
        ]

    def create_label(
        self, *, name: str, color: str = "ffffff", description: str = ""
    ) -> FakeLabel:
        entry = {"name": name, "color": color, "description": description}
        self.created_labels.append(entry)
        label = FakeLabel(name)
        self._labels[name] = label
        return label


class FakeGitHubClient:
    """Minimal stand-in for a PyGitHub ``Github`` instance."""

    def __init__(self, repo: FakeRepo) -> None:
        self.repo = repo

    def get_repo(self, _full_name: str) -> FakeRepo:
        return self.repo

    def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Fake Oz agent run items
# ---------------------------------------------------------------------------


class FakeRunItem:
    """Minimal stand-in for ``oz_agent_sdk.types.agent.RunItem``."""

    def __init__(
        self,
        run_id: str = "fake-run-00001",
        session_link: str = "https://app.warp.dev/session/test",
        state: str = "SUCCEEDED",
    ) -> None:
        self.run_id = run_id
        self.session_link = session_link
        self.state = state
        self.status_message = None
        self.artifacts: list[Any] = []


# ---------------------------------------------------------------------------
# Workspace and environment helpers
# ---------------------------------------------------------------------------

MINIMAL_TRIAGE_CONFIG: dict[str, Any] = {
    "labels": {
        "bug": {"color": "D73A4A", "description": "Something isn't working"},
        "enhancement": {
            "color": "A2EEEF",
            "description": "New feature or request",
        },
        "documentation": {
            "color": "0075CA",
            "description": "Documentation improvements",
        },
        "needs-info": {
            "color": "D876E3",
            "description": "More information requested",
        },
        "triaged": {
            "color": "0E8A16",
            "description": "Reviewed by maintainers",
        },
        "duplicate": {"color": "CFD3D7", "description": "Duplicate issue"},
        "repro:unknown": {
            "color": "CCCCCC",
            "description": "Reproducibility unknown",
        },
        "repro:low": {
            "color": "CCCCCC",
            "description": "Rarely reproducible",
        },
        "repro:medium": {
            "color": "CCCCCC",
            "description": "Sometimes reproducible",
        },
        "repro:high": {
            "color": "B60205",
            "description": "Easily reproducible",
        },
    }
}


class WorkspaceSetup:
    """Context-manager that creates a temporary workspace with config files.

    Usage::

        with WorkspaceSetup(event=issue_opened_payload()) as ws:
            with patch.dict(os.environ, ws.env()):
                main()

        self.assertIn("bug", issue.added_labels)
    """

    def __init__(
        self,
        *,
        config: dict[str, Any] | None = None,
        event: dict[str, Any] | None = None,
        event_name: str = "issues",
    ) -> None:
        self._config = config or MINIMAL_TRIAGE_CONFIG
        self._event = event or {}
        self._event_name = event_name
        self._tmpdir: tempfile.TemporaryDirectory[str] | None = None
        self.path: Path = Path()
        self.event_path: Path = Path()

    def __enter__(self) -> "WorkspaceSetup":
        self._tmpdir = tempfile.TemporaryDirectory()
        root = Path(self._tmpdir.name)
        self.path = root

        # Required triage config
        config_dir = root / ".github" / "issue-triage"
        config_dir.mkdir(parents=True)
        (config_dir / "config.json").write_text(
            json.dumps(self._config), encoding="utf-8"
        )

        # Optional stakeholders file (empty means no configured owners)
        (root / ".github").mkdir(exist_ok=True)
        (root / ".github" / "STAKEHOLDERS").write_text("", encoding="utf-8")

        # GitHub Actions output sinks
        (root / "gha_output.txt").write_text("", encoding="utf-8")
        (root / "gha_summary.txt").write_text("", encoding="utf-8")

        # Event payload
        event_file = root / "event.json"
        event_file.write_text(json.dumps(self._event), encoding="utf-8")
        self.event_path = event_file

        return self

    def __exit__(self, *_: Any) -> None:
        if self._tmpdir:
            self._tmpdir.cleanup()

    def env(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        """Return a minimal set of environment variables for a workflow run."""
        base: dict[str, str] = {
            "GITHUB_REPOSITORY": REPO_SLUG,
            "GITHUB_WORKSPACE": str(self.path),
            "GITHUB_EVENT_PATH": str(self.event_path),
            "GITHUB_EVENT_NAME": self._event_name,
            "GH_TOKEN": "fake-gh-token",
            "WARP_API_KEY": "fake-warp-key",
            "WARP_API_BASE_URL": "https://app.warp.dev/api/v1",
            "WARP_ENVIRONMENT_ID": "test-env-id",
            "GITHUB_OUTPUT": str(self.path / "gha_output.txt"),
            "GITHUB_STEP_SUMMARY": str(self.path / "gha_summary.txt"),
            "LOOKBACK_MINUTES": "60",
        }
        if extra:
            base.update(extra)
        return base

    def read_summary(self) -> str:
        return (self.path / "gha_summary.txt").read_text(encoding="utf-8")

    def read_output(self) -> str:
        return (self.path / "gha_output.txt").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Common GitHub event payload factories
# ---------------------------------------------------------------------------


def issue_opened_event(
    *,
    number: int = 42,
    title: str = "Widget crashes on startup",
    body: str = "Steps to reproduce:\n1. Open widget\n2. It crashes",
    user_login: str = "reporter",
    labels: list[str] | None = None,
    sender_login: str = "reporter",
) -> dict[str, Any]:
    return {
        "action": "opened",
        "issue": {
            "number": number,
            "title": title,
            "body": body,
            "state": "open",
            "labels": [{"name": l} for l in (labels or [])],
            "user": {"login": user_login, "type": "User"},
            "created_at": (
                datetime.now(timezone.utc) - timedelta(minutes=5)
            ).isoformat(),
            "assignees": [],
        },
        "sender": {"login": sender_login, "type": "User"},
    }


def issue_comment_event(
    *,
    issue_number: int = 42,
    issue_labels: list[str] | None = None,
    comment_body: str = "I'm on macOS 14.2, reproduced every time.",
    commenter_login: str = "reporter",
    issue_user_login: str = "reporter",
    author_association: str = "NONE",
    pull_request: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "action": "created",
        "issue": {
            "number": issue_number,
            "title": "Widget crashes on startup",
            "body": "Original report",
            "state": "open",
            "labels": [{"name": l} for l in (issue_labels or [])],
            "user": {"login": issue_user_login, "type": "User"},
            "pull_request": pull_request,
            "assignees": [],
        },
        "comment": {
            "id": 1001,
            "body": comment_body,
            "user": {"login": commenter_login, "type": "User"},
            "author_association": author_association,
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
        "sender": {"login": commenter_login, "type": "User"},
    }


def pr_opened_event(
    *,
    pr_number: int = 10,
    title: str = "Fix widget crash",
    body: str = "Closes #42",
    author_login: str = "contributor",
    base_ref: str = "main",
    head_ref: str = "fix/widget-crash",
    draft: bool = False,
    labels: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "action": "opened",
        "number": pr_number,
        "pull_request": {
            "number": pr_number,
            "title": title,
            "body": body,
            "state": "open",
            "draft": draft,
            "html_url": f"https://github.com/{REPO_SLUG}/pull/{pr_number}",
            "user": {"login": author_login, "type": "User"},
            "head": {"ref": head_ref, "sha": "abc1234"},
            "base": {"ref": base_ref},
            "labels": [{"name": l} for l in (labels or [])],
            "author_association": "CONTRIBUTOR",
        },
        "sender": {"login": author_login, "type": "User"},
    }


# ---------------------------------------------------------------------------
# Canned triage result payloads
# ---------------------------------------------------------------------------


def triage_result_bug(
    *,
    labels: list[str] | None = None,
    follow_up_questions: list[Any] | None = None,
    duplicate_of: list[Any] | None = None,
) -> dict[str, Any]:
    return {
        "summary": "widget crashes on startup due to null pointer",
        "labels": labels or ["bug", "repro:high"],
        "reproducibility": {"level": "high", "reasoning": "Consistently reproducible"},
        "root_cause": {
            "summary": "Null pointer in widget initializer",
            "confidence": "medium",
            "relevant_files": ["src/widget.py"],
        },
        "sme_candidates": [],
        "selected_template_path": "",
        "issue_body": "## Bug Analysis\n\nThe widget crashes on startup.",
        "follow_up_questions": follow_up_questions or [],
        "duplicate_of": duplicate_of or [],
    }


def triage_result_needs_info(
    *,
    labels: list[str] | None = None,
    questions: list[Any] | None = None,
) -> dict[str, Any]:
    return {
        "summary": "unable to reproduce without OS version and widget config",
        "labels": labels or ["bug", "repro:unknown"],
        "reproducibility": {"level": "unknown", "reasoning": "Missing env details"},
        "root_cause": {
            "summary": "Unknown without additional context",
            "confidence": "low",
            "relevant_files": [],
        },
        "sme_candidates": [],
        "selected_template_path": "",
        "issue_body": "## Initial Analysis\n\nMore information needed.",
        "follow_up_questions": questions
        or [
            {
                "question": "What OS version are you running?",
                "reasoning": "The crash may be platform-specific",
            }
        ],
        "duplicate_of": [],
    }
