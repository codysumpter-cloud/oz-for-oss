#!/usr/bin/env python3
"""Lightweight mock server for GitHub REST API and Warp API.

Used with nektos/act to run GitHub Actions workflows locally without
hitting real external APIs. The server intercepts HTTP calls from the
Python workflow scripts and returns pre-configured responses.

Usage
-----
Start the server before running act:

    python tools/mock_api_server.py --port 8080 --scenario triage-new-issue

Then point act at the server:

    GH_TOKEN=mock-token \
    WARP_API_BASE_URL=http://localhost:8080/warp-api \
    GITHUB_API_URL=http://localhost:8080 \
    act issues -e tools/act/events/issue_opened.json --secret-file tools/act/.secrets

Scenarios
---------
Each scenario is a Python dict that configures the responses the server
returns. You can add new scenarios in the SCENARIOS dict below.

  triage-new-issue      : New issue opened, triage agent succeeds
  needs-info-reply      : Reporter replies to needs-info question
  pr-opened             : PR opened against a ready-to-implement issue
  unready-assigned      : Issue assigned without ready-to-spec/implement label

The server writes a JSON log of all received requests to /tmp/mock_requests.jsonl
so act tests can assert on what calls were made.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

REQUEST_LOG = Path("/tmp/mock_requests.jsonl")


# ---------------------------------------------------------------------------
# Helper to build minimal GitHub API response shapes
# ---------------------------------------------------------------------------

def _label(name: str, color: str = "D73A4A") -> dict:
    return {"id": abs(hash(name)), "name": name, "color": color, "description": ""}


def _user(login: str, *, type_: str = "User") -> dict:
    return {"login": login, "id": abs(hash(login)), "type": type_}


def _issue(
    number: int,
    *,
    title: str = "Test issue",
    body: str = "Issue body",
    labels: list[str] | None = None,
    state: str = "open",
    user_login: str = "reporter",
    assignees: list[str] | None = None,
) -> dict:
    return {
        "number": number,
        "title": title,
        "body": body,
        "state": state,
        "labels": [_label(l) for l in (labels or [])],
        "user": _user(user_login),
        "assignees": [_user(l) for l in (assignees or [])],
        "created_at": "2026-04-24T00:00:00Z",
        "updated_at": "2026-04-24T00:00:00Z",
        "html_url": f"https://github.com/testorg/testrepo/issues/{number}",
        "comments": 0,
        "pull_request": None,
    }


def _comment(id_: int, body: str, *, user_login: str = "oz-agent[bot]") -> dict:
    return {
        "id": id_,
        "body": body,
        "user": _user(user_login, type_="Bot"),
        "author_association": "NONE",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def _run_item(
    run_id: str,
    *,
    state: str = "SUCCEEDED",
    session_link: str | None = None,
) -> dict:
    return {
        "run_id": run_id,
        "state": state,
        "title": f"Agent run {run_id}",
        "prompt": "",
        "task_id": f"task-{run_id}",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "session_link": session_link
        or f"https://app.warp.dev/session/{run_id}",
        "artifacts": [],
    }


def _artifact_entry(
    uid: str, filename: str
) -> dict:
    return {
        "artifact_type": "FILE",
        "data": {
            "artifact_uid": uid,
            "filename": filename,
        },
    }


# ---------------------------------------------------------------------------
# Scenario definitions
# ---------------------------------------------------------------------------

# The "state" dict is mutated by request handlers as the server processes
# sequential requests (e.g. "run created" → "run polled" → "artifact ready").

def _make_triage_scenario(
    issue_number: int = 42,
    *,
    issue_labels: list[str] | None = None,
    triage_result: dict | None = None,
) -> dict:
    run_id = f"run-{uuid.uuid4().hex[:8]}"
    artifact_uid = f"art-{uuid.uuid4().hex[:8]}"
    download_url_path = f"/artifact-downloads/{artifact_uid}"

    default_triage_result = triage_result or {
        "summary": "widget crashes on startup due to null pointer",
        "labels": ["bug", "repro:high"],
        "reproducibility": {"level": "high", "reasoning": "Consistently reproducible"},
        "root_cause": {
            "summary": "Null pointer in widget initializer",
            "confidence": "medium",
            "relevant_files": ["src/widget.py"],
        },
        "sme_candidates": [],
        "selected_template_path": "",
        "issue_body": "## Analysis\n\nThe widget crashes on startup.",
        "follow_up_questions": [],
        "duplicate_of": [],
    }

    state = {
        "run_id": run_id,
        "artifact_uid": artifact_uid,
        "download_url_path": download_url_path,
        "triage_result": default_triage_result,
        "issue_number": issue_number,
        "issue_labels": issue_labels or [],
        "created_comments": [],
        "added_labels": [],
    }

    run_with_artifact = _run_item(run_id)
    run_with_artifact["artifacts"] = [
        _artifact_entry(artifact_uid, "triage_result.json")
    ]

    return {
        "state": state,
        "routes": {
            # GitHub API: list labels
            f"GET /repos/testorg/testrepo/labels": lambda s: [
                _label(n) for n in [
                    "bug", "enhancement", "needs-info", "triaged",
                    "duplicate", "repro:unknown", "repro:low",
                    "repro:medium", "repro:high",
                ]
            ],
            # GitHub API: get issue
            f"GET /repos/testorg/testrepo/issues/{issue_number}": lambda s: _issue(
                issue_number, labels=s["issue_labels"]
            ),
            # GitHub API: list open issues (for lookback scan)
            "GET /repos/testorg/testrepo/issues": lambda s: [
                _issue(issue_number, labels=s["issue_labels"])
            ],
            # GitHub API: get issue comments
            f"GET /repos/testorg/testrepo/issues/{issue_number}/comments": lambda s: s["created_comments"],
            # GitHub API: create comment
            f"POST /repos/testorg/testrepo/issues/{issue_number}/comments": lambda s, body: (
                s["created_comments"].append(_comment(len(s["created_comments"]) + 1, body.get("body", ""))) or
                _comment(len(s["created_comments"]), body.get("body", ""))
            ),
            # GitHub API: add labels
            f"POST /repos/testorg/testrepo/issues/{issue_number}/labels": lambda s, body: (
                s["added_labels"].extend(body if isinstance(body, list) else body.get("labels", [])) or
                [_label(l) for l in s["added_labels"]]
            ),
            # GitHub API: get org membership (trust check)
            "GET /orgs/testorg/members/contributor": lambda s: ("", 204),
            # Warp API: start agent run
            "POST /warp-api/agent/run": lambda s: {
                "run_id": s["run_id"],
                "state": "QUEUED",
            },
            # Warp API: poll run (already succeeded with artifact)
            f"GET /warp-api/agent/runs/{run_id}": lambda s: run_with_artifact,
            # Warp API: get artifact info
            f"GET /warp-api/agent/{artifact_uid}": lambda s: {
                "data": {
                    "artifact_uid": artifact_uid,
                    "filename": "triage_result.json",
                    "download_url": f"http://localhost:__PORT__{download_url_path}",
                }
            },
            # Artifact download endpoint
            f"GET {download_url_path}": lambda s: json.dumps(s["triage_result"]),
        },
    }


SCENARIOS: dict[str, dict] = {
    "triage-new-issue": _make_triage_scenario(
        issue_number=42, issue_labels=[]
    ),
    "needs-info-reply": _make_triage_scenario(
        issue_number=42,
        issue_labels=["needs-info", "bug", "repro:unknown"],
        triage_result={
            "summary": "reproduced on macOS 14.2",
            "labels": ["bug", "repro:high"],
            "reproducibility": {"level": "high", "reasoning": "Confirmed by reporter"},
            "root_cause": {"summary": "Platform-specific issue", "confidence": "medium", "relevant_files": []},
            "sme_candidates": [],
            "selected_template_path": "",
            "issue_body": "## Updated Analysis\n\nReproduced on macOS 14.2.",
            "follow_up_questions": [],
            "duplicate_of": [],
        },
    ),
    "unready-assigned": {
        "state": {
            "issue_number": 42,
            "created_comments": [],
        },
        "routes": {
            "GET /repos/testorg/testrepo/issues/42": lambda s: _issue(42, labels=[]),
            "GET /repos/testorg/testrepo/issues/42/comments": lambda s: s["created_comments"],
            "POST /repos/testorg/testrepo/issues/42/comments": lambda s, body: (
                s["created_comments"].append(_comment(len(s["created_comments"]) + 1, body.get("body", ""))) or
                _comment(len(s["created_comments"]), body.get("body", ""))
            ),
            "DELETE /repos/testorg/testrepo/issues/42/assignees": lambda s, body: {"assignees": []},
        },
    },
}


# ---------------------------------------------------------------------------
# HTTP request handler
# ---------------------------------------------------------------------------


class MockHandler(BaseHTTPRequestHandler):
    scenario: dict = {}
    port: int = 8080

    def log_message(self, fmt: str, *args: Any) -> None:
        log.info("  %s", fmt % args)

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length) if length else b""

    def _write_json(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _write_text(self, text: str, status: int = 200) -> None:
        body = text.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _log_request(self, method: str, path: str, body: Any) -> None:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "method": method,
            "path": path,
            "body": body,
        }
        with REQUEST_LOG.open("a") as f:
            f.write(json.dumps(entry) + "\n")

    def _handle(self, method: str) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        raw_body = self._read_body()
        try:
            body = json.loads(raw_body) if raw_body else {}
        except ValueError:
            body = raw_body.decode()
        self._log_request(method, path, body)

        routes = self.scenario.get("routes", {})
        state = self.scenario.get("state", {})

        route_key = f"{method} {path}"
        handler = routes.get(route_key)

        if handler is None:
            log.warning("No mock route for %s — returning 404", route_key)
            self._write_json({"message": f"No mock for {route_key}"}, 404)
            return

        try:
            import inspect
            sig = inspect.signature(handler)
            if len(sig.parameters) == 1:
                result = handler(state)
            else:
                result = handler(state, body)
        except Exception as exc:
            log.exception("Mock handler %s raised: %s", route_key, exc)
            self._write_json({"message": str(exc)}, 500)
            return

        # Handler can return (text, status) for special cases
        if isinstance(result, tuple) and len(result) == 2:
            text, status = result
            if status == 204:
                self.send_response(204)
                self.end_headers()
            else:
                self._write_text(str(text), status)
            return

        if isinstance(result, str):
            # Replace port placeholder in artifact download URLs
            result = result.replace("__PORT__", str(self.port))
            self._write_text(result)
            return

        if result is None:
            self.send_response(204)
            self.end_headers()
            return

        self._write_json(result)

    def do_GET(self) -> None:
        self._handle("GET")

    def do_POST(self) -> None:
        self._handle("POST")

    def do_PATCH(self) -> None:
        self._handle("PATCH")

    def do_DELETE(self) -> None:
        self._handle("DELETE")

    def do_PUT(self) -> None:
        self._handle("PUT")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Mock GitHub/Warp API server for act tests")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument(
        "--scenario",
        default="triage-new-issue",
        choices=list(SCENARIOS),
        help="Test scenario to configure responses for",
    )
    parser.add_argument(
        "--list-scenarios",
        action="store_true",
        help="Print available scenarios and exit",
    )
    args = parser.parse_args()

    if args.list_scenarios:
        for name in SCENARIOS:
            print(name)
        return

    REQUEST_LOG.write_text("")  # clear previous log

    scenario = SCENARIOS[args.scenario]
    # Resolve port placeholder in any pre-rendered URLs
    MockHandler.scenario = scenario
    MockHandler.port = args.port

    server = HTTPServer(("0.0.0.0", args.port), MockHandler)
    log.info("Mock API server listening on port %d (scenario: %s)", args.port, args.scenario)
    log.info("Request log: %s", REQUEST_LOG)
    log.info("Stop with Ctrl-C")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
