from __future__ import annotations

import base64
from typing import Any

import httpx


class GitHubClient:
    def __init__(self, token: str, repository: str) -> None:
        self.repository = repository
        self._client = httpx.Client(
            base_url="https://api.github.com",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "User-Agent": "oz-python-workflows",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=60.0,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "GitHubClient":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any | None = None,
    ) -> Any:
        response = self._client.request(method, path, params=params, json=json_body)
        response.raise_for_status()
        if not response.content:
            return None
        return response.json()

    def request_or_none(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any | None = None,
    ) -> Any | None:
        response = self._client.request(method, path, params=params, json=json_body)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        if not response.content:
            return None
        return response.json()

    def paginate(self, path: str, *, params: dict[str, Any] | None = None) -> list[Any]:
        page = 1
        per_page = 100
        base_params = dict(params or {})
        results: list[Any] = []

        while True:
            merged = {**base_params, "page": page, "per_page": per_page}
            page_data = self.request("GET", path, params=merged)
            if not isinstance(page_data, list):
                raise RuntimeError(f"Expected list response while paginating {path}")
            results.extend(page_data)
            if len(page_data) < per_page:
                return results
            page += 1

    def get_issue(self, owner: str, repo: str, issue_number: int) -> dict[str, Any]:
        return self.request("GET", f"/repos/{owner}/{repo}/issues/{issue_number}")

    def get_pull(self, owner: str, repo: str, pull_number: int) -> dict[str, Any]:
        return self.request("GET", f"/repos/{owner}/{repo}/pulls/{pull_number}")

    def list_issue_comments(self, owner: str, repo: str, issue_number: int) -> list[dict[str, Any]]:
        return self.paginate(
            f"/repos/{owner}/{repo}/issues/{issue_number}/comments",
        )

    def list_issue_events(self, owner: str, repo: str, issue_number: int) -> list[dict[str, Any]]:
        return self.paginate(
            f"/repos/{owner}/{repo}/issues/{issue_number}/events",
        )

    def create_comment(self, owner: str, repo: str, issue_number: int, body: str) -> dict[str, Any]:
        return self.request(
            "POST",
            f"/repos/{owner}/{repo}/issues/{issue_number}/comments",
            json_body={"body": body},
        )

    def update_comment(self, owner: str, repo: str, comment_id: int, body: str) -> dict[str, Any]:
        return self.request(
            "PATCH",
            f"/repos/{owner}/{repo}/issues/comments/{comment_id}",
            json_body={"body": body},
        )

    def get_comment(self, owner: str, repo: str, comment_id: int) -> dict[str, Any]:
        return self.request(
            "GET",
            f"/repos/{owner}/{repo}/issues/comments/{comment_id}",
        )

    def delete_comment(self, owner: str, repo: str, comment_id: int) -> None:
        self.request(
            "DELETE",
            f"/repos/{owner}/{repo}/issues/comments/{comment_id}",
        )

    def remove_assignees(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        assignees: list[str],
    ) -> None:
        self.request(
            "DELETE",
            f"/repos/{owner}/{repo}/issues/{issue_number}/assignees",
            json_body={"assignees": assignees},
        )

    def add_assignees(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        assignees: list[str],
    ) -> dict[str, Any]:
        return self.request(
            "POST",
            f"/repos/{owner}/{repo}/issues/{issue_number}/assignees",
            json_body={"assignees": assignees},
        )

    def get_user(self, username: str) -> dict[str, Any] | None:
        return self.request_or_none("GET", f"/users/{username}")

    def list_pulls(
        self,
        owner: str,
        repo: str,
        *,
        state: str,
        head: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"state": state}
        if head:
            params["head"] = head
        return self.paginate(f"/repos/{owner}/{repo}/pulls", params=params)

    def list_pull_files(self, owner: str, repo: str, pull_number: int) -> list[dict[str, Any]]:
        return self.paginate(f"/repos/{owner}/{repo}/pulls/{pull_number}/files")

    def list_repo_issues(
        self,
        owner: str,
        repo: str,
        *,
        state: str,
        labels: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"state": state}
        if labels:
            params["labels"] = labels
        return self.paginate(f"/repos/{owner}/{repo}/issues", params=params)
    def update_issue(self, owner: str, repo: str, issue_number: int, **fields: Any) -> dict[str, Any]:
        return self.request(
            "PATCH",
            f"/repos/{owner}/{repo}/issues/{issue_number}",
            json_body=fields,
        )

    def add_labels(self, owner: str, repo: str, issue_number: int, labels: list[str]) -> list[dict[str, Any]]:
        return self.request(
            "POST",
            f"/repos/{owner}/{repo}/issues/{issue_number}/labels",
            json_body={"labels": labels},
        )

    def list_repo_labels(self, owner: str, repo: str) -> list[dict[str, Any]]:
        return self.paginate(f"/repos/{owner}/{repo}/labels")

    def create_label(
        self,
        owner: str,
        repo: str,
        *,
        name: str,
        color: str,
        description: str = "",
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"name": name, "color": color}
        if description:
            payload["description"] = description
        return self.request(
            "POST",
            f"/repos/{owner}/{repo}/labels",
            json_body=payload,
        )

    def get_contents_text(self, owner: str, repo: str, path: str, *, ref: str) -> str | None:
        response = self.request_or_none(
            "GET",
            f"/repos/{owner}/{repo}/contents/{path}",
            params={"ref": ref},
        )
        if not response:
            return None
        if response.get("encoding") != "base64":
            raise RuntimeError(f"Unexpected content encoding for {path}: {response.get('encoding')}")
        content = response.get("content", "")
        return base64.b64decode(content).decode("utf-8")

    def create_pull(
        self,
        owner: str,
        repo: str,
        *,
        title: str,
        head: str,
        base: str,
        body: str,
        draft: bool,
    ) -> dict[str, Any]:
        return self.request(
            "POST",
            f"/repos/{owner}/{repo}/pulls",
            json_body={
                "title": title,
                "head": head,
                "base": base,
                "body": body,
                "draft": draft,
            },
        )

    def update_pull(self, owner: str, repo: str, pull_number: int, **fields: Any) -> dict[str, Any]:
        return self.request(
            "PATCH",
            f"/repos/{owner}/{repo}/pulls/{pull_number}",
            json_body=fields,
        )

    def create_reaction_for_issue_comment(
        self,
        owner: str,
        repo: str,
        comment_id: int,
        content: str,
    ) -> dict[str, Any]:
        return self.request(
            "POST",
            f"/repos/{owner}/{repo}/issues/comments/{comment_id}/reactions",
            json_body={"content": content},
        )

    def create_review(
        self,
        owner: str,
        repo: str,
        pull_number: int,
        *,
        body: str,
        event: str,
        comments: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"body": body, "event": event}
        if comments:
            payload["comments"] = comments
        return self.request(
            "POST",
            f"/repos/{owner}/{repo}/pulls/{pull_number}/reviews",
            json_body=payload,
        )

    def list_pull_review_comments(self, owner: str, repo: str, pull_number: int) -> list[dict[str, Any]]:
        return self.paginate(f"/repos/{owner}/{repo}/pulls/{pull_number}/comments")

    def create_reaction_for_pull_request_review_comment(
        self,
        owner: str,
        repo: str,
        comment_id: int,
        content: str,
    ) -> dict[str, Any]:
        return self.request(
            "POST",
            f"/repos/{owner}/{repo}/pulls/comments/{comment_id}/reactions",
            json_body={"content": content},
        )

    def get_ref(self, owner: str, repo: str, ref: str) -> dict[str, Any] | None:
        return self.request_or_none("GET", f"/repos/{owner}/{repo}/git/ref/{ref}")

    def get_commit(self, owner: str, repo: str, sha: str) -> dict[str, Any]:
        return self.request("GET", f"/repos/{owner}/{repo}/commits/{sha}")
