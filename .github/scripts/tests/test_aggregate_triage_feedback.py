"""Tests for ``aggregate_triage_feedback._maintainer_comments``.

The update-triage aggregator filters comments to those from maintainers
based on ``author_association``. GitHub's association field is scoped to
the repository, so legitimate org members can surface as ``CONTRIBUTOR``
(e.g. private org membership). The aggregator must fall back to an org
membership probe in those cases so maintainer context is not silently
dropped during the update-triage self-improvement loop.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock


def _load_module():
    repo_root = Path(__file__).resolve().parents[3]
    script_path = (
        repo_root
        / ".agents"
        / "skills"
        / "update-triage"
        / "scripts"
        / "aggregate_triage_feedback.py"
    )
    spec = importlib.util.spec_from_file_location(
        "aggregate_triage_feedback", script_path
    )
    assert spec and spec.loader  # for type checkers
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("aggregate_triage_feedback", module)
    spec.loader.exec_module(module)
    return module


def _recent_iso(minutes_ago: int = 60) -> str:
    when = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


class MaintainerCommentsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = _load_module()
        self.cutoff = datetime.now(timezone.utc) - timedelta(days=1)

    def test_keeps_static_trusted_associations(self) -> None:
        comments = [
            {
                "author_association": "MEMBER",
                "created_at": _recent_iso(),
                "body": "m",
                "user": {"login": "alice"},
            },
            {
                "author_association": "OWNER",
                "created_at": _recent_iso(),
                "body": "o",
                "user": {"login": "owen"},
            },
        ]
        with mock.patch.object(subprocess, "run") as mock_run:
            selected = self.mod._maintainer_comments(
                comments,
                self.cutoff,
                org="warpdotdev",
                membership_cache={},
            )
        # Static allowlist should not trigger the gh subprocess probe.
        mock_run.assert_not_called()
        self.assertEqual([c["author"] for c in selected], ["alice", "owen"])

    def test_promotes_contributor_that_is_org_member(self) -> None:
        """GitHub may report a private org member as CONTRIBUTOR; the
        aggregator must fall back to ``gh api /orgs/{org}/members/{login}``
        so maintainer feedback is still collected.
        """
        comments = [
            {
                "author_association": "CONTRIBUTOR",
                "created_at": _recent_iso(),
                "body": "actually a maintainer",
                "user": {"login": "safia"},
            },
            {
                "author_association": "CONTRIBUTOR",
                "created_at": _recent_iso(),
                "body": "drive-by",
                "user": {"login": "outsider"},
            },
        ]

        def fake_run(cmd, *args, **kwargs):
            # ``gh api --silent /orgs/warpdotdev/members/<login>``
            login = cmd[-1].rsplit("/", 1)[-1]
            result = mock.Mock()
            result.returncode = 0 if login == "safia" else 1
            result.stdout = ""
            result.stderr = ""
            return result

        with mock.patch.object(subprocess, "run", side_effect=fake_run):
            selected = self.mod._maintainer_comments(
                comments,
                self.cutoff,
                org="warpdotdev",
                membership_cache={},
            )
        self.assertEqual([c["author"] for c in selected], ["safia"])

    def test_membership_cache_prevents_repeated_probes(self) -> None:
        comments = [
            {
                "author_association": "CONTRIBUTOR",
                "created_at": _recent_iso(),
                "body": "first",
                "user": {"login": "safia"},
            },
            {
                "author_association": "CONTRIBUTOR",
                "created_at": _recent_iso(),
                "body": "second",
                "user": {"login": "safia"},
            },
            {
                "author_association": "CONTRIBUTOR",
                "created_at": _recent_iso(),
                "body": "third (case)",
                "user": {"login": "Safia"},
            },
        ]
        mock_result = mock.Mock()
        mock_result.returncode = 0
        with mock.patch.object(
            subprocess, "run", return_value=mock_result
        ) as mock_run:
            selected = self.mod._maintainer_comments(
                comments,
                self.cutoff,
                org="warpdotdev",
                membership_cache={},
            )
        # All three kept; only one subprocess probe should have run
        # thanks to the shared case-insensitive cache.
        self.assertEqual(len(selected), 3)
        self.assertEqual(mock_run.call_count, 1)


if __name__ == "__main__":
    unittest.main()
