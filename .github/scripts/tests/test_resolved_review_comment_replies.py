from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from oz_workflows.helpers import (
    _resolve_review_thread_ids_for_comments,
    post_resolved_review_comment_replies,
)


def _make_github_client_with_graphql(
    *,
    query_responses: list[tuple[dict, dict]],
    mutation_responses: list[tuple[dict, dict]] | None = None,
) -> MagicMock:
    """Build a MagicMock Github client whose private requester replays GraphQL calls."""
    client = MagicMock()
    requester = MagicMock()
    query_mock = MagicMock(side_effect=list(query_responses))
    mutation_mock = MagicMock(
        side_effect=list(mutation_responses) if mutation_responses else []
    )
    requester.graphql_query = query_mock
    requester.graphql_named_mutation = mutation_mock
    # The helper reads ``github_client.requester`` (the public requester
    # property exposed by PyGithub's ``Github`` client).
    client.requester = requester
    return client


class ResolveReviewThreadIdsForCommentsTest(unittest.TestCase):
    def test_returns_mapping_for_matching_thread(self) -> None:
        response = (
            {},
            {
                "data": {
                    "repository": {
                        "pullRequest": {
                            "reviewThreads": {
                                "pageInfo": {
                                    "hasNextPage": False,
                                    "endCursor": None,
                                },
                                "nodes": [
                                    {
                                        "id": "RT_1",
                                        "isResolved": False,
                                        "comments": {
                                            "nodes": [
                                                {"databaseId": 111},
                                                {"databaseId": 112},
                                            ]
                                        },
                                    },
                                    {
                                        "id": "RT_2",
                                        "isResolved": False,
                                        "comments": {
                                            "nodes": [{"databaseId": 222}]
                                        },
                                    },
                                ],
                            }
                        }
                    }
                }
            },
        )
        client = _make_github_client_with_graphql(query_responses=[response])
        mapping = _resolve_review_thread_ids_for_comments(
            client, "acme", "widgets", 42, [112, 222]
        )
        self.assertEqual(mapping, {112: "RT_1", 222: "RT_2"})

    def test_returns_empty_mapping_when_no_ids_requested(self) -> None:
        client = _make_github_client_with_graphql(query_responses=[])
        self.assertEqual(
            _resolve_review_thread_ids_for_comments(
                client, "acme", "widgets", 1, []
            ),
            {},
        )

    def test_paginates_until_all_ids_found(self) -> None:
        page_one = (
            {},
            {
                "data": {
                    "repository": {
                        "pullRequest": {
                            "reviewThreads": {
                                "pageInfo": {
                                    "hasNextPage": True,
                                    "endCursor": "cursor-1",
                                },
                                "nodes": [
                                    {
                                        "id": "RT_1",
                                        "isResolved": False,
                                        "comments": {
                                            "nodes": [{"databaseId": 111}]
                                        },
                                    }
                                ],
                            }
                        }
                    }
                }
            },
        )
        page_two = (
            {},
            {
                "data": {
                    "repository": {
                        "pullRequest": {
                            "reviewThreads": {
                                "pageInfo": {
                                    "hasNextPage": False,
                                    "endCursor": None,
                                },
                                "nodes": [
                                    {
                                        "id": "RT_2",
                                        "isResolved": False,
                                        "comments": {
                                            "nodes": [{"databaseId": 222}]
                                        },
                                    }
                                ],
                            }
                        }
                    }
                }
            },
        )
        client = _make_github_client_with_graphql(
            query_responses=[page_one, page_two]
        )
        mapping = _resolve_review_thread_ids_for_comments(
            client, "acme", "widgets", 42, [111, 222]
        )
        self.assertEqual(mapping, {111: "RT_1", 222: "RT_2"})

    def test_returns_partial_mapping_when_some_ids_missing(self) -> None:
        response = (
            {},
            {
                "data": {
                    "repository": {
                        "pullRequest": {
                            "reviewThreads": {
                                "pageInfo": {
                                    "hasNextPage": False,
                                    "endCursor": None,
                                },
                                "nodes": [
                                    {
                                        "id": "RT_1",
                                        "isResolved": False,
                                        "comments": {
                                            "nodes": [{"databaseId": 111}]
                                        },
                                    }
                                ],
                            }
                        }
                    }
                }
            },
        )
        client = _make_github_client_with_graphql(query_responses=[response])
        mapping = _resolve_review_thread_ids_for_comments(
            client, "acme", "widgets", 42, [111, 999]
        )
        self.assertEqual(mapping, {111: "RT_1"})


class PostResolvedReviewCommentRepliesTest(unittest.TestCase):
    def _make_pr(self) -> MagicMock:
        pr = MagicMock()
        pr.number = 42
        pr.create_review_comment_reply = MagicMock()
        return pr

    def test_returns_empty_when_no_resolved_entries(self) -> None:
        client = _make_github_client_with_graphql(query_responses=[])
        pr = self._make_pr()
        results = post_resolved_review_comment_replies(
            client, "acme", "widgets", pr, []
        )
        self.assertEqual(results, [])
        pr.create_review_comment_reply.assert_not_called()

    def test_posts_reply_and_resolves_thread(self) -> None:
        query_response = (
            {},
            {
                "data": {
                    "repository": {
                        "pullRequest": {
                            "reviewThreads": {
                                "pageInfo": {
                                    "hasNextPage": False,
                                    "endCursor": None,
                                },
                                "nodes": [
                                    {
                                        "id": "RT_1",
                                        "isResolved": False,
                                        "comments": {
                                            "nodes": [{"databaseId": 111}]
                                        },
                                    }
                                ],
                            }
                        }
                    }
                }
            },
        )
        mutation_response = ({}, {"thread": {"id": "RT_1", "isResolved": True}})
        client = _make_github_client_with_graphql(
            query_responses=[query_response],
            mutation_responses=[mutation_response],
        )
        pr = self._make_pr()
        results = post_resolved_review_comment_replies(
            client,
            "acme",
            "widgets",
            pr,
            [{"comment_id": 111, "summary": "Fixed it."}],
        )
        self.assertEqual(
            results,
            [
                {
                    "comment_id": 111,
                    "thread_id": "RT_1",
                    "reply_posted": True,
                    "thread_resolved": True,
                }
            ],
        )
        pr.create_review_comment_reply.assert_called_once()
        call_args = pr.create_review_comment_reply.call_args[0]
        self.assertEqual(call_args[0], 111)
        self.assertIn("Fixed it.", call_args[1])

    def test_posts_reply_without_thread_when_thread_lookup_returns_nothing(self) -> None:
        query_response = (
            {},
            {
                "data": {
                    "repository": {
                        "pullRequest": {
                            "reviewThreads": {
                                "pageInfo": {
                                    "hasNextPage": False,
                                    "endCursor": None,
                                },
                                "nodes": [],
                            }
                        }
                    }
                }
            },
        )
        client = _make_github_client_with_graphql(
            query_responses=[query_response], mutation_responses=[]
        )
        pr = self._make_pr()
        results = post_resolved_review_comment_replies(
            client,
            "acme",
            "widgets",
            pr,
            [{"comment_id": 111, "summary": "Fixed it."}],
        )
        self.assertEqual(
            results,
            [
                {
                    "comment_id": 111,
                    "thread_id": "",
                    "reply_posted": True,
                    "thread_resolved": False,
                }
            ],
        )

    def test_continues_when_reply_fails(self) -> None:
        query_response = (
            {},
            {
                "data": {
                    "repository": {
                        "pullRequest": {
                            "reviewThreads": {
                                "pageInfo": {
                                    "hasNextPage": False,
                                    "endCursor": None,
                                },
                                "nodes": [
                                    {
                                        "id": "RT_1",
                                        "isResolved": False,
                                        "comments": {
                                            "nodes": [{"databaseId": 111}]
                                        },
                                    },
                                    {
                                        "id": "RT_2",
                                        "isResolved": False,
                                        "comments": {
                                            "nodes": [{"databaseId": 222}]
                                        },
                                    },
                                ],
                            }
                        }
                    }
                }
            },
        )
        mutation_response = ({}, {"thread": {"id": "RT_2", "isResolved": True}})
        client = _make_github_client_with_graphql(
            query_responses=[query_response],
            mutation_responses=[mutation_response],
        )
        pr = self._make_pr()

        def fail_first_reply(comment_id: int, body: str) -> None:
            if comment_id == 111:
                raise RuntimeError("boom")

        pr.create_review_comment_reply.side_effect = fail_first_reply
        results = post_resolved_review_comment_replies(
            client,
            "acme",
            "widgets",
            pr,
            [
                {"comment_id": 111, "summary": "First."},
                {"comment_id": 222, "summary": "Second."},
            ],
        )
        self.assertEqual(len(results), 2)
        self.assertFalse(results[0]["reply_posted"])
        self.assertTrue(results[1]["reply_posted"])
        self.assertTrue(results[1]["thread_resolved"])


class _FakeReviewComment(SimpleNamespace):
    """Minimal review-comment stand-in for formatting tests."""


if __name__ == "__main__":
    unittest.main()
