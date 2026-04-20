"""Tests for ``aggregate_dedupe_feedback.build_payload``.

The aggregator intentionally restricts itself to issues GitHub recorded as
closed with the *duplicate* close reason and resolves the canonical issue
each one was closed against via the ``marked_as_duplicate`` event on the
issue timeline. These tests patch the tiny ``_gh_api`` shim used by the
script so we can exercise the filtering and canonical-resolution logic
without hitting GitHub.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock


def _load_aggregator_module():
    repo_root = Path(__file__).resolve().parents[3]
    script_path = (
        repo_root
        / ".agents"
        / "skills"
        / "update-dedupe"
        / "scripts"
        / "aggregate_dedupe_feedback.py"
    )
    spec = importlib.util.spec_from_file_location(
        "aggregate_dedupe_feedback", script_path
    )
    assert spec and spec.loader  # for type checkers
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("aggregate_dedupe_feedback", module)
    spec.loader.exec_module(module)
    return module


def _recent_iso(minutes_ago: int = 60) -> str:
    when = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def _old_iso(days_ago: int = 60) -> str:
    when = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


class BuildPayloadTest(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = _load_aggregator_module()

    def _stub_gh_api(self, closed_issues, timeline_by_issue):
        def fake(args):
            # Closed-issues listing uses a ``repos/<repo>/issues?state=closed...`` path.
            joined = " ".join(args)
            if "/issues?" in joined:
                return closed_issues
            # Timeline lookups are ``repos/<repo>/issues/<n>/timeline``.
            for num, events in timeline_by_issue.items():
                if f"/issues/{num}/timeline" in joined:
                    return events
            return []

        return fake

    def test_includes_only_state_reason_duplicate_issues(self) -> None:
        closed_issues = [
            {
                "number": 10,
                "title": "Dupe",
                "html_url": "https://github.test/acme/widgets/issues/10",
                "closed_at": _recent_iso(),
                "state_reason": "duplicate",
                "labels": [{"name": "duplicate"}],
            },
            {
                "number": 11,
                "title": "Completed",
                "html_url": "https://github.test/acme/widgets/issues/11",
                "closed_at": _recent_iso(),
                "state_reason": "completed",
            },
            {
                "number": 12,
                "title": "Not planned, not a dupe",
                "html_url": "https://github.test/acme/widgets/issues/12",
                "closed_at": _recent_iso(),
                "state_reason": "not_planned",
                "labels": [{"name": "wontfix"}],
            },
            {
                "number": 13,
                "title": "Legacy dup-labeled but no state reason",
                "html_url": "https://github.test/acme/widgets/issues/13",
                "closed_at": _recent_iso(),
                "state_reason": "",
                "labels": [{"name": "duplicate"}],
            },
        ]
        timeline = {
            10: [
                {
                    "event": "marked_as_duplicate",
                    "new_issue": {
                        "number": 5,
                        "html_url": "https://github.test/acme/widgets/issues/5",
                    },
                }
            ]
        }
        fake_gh_api = self._stub_gh_api(closed_issues, timeline)
        with mock.patch.object(self.mod, "_gh_api", side_effect=fake_gh_api):
            payload = self.mod.build_payload("acme/widgets", days=7)
        numbers = [r["number"] for r in payload["closed_as_duplicate"]]
        self.assertEqual(numbers, [10])
        self.assertEqual(payload["closed_as_duplicate"][0]["canonical_issue_number"], 5)

    def test_ignores_issues_closed_before_cutoff(self) -> None:
        closed_issues = [
            {
                "number": 20,
                "title": "Old dupe",
                "html_url": "https://github.test/acme/widgets/issues/20",
                "closed_at": _old_iso(),
                "state_reason": "duplicate",
            }
        ]
        fake_gh_api = self._stub_gh_api(closed_issues, {})
        with mock.patch.object(self.mod, "_gh_api", side_effect=fake_gh_api):
            payload = self.mod.build_payload("acme/widgets", days=7)
        self.assertEqual(payload["closed_as_duplicate"], [])

    def test_canonical_is_none_when_no_timeline_link(self) -> None:
        closed_issues = [
            {
                "number": 30,
                "title": "Duplicate with no link",
                "html_url": "https://github.test/acme/widgets/issues/30",
                "closed_at": _recent_iso(),
                "state_reason": "duplicate",
            }
        ]
        # Timeline contains unrelated events but no marked_as_duplicate.
        timeline = {
            30: [
                {"event": "labeled", "label": {"name": "duplicate"}},
                {"event": "closed"},
            ]
        }
        fake_gh_api = self._stub_gh_api(closed_issues, timeline)
        with mock.patch.object(self.mod, "_gh_api", side_effect=fake_gh_api):
            payload = self.mod.build_payload("acme/widgets", days=7)
        record = payload["closed_as_duplicate"][0]
        self.assertEqual(record["number"], 30)
        self.assertIsNone(record["canonical_issue_number"])
        self.assertIsNone(record["canonical_issue_url"])

    def test_skips_pull_requests(self) -> None:
        closed_issues = [
            {
                "number": 40,
                "title": "PR closed as duplicate",
                "html_url": "https://github.test/acme/widgets/pull/40",
                "closed_at": _recent_iso(),
                "state_reason": "duplicate",
                "pull_request": {"url": "https://example.test/pr/40"},
            }
        ]
        fake_gh_api = self._stub_gh_api(closed_issues, {})
        with mock.patch.object(self.mod, "_gh_api", side_effect=fake_gh_api):
            payload = self.mod.build_payload("acme/widgets", days=7)
        self.assertEqual(payload["closed_as_duplicate"], [])


if __name__ == "__main__":
    unittest.main()
