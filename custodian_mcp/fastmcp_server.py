# code updated
"""MCP tools for the Repository Custodian agent."""

from datetime import datetime, timezone

import os
import json
import base64 # code updated
import boto3 # code updated - connect mcp server to the table
from boto3.dynamodb.conditions import Key #- retrieve saved investigation
import httpx
from fastmcp import FastMCP

REPOSITORY = "0ayshi/schedule"
GITHUB_API_URL = f"https://api.github.com/repos/{REPOSITORY}"
DEFAULT_BRANCH = "master"

# use AWS’s Sydney region;
# connect to your named DynamoDB table;
# allow the table name to be changed through an environment variable later.
AWS_REGION = os.getenv("AWS_REGION", "ap-southeast-2")
DYNAMODB_TABLE = os.getenv(
    "DYNAMODB_TABLE",
    "n11242795-repo-custodian-records",
)

dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
records_table = dynamodb.Table(DYNAMODB_TABLE)

# Bedrock converts repository text into 256-number embeddings.
# S3 Vectors stores and searches those embeddings.
VECTOR_BUCKET = "n11242795-repo-custodian-vectors"
VECTOR_INDEX = "repository-knowledge"
EMBEDDING_MODEL_ID = "amazon.titan-embed-image-v1"
EMBEDDING_DIMENSION = 256

bedrock_runtime = boto3.client("bedrock-runtime", region_name=AWS_REGION)
s3_vectors = boto3.client("s3vectors", region_name=AWS_REGION)

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

# text embedding helper
def embed_text(text: str) -> list[float]:
    """Convert text into a 256-dimensional Titan embedding."""

    response = bedrock_runtime.invoke_model(
        modelId=EMBEDDING_MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=json.dumps(
            {
                "inputText": text,
                "embeddingConfig": {
                    "outputEmbeddingLength": EMBEDDING_DIMENSION
                },
            }
        ),
    )

    response_body = json.loads(response["body"].read())
    return response_body["embedding"]

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

# authenticated issue-comment tool
# Important safety feature: even though the agent has the tool, GitHub receives nothing unless confirmed=True.
# This prevents accidental comments.
@mcp.tool
def add_issue_comment(
    issue_number: int,
    comment_body: str,
    confirmed: bool = False,
) -> dict[str, object]:
    """Post a comment on a GitHub issue after explicit confirmation."""

    if not confirmed:
        return {
            "posted": False,
            "message": "Explicit confirmation is required before posting.",
        }

    if issue_number < 1:
        raise ValueError("The issue number must be positive.")

    cleaned_comment = comment_body.strip()

    if not cleaned_comment:
        raise ValueError("The comment cannot be empty.")

    if len(cleaned_comment) > 4_000:
        raise ValueError("The comment cannot exceed 4,000 characters.")

    if not os.getenv("GITHUB_TOKEN"):
        raise RuntimeError("GITHUB_TOKEN is not configured.")

    response = httpx.post(
        f"{GITHUB_API_URL}/issues/{issue_number}/comments",
        headers=github_headers(),
        json={"body": cleaned_comment},
        timeout=15.0,
    )
    response.raise_for_status()

    created_comment = response.json()

    return {
        "posted": True,
        "issue_number": issue_number,
        "comment_id": created_comment["id"],
        "url": created_comment["html_url"],
    }

# tool that saves an investigation record
@mcp.tool
def save_issue_analysis(
    issue_number: int,
    summary: str,
    status: str = "investigated",
    evidence: str = "",
) -> str:
    """Save an issue investigation result in DynamoDB."""

    if issue_number < 1:
        raise ValueError("issue_number must be positive.")
    if not summary.strip():
        raise ValueError("summary cannot be empty.")

    created_at = datetime.now(timezone.utc).isoformat()
    record = {
        "PK": f"ISSUE#{issue_number}",
        "SK": f"ANALYSIS#{created_at}",
        "recordType": "IssueAnalysis",
        "repository": REPOSITORY,
        "issueNumber": issue_number,
        "summary": summary.strip(),
        "status": status.strip(),
        "evidence": evidence.strip(),
        "createdAt": created_at,
    }

    records_table.put_item(Item=record)
    return f"Saved analysis for issue #{issue_number} at {created_at}."

# retrieve saved investigations
@mcp.tool
def get_issue_analyses(issue_number: int, limit: int = 10) -> str:
    """Retrieve saved investigation records for a GitHub issue."""

    if issue_number < 1:
        raise ValueError("issue_number must be positive.")

    limit = max(1, min(limit, 20))

    response = records_table.query(
        KeyConditionExpression=(
            Key("PK").eq(f"ISSUE#{issue_number}")
            & Key("SK").begins_with("ANALYSIS#")
        ),
        ScanIndexForward=False,
        Limit=limit,
    )

    items = response.get("Items", [])
    if not items:
        return f"No saved analyses were found for issue #{issue_number}."

    results = []
    for item in items:
        results.append(
            f"{item['createdAt']} | Status: {item['status']} | "
            f"Summary: {item['summary']} | Evidence: {item.get('evidence', '')}"
        )

    return "\n".join(results)

# This stores:
# the embedding for semantic comparison;
# the original text so the agent can read the result;
# its repository source;
# a stable vector key so the record can be updated later.
@mcp.tool
def index_knowledge_chunk(
    vector_key: str,
    text: str,
    source: str,
    confirmed: bool = False,
) -> str:
    """Embed and store one repository knowledge chunk in S3 Vectors."""

    if not confirmed:
        raise ValueError("Explicit confirmation is required before indexing knowledge.")
    if not vector_key.strip():
        raise ValueError("vector_key cannot be empty.")
    if not text.strip():
        raise ValueError("text cannot be empty.")
    if len(text) > 500:
        raise ValueError("text cannot exceed 500 characters.")
    if not source.strip():
        raise ValueError("source cannot be empty.")

    s3_vectors.put_vectors(
        vectorBucketName=VECTOR_BUCKET,
        indexName=VECTOR_INDEX,
        vectors=[
            {
                "key": vector_key.strip(),
                "data": {"float32": embed_text(text.strip())},
                "metadata": {
                    "kind": "repository-text",
                    "text": text.strip(),
                    "source": source.strip(),
                    "repository": REPOSITORY,
                },
            }
        ],
    )

    return f"Indexed repository knowledge under key '{vector_key.strip()}'."

# semantic search tool
@mcp.tool
def search_repository_knowledge(query: str, limit: int = 3) -> str:
    """Search indexed repository knowledge by semantic similarity."""

    if not query.strip():
        raise ValueError("query cannot be empty.")
    if len(query) > 500:
        raise ValueError("query cannot exceed 500 characters.")

    limit = max(1, min(limit, 10))

    response = s3_vectors.query_vectors(
        vectorBucketName=VECTOR_BUCKET,
        indexName=VECTOR_INDEX,
        queryVector={"float32": embed_text(query.strip())},
        topK=limit,
        returnDistance=True,
        returnMetadata=True,
    )

    matches = response.get("vectors", [])
    if not matches:
        return "No relevant repository knowledge was found."

    results = []
    for match in matches:
        metadata = match.get("metadata", {})
        results.append(
            f"Source: {metadata.get('source', 'unknown')} | "
            f"Distance: {match.get('distance', 'unknown')} | "
            f"Text: {metadata.get('text', '')}"
        )

    return "\n".join(results)

if __name__ == "__main__":
    mcp.run()