# copied from the aws lambda editor

# code updated
# This checks GitHub for open issues and saves a successful or failed heartbeat record in DynamoDB.
# It does not modify GitHub.
import json
import os
from datetime import datetime, timezone
from urllib.request import Request, urlopen

import boto3

REPOSITORY = os.getenv("REPOSITORY", "0ayshi/schedule")
TABLE_NAME = os.getenv(
    "DYNAMODB_TABLE",
    "n11242795-repo-custodian-records",
)

table = boto3.resource("dynamodb").Table(TABLE_NAME)


def get_open_issues() -> list[dict]:
    """Retrieve open issues from GitHub, excluding pull requests."""

    request = Request(
        f"https://api.github.com/repos/{REPOSITORY}/issues" "?state=open&per_page=100",
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "CAB432-Repository-Custodian",
        },
    )

    with urlopen(request, timeout=15) as response:
        results = json.load(response)

    return [item for item in results if "pull_request" not in item]


def lambda_handler(event, context):
    """Process an SQS heartbeat and record the repository status."""

    created_at = datetime.now(timezone.utc).isoformat()

    try:
        issues = get_open_issues()

        table.put_item(
            Item={
                "PK": "HEARTBEAT",
                "SK": f"RUN#{created_at}",
                "recordType": "RepositoryHeartbeat",
                "repository": REPOSITORY,
                "status": "success",
                "openIssueCount": len(issues),
                "openIssueNumbers": [issue["number"] for issue in issues],
                "createdAt": created_at,
            }
        )

        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "repository": REPOSITORY,
                    "openIssueCount": len(issues),
                    "createdAt": created_at,
                }
            ),
        }

    except Exception as error:
        table.put_item(
            Item={
                "PK": "HEARTBEAT",
                "SK": f"ERROR#{created_at}",
                "recordType": "RepositoryHeartbeat",
                "repository": REPOSITORY,
                "status": "error",
                "error": str(error),
                "createdAt": created_at,
            }
        )
        raise
