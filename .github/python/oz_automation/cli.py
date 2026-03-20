from __future__ import annotations

import argparse

from oz_automation.commands import (
    comment_on_unready_issue,
    create_implementation_from_issue,
    create_plan_from_issue,
    enforce_pr_issue_state,
    resolve_review_context,
    review_pr,
    validate,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="oz_automation")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("comment-on-unready-issue")
    subparsers.add_parser("resolve-review-context")
    subparsers.add_parser("enforce-pr-issue-state")
    subparsers.add_parser("review-pr")
    subparsers.add_parser("create-plan-from-issue")
    subparsers.add_parser("create-implementation-from-issue")
    subparsers.add_parser("validate")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    command_map = {
        "comment-on-unready-issue": comment_on_unready_issue.main,
        "resolve-review-context": resolve_review_context.main,
        "enforce-pr-issue-state": enforce_pr_issue_state.main,
        "review-pr": review_pr.main,
        "create-plan-from-issue": create_plan_from_issue.main,
        "create-implementation-from-issue": create_implementation_from_issue.main,
        "validate": validate.main,
    }
    return command_map[args.command]()
