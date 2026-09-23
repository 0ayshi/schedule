# Repository Custodian

This fork of the `schedule` repository is managed by a Repository Custodian developed for CAB432 Assessment 2, Track B.

The custodian focuses on the repository’s basic scheduling and job-cancellation functionality. It can inspect repository content and issues, retrieve relevant knowledge, record investigations, and perform controlled GitHub maintenance actions.

## Main capabilities

* Answer questions about the repository through an ACP-compatible chat interface.
* Retrieve GitHub issues and repository files through an MCP server.
* Search indexed repository knowledge using Amazon S3 Vectors.
* Investigate issues and save analysis records in Amazon DynamoDB.
* Add GitHub issue comments and documentation after explicit user confirmation.
* Accept and return PNG, JPEG, and WebP images inline in the chat.
* Run an autonomous daily heartbeat that detects, summarises, and triages new issues.
* Run the ACP backend as a container on Amazon ECS Fargate.

## Architecture

### Conversational workflow

1. The user sends a message through the browser-based ACP client.
2. The client sends an ACP request to the WebSocket relay.
3. The relay starts the PydanticAI ACP agent.
4. The agent uses the NVIDIA Nemotron model through Amazon Bedrock.
5. When repository information or an action is needed, the agent calls the separate FastMCP server.
6. The MCP tools communicate with GitHub, DynamoDB, S3 Vectors, and AWS Secrets Manager.
7. The response is streamed back to the browser through ACP.

The MCP server runs as a dedicated stdio subprocess. Repository and AWS operations are therefore separated from the model-calling code.

### Autonomous heartbeat workflow

1. Amazon EventBridge Scheduler runs once per day.
2. EventBridge sends a heartbeat message to Amazon SQS.
3. SQS asynchronously invokes the heartbeat AWS Lambda function.
4. Lambda retrieves the repository’s current open GitHub issues.
5. Lambda compares them with the previous heartbeat stored in DynamoDB.
6. New issues are summarised and triaged using Amazon Bedrock.
7. The run, issue numbers, summaries, priorities, and recommended actions are persisted in DynamoDB.
8. If Bedrock is temporarily unavailable, a deterministic fallback triage is saved instead.

This workflow runs without a person prompting the agent.

## AWS services

| Service                      | Purpose                                                      |
| ---------------------------- | ------------------------------------------------------------ |
| Amazon Bedrock               | Foundation-model responses, issue summaries, and triage      |
| Amazon S3 Vectors            | Nearest-neighbour search over repository knowledge           |
| Amazon DynamoDB              | Investigation records, heartbeat history, and triage results |
| Amazon EventBridge Scheduler | Starts the autonomous daily heartbeat                        |
| Amazon SQS                   | Decouples the schedule from asynchronous processing          |
| AWS Lambda                   | Processes heartbeat messages and performs autonomous triage  |
| AWS Secrets Manager          | Stores the GitHub token securely                             |
| Amazon ECS Fargate           | Runs the containerised ACP backend                           |
| Amazon CloudWatch            | Stores Lambda and ECS execution logs                         |

## Important resources

* Repository: `0ayshi/schedule`
* AWS region: `ap-southeast-2`
* DynamoDB table: `n11242795-repo-custodian-records`
* S3 Vectors bucket: `n11242795-repo-custodian-vectors`
* S3 Vectors index: `repository-knowledge`
* Secrets Manager secret: `n11242795/repo-custodian/github-token`
* EventBridge schedule: `n11242795-repo-custodian-heartbeat-schedule`
* SQS queue: `n11242795-repo-custodian-heartbeat`
* ECS cluster: `n11242795-repo-custodian-cluster`
* ECS task definition: `n11242795-repo-custodian-acp`
* Container image: `ghcr.io/0ayshi/repo-custodian-acp:latest`

## Project structure

* `acp_client/` – Vite and TypeScript browser client.
* `custodian_acp/` – PydanticAI ACP agent and WebSocket relay.
* `custodian_mcp/` – FastMCP repository and AWS tools.
* `heartbeat_lambda/` – asynchronous scheduled heartbeat worker.
* `Dockerfile` – ACP backend container definition.
* `.github/workflows/build-container.yml` – GitHub Actions container build.
* `REPOSITORY_CUSTODIAN.md` – project architecture and operating guide.

## Local setup

### Prerequisites

* Python 3.11
* Node.js and npm
* AWS CLI
* An authenticated QUT AWS SSO session

Create and activate a Python environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install the Python dependencies:

```powershell
pip install -r custodian_acp\requirements.txt
pip install -r custodian_mcp\requirements.txt
```

Install the browser-client dependencies:

```powershell
cd acp_client
npm install
cd ..
```

Authenticate with AWS when required:

```powershell
aws sso login
```

## Running the conversational client

In the first terminal, from the repository root:

```powershell
.\.venv\Scripts\Activate.ps1
python custodian_acp\websocket_server.py --verbose
```

In a second terminal:

```powershell
cd acp_client
npm run dev
```

Open the Vite URL displayed in the terminal, normally `http://localhost:5173`.

The WebSocket relay listens on:

```text
ws://127.0.0.1:7331/acp
```

## Image handling

The ACP client accepts PNG, JPEG, and WebP images up to 5 MB.

The WebSocket relay:

* validates the media type;
* validates Base64 encoding;
* checks the decoded size;
* calculates a SHA-256 identifier;
* returns the image inline through an ACP agent-message update; and
* supplies safe image metadata to the text-only foundation model.

The image is therefore visible inline in both directions even though the selected Nemotron model processes text rather than image pixels.

## Repository tools

The MCP server provides tools for:

* retrieving repository scope;
* listing and reading GitHub issues;
* reading repository files;
* investigating scheduling and cancellation behaviour;
* adding confirmed issue comments;
* creating confirmed documentation updates;
* saving and retrieving issue analyses;
* indexing repository knowledge; and
* searching repository knowledge through vector similarity.

GitHub write operations require explicit confirmation. Read-only operations do not modify the repository.

## Security

* The GitHub token is stored in AWS Secrets Manager.
* No GitHub token is hard-coded in source code.
* AWS credentials use the AWS credential chain, SSO, or ECS task role.
* The MCP subprocess does not require the GitHub token to be passed as a plaintext environment variable.
* GitHub mutation tools require explicit confirmation.
* Agent inputs are validated and size-limited.
* The scheduled triage prompt treats GitHub issue text as untrusted data.
* Image MIME types, Base64 content, and decoded sizes are validated.

The Secrets Manager secret must contain a JSON field named `GITHUB_TOKEN`. The token value must never be committed to Git.

## ECS deployment

GitHub Actions builds the root Dockerfile and publishes the image to GitHub Container Registry.

The ACP backend has been deployed to the ECS cluster as a standalone Fargate task. The QUT student IAM policy explicitly denies `ecs:CreateService` and `ec2:CreateSecurityGroup`, so the deployment uses:

* an existing VPC;
* the existing `CAB432SG` security group;
* a standalone ECS task; and
* the supplied ECS execution and task roles.

CloudWatch logs confirm that the container listens on `0.0.0.0:7331` and exposes the `/acp` WebSocket endpoint.

## Verification completed

The following behaviour has been tested:

* normal Bedrock text conversation through ACP;
* inline image send and receive;
* MCP repository retrieval;
* confirmed GitHub issue commenting;
* confirmed GitHub documentation creation;
* DynamoDB issue-analysis persistence;
* S3 Vectors indexing and similarity retrieval;
* EventBridge to SQS delivery;
* SQS-triggered Lambda execution;
* autonomous Bedrock issue summarisation and triage;
* DynamoDB heartbeat persistence;
* GitHub Actions tests;
* container build and publication; and
* ECS Fargate container startup with CloudWatch logs.

## Limitations

* The custodian is intentionally limited to basic scheduling and cancellation.
* GitHub public read requests remain subject to GitHub rate limits.
* Amazon Bedrock can occasionally return a temporary service-unavailable response.
* The heartbeat uses fallback triage if Bedrock is unavailable.
* The selected foundation model is text-only, so images are transported inline while image metadata is supplied to the model.
* QUT IAM restrictions prevent creation of a permanent ECS service or a new security group.
* Human oversight is still required before repository-changing actions.

## Human oversight

The custodian assists with investigation and maintenance but does not replace repository maintainers. A human remains responsible for reviewing findings and approving repository changes.

---

This notice applies specifically to the `0ayshi/schedule` fork.
