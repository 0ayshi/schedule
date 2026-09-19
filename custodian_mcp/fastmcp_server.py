# code updated
"""MCP tools for the Repository Custodian agent."""

import os

import httpx
from fastmcp import FastMCP

REPOSITORY = "0ayshi/schedule"
GITHUB_API_URL = f"https://api.github.com/repos/{REPOSITORY}"
DEFAULT_BRANCH = "master"

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

@mcp.tool
def list_repository_files(
    path_prefix: str = "",
    limit: int = 100,
) -> dict[str, object]:
    """List file paths in the managed GitHub repository."""

    safe_limit = max(1, min(limit, 200))

    response = httpx.get(
        f"{GITHUB_API_URL}/git/trees/{DEFAULT_BRANCH}",
        headers=github_headers(),
        params={"recursive": "1"},
        timeout=15.0,
    )
    response.raise_for_status()

    files = [
        item["path"]
        for item in response.json().get("tree", [])
        if item["type"] == "blob"
        and item["path"].startswith(path_prefix)
    ][:safe_limit]

    return {
        "repository": REPOSITORY,
        "path_prefix": path_prefix,
        "count": len(files),
        "files": files,
    }

if __name__ == "__main__":
    mcp.run()