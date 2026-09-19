import re
from typing import Any

import requests

from config import get_secret


GITHUB_README_URL = "https://api.github.com/repos/{repo}/readme"
GITHUB_SEARCH_URL = "https://api.github.com/search/repositories"
GITHUB_USER_REPOS_URL = "https://api.github.com/user/repos"
REPO_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class GitHubAuthError(ValueError):
    """GitHub rejected the token (expired, revoked, or invalid).

    A ValueError subclass so callers that only handle ValueError (the Streamlit app) still
    show the message; the web server catches it first to end a dead session.
    """


def get_github_token() -> str | None:
    """Read an optional GitHub token from the environment, then .streamlit/secrets.toml.

    A token is free (a classic personal access token needs no scopes for public repos) and
    raises the rate limit from 60/hour to 5,000/hour.
    """
    token = get_secret("GITHUB_TOKEN")
    if not token or token.strip().lower() in {"your-github-token", "ghp_your-token-here"}:
        return None
    return token.strip()


def parse_repositories(raw_repositories: str) -> list[str]:
    repositories = [line.strip() for line in raw_repositories.splitlines() if line.strip()]
    if len(repositories) < 2:
        raise ValueError("Enter at least two repositories, one owner/repo per line.")
    if len(repositories) > 10:
        raise ValueError("CrossTalk supports up to 10 repositories per analysis.")
    if len(set(repositories)) != len(repositories):
        raise ValueError("Remove duplicate repositories before analyzing.")
    for repo in repositories:
        if not REPO_PATTERN.fullmatch(repo):
            raise ValueError(f"`{repo}` is invalid. Use the format owner/repo.")
    return repositories


def github_headers(accept: str, token: str | None) -> dict[str, str]:
    headers = {"Accept": accept, "User-Agent": "CrossTalk-MVP"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def fetch_readme(repo: str, token: str | None = None) -> str:
    """Fetch the public README through GitHub's repository API."""
    if not REPO_PATTERN.fullmatch(repo.strip()):
        raise ValueError("Use the format owner/repo, for example expressjs/session.")

    response = requests.get(
        GITHUB_README_URL.format(repo=repo.strip()),
        headers=github_headers("application/vnd.github.raw+json", token),
        timeout=15,
    )
    if response.status_code == 401 and token:
        raise GitHubAuthError("GitHub rejected the token.")
    if response.status_code == 404:
        raise ValueError("Repository was not found, has no README, or you don't have access to it.")
    if response.status_code in (401, 403):
        raise ValueError("GitHub rate limit reached. Try again shortly or add a GitHub token.")
    response.raise_for_status()

    content = response.text.strip()
    if not content:
        raise ValueError("The repository README is empty.")
    return content[:2500]


def search_github_repositories(query: str, limit: int = 10, token: str | None = None) -> list[dict[str, Any]]:
    """Find public GitHub repositories matching a topic or tool name."""
    query = query.strip()
    if len(query) < 2:
        raise ValueError("Enter at least two characters to search GitHub.")

    response = requests.get(
        GITHUB_SEARCH_URL,
        params={"q": query, "sort": "stars", "order": "desc", "per_page": limit},
        headers=github_headers("application/vnd.github+json", token),
        timeout=15,
    )
    if response.status_code == 401 and token:
        raise GitHubAuthError("GitHub rejected the token.")
    if response.status_code in (403, 429):
        raise ValueError("GitHub search rate limit reached. Try again shortly.")
    response.raise_for_status()
    return [_repo_summary(item) for item in response.json().get("items", [])]


def _repo_summary(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "full_name": item["full_name"],
        "description": item.get("description") or "No description provided.",
        "stars": item.get("stargazers_count", 0),
        "language": item.get("language") or "Unknown",
        "url": item["html_url"],
    }


def list_user_repositories(token: str, limit: int = 50) -> list[dict[str, Any]]:
    """The signed-in user's repositories (including private ones the token can see)."""
    response = requests.get(
        GITHUB_USER_REPOS_URL,
        params={
            "sort": "pushed",
            "direction": "desc",
            "per_page": max(1, min(limit, 100)),
            "affiliation": "owner,collaborator,organization_member",
        },
        headers=github_headers("application/vnd.github+json", token),
        timeout=15,
    )
    if response.status_code == 401:
        raise GitHubAuthError("GitHub rejected the token.")
    if response.status_code in (403, 429):
        raise ValueError("GitHub rate limit reached. Try again shortly.")
    response.raise_for_status()
    return [{**_repo_summary(item), "private": bool(item.get("private"))} for item in response.json()]
