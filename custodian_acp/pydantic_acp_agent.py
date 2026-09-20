"""Expose the existing PydanticAI/MCP teaching agent through ACP over stdio."""

from __future__ import annotations

import os
import sys
import warnings
from pathlib import Path

from fastmcp.client.transports import StdioTransport
from pydantic_ai import Agent
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.models.bedrock import BedrockConverseModel
from pydantic_ai.providers.bedrock import BedrockProvider
from pydantic_ai_harness.experimental import HarnessExperimentalWarning

# ACP is an explicitly experimental Harness capability; keep its expected warning out of server logs.
warnings.filterwarnings("ignore", category=HarnessExperimentalWarning)
from pydantic_ai_harness.experimental.acp import run_acp_stdio_sync

# Use the configured region, defaulting to the unit's Sydney region.
REGION = os.getenv("AWS_REGION", "ap-southeast-2")
MODEL_ID = "nvidia.nemotron-super-3-120b"
# The MCP practical is extracted beside this directory.

#MCP_SERVER = Path(__file__).parents[1] / "mcp_servers_python" / "fastmcp_server.py" - changed mcp server path
MCP_SERVER = Path(__file__).parents[1] / "custodian_mcp" / "fastmcp_server.py"

# code updated
# Forward only the GitHub token required by the MCP subprocess.
MCP_ENV = {}

github_token = os.getenv("GITHUB_TOKEN")
if github_token:
    MCP_ENV["GITHUB_TOKEN"] = github_token

#region agent-configuration
# This is the same Bedrock model and local MCP toolset as the terminal agent.
model = BedrockConverseModel(MODEL_ID, provider=BedrockProvider(region_name=REGION))
mcp_toolset = MCPToolset(
    StdioTransport(
        command=sys.executable,
        args=[str(MCP_SERVER)],
        env=MCP_ENV,
    )
)

agent = Agent(  # code updated
    model,
    instructions=(
        "You are a Repository Custodian for the 0ayshi/schedule repository. "                                    # purpose
        "Only focus on basic scheduling and cancellation. "                                                      # focus
        "Use get_repository_scope when asked about your responsibilities or project scope. "                     # project scope
        "Always use list_open_issues when asked about current or open GitHub issues. "                           # github issues
        "Base repository answers on tool results rather than inventing information."                             # answers: use tools
        "Use list_repository_files when you need to inspect the repository structure or locate relevant files. " # look at repo files
        "Use get_repository_file to read a relevant file after locating it with list_repository_files. "         # read file after locating it
        "Use search_repository_file instead of reading an entire large file when looking for specific code. "    # read relavent code instead of entire file
        "Before posting an issue comment, draft the exact comment and show it to the user. "                     # draft comment and show user before posting issue
        "Only call add_issue_comment with confirmed=True after the user explicitly approves that exact comment. "# only call after user approves comment
        "Never treat a request to investigate or draft as permission to post."                                   # cannot post request until you clearly say post it
    ),
    toolsets=[mcp_toolset],
)
#endregion agent-configuration


if __name__ == "__main__":
    #region acp-runner
    # The Pydantic AI Harness supplies ACP sessions, history, streaming and cancellation.
    # websocket_server.py exposes this stdio server to the browser over WebSocket.

    # code updated: run_acp_stdio_sync(agent, name="CAB432 Bedrock MCP agent", version="1.0.0")
    run_acp_stdio_sync(
        agent,
        name="Repository Custodian",
        version="1.0.0",
    )
    #endregion acp-runner
