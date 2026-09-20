# code updated
"""MCP tools for the Repository Custodian agent."""

import os
import base64 # code updated
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

# Github send file contents encoded in base64
# so tool decodes them back into readable text
# size limit prevents large file from overwhelming agent
@mcp.tool
def get_repository_file(
    file_path: str,
    max_characters: int = 20_000,
) -> dict[str, object]:
    """Read a text file from the managed GitHub repository."""

    cleaned_path = file_path.strip().lstrip("/")

    if not cleaned_path or ".." in cleaned_path.split("/"):
        raise ValueError("A valid repository file path is required.")

    safe_maximum = max(1_000, min(max_characters, 30_000))

    response = httpx.get(
        f"{GITHUB_API_URL}/contents/{cleaned_path}",
        headers=github_headers(),
        params={"ref": DEFAULT_BRANCH},
        timeout=15.0,
    )
    response.raise_for_status()

    file_data = response.json()

    if file_data.get("type") != "file":
        raise ValueError(f"{cleaned_path} is not a file.")

    encoded_content = file_data.get("content", "").replace("\n", "")
    full_content = base64.b64decode(encoded_content).decode(
        "utf-8",
        errors="replace",
    )

    return {
        "repository": REPOSITORY,
        "path": cleaned_path,
        "sha": file_data["sha"],
        "content": full_content[:safe_maximum],
        "truncated": len(full_content) > safe_maximum,
    }

# smaller tool that returns only matching code sections instead of the entire file.
@mcp.tool
def search_repository_file(
    file_path: str,
    search_term: str,
    context_lines: int = 3,
    max_matches: int = 10,
) -> dict[str, object]:
    """Find matching lines and nearby context in a repository text file."""

    cleaned_path = file_path.strip().lstrip("/")

    if not cleaned_path or ".." in cleaned_path.split("/"):
        raise ValueError("A valid repository file path is required.")

    if not search_term.strip():
        raise ValueError("A search term is required.")

    safe_context = max(0, min(context_lines, 10))
    safe_matches = max(1, min(max_matches, 20))

    response = httpx.get(
        f"{GITHUB_API_URL}/contents/{cleaned_path}",
        headers=github_headers(),
        params={"ref": DEFAULT_BRANCH},
        timeout=15.0,
    )
    response.raise_for_status()

    file_data = response.json()

    if file_data.get("type") != "file":
        raise ValueError(f"{cleaned_path} is not a file.")

    encoded_content = file_data.get("content", "").replace("\n", "")
    content = base64.b64decode(encoded_content).decode(
        "utf-8",
        errors="replace",
    )
    lines = content.splitlines()
    search_value = search_term.casefold()
    matches = []

    for index, line in enumerate(lines):
        if search_value in line.casefold():
            start = max(0, index - safe_context)
            end = min(len(lines), index + safe_context + 1)

            matches.append(
                {
                    "line_number": index + 1,
                    "excerpt": "\n".join(lines[start:end]),
                }
            )

            if len(matches) >= safe_matches:
                break

    return {
        "repository": REPOSITORY,
        "path": cleaned_path,
        "search_term": search_term,
        "count": len(matches),
        "matches": matches,
    }

if __name__ == "__main__":
    mcp.run()