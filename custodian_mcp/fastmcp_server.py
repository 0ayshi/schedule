# code updated
"""MCP tools for the Repository Custodian agent."""

import os

import httpx
from fastmcp import FastMCP

REPOSITORY = "0ayshi/schedule"
GITHUB_API_URL = f"https://api.github.com/repos/{REPOSITORY}"

mcp = FastMCP("Repository Custodian tools")

def github_headers() -> dict[str, str]:
    """Create headers for GitHub API requests."""

    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    return headers

@mcp.tool
def get_repository_scope() -> dict[str, object]:
    """Return the repository and features managed by the custodian."""

    return {
        "repository": REPOSITORY,
        "project_role": "Repository Custodian",
        "supported_features": [
            "basic scheduling",
            "cancellation",
        ],
    }

@mcp.tool
def list_open_issues(limit: int = 10) -> dict[str, object]:
    """Return open GitHub issues from the managed repository."""

    safe_limit = max(1, min(limit, 30))

    response = httpx.get(
        f"{GITHUB_API_URL}/issues",
        headers=github_headers(),
        params={
            "state": "open",
            "per_page": safe_limit,
        },
        timeout=15.0,
    )
    response.raise_for_status()

    # GitHub's issues endpoint also returns pull requests, so exclude them.
    issues = [
        {
            "number": issue["number"],
            "title": issue["title"],
            "body": issue["body"] or "",
            "labels": [label["name"] for label in issue["labels"]],
            "url": issue["html_url"],
        }
        for issue in response.json()
        if "pull_request" not in issue
    ]

    return {
        "repository": REPOSITORY,
        "count": len(issues),
        "issues": issues,
    }

if __name__ == "__main__":
    mcp.run()