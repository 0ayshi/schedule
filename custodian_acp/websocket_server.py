"""Serve the local stdio ACP agent to browsers over WebSocket.

This keeps the transport bridge beside the teaching agent, so students start one
program. Each WebSocket connection receives its own child agent process.
"""

from __future__ import annotations

import argparse
import asyncio
import itertools
import logging
import sys
from contextlib import suppress
from pathlib import Path

# code updated - decode/validate img
import base64
import binascii
import hashlib
import json

from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

HOST = "127.0.0.1"
PORT = 7331
PATH = "/acp"
AGENT_SCRIPT = Path(__file__).with_name("pydantic_acp_agent.py")
LOGGER = logging.getLogger(__name__)
CONNECTION_IDS = itertools.count(1)


# region websocket-relay
async def relay(websocket: ServerConnection) -> None:
    """Run one stdio ACP agent and relay this browser connection to it."""
    if websocket.request.path != PATH:
        LOGGER.warning("Rejected WebSocket connection to %s", websocket.request.path)
        await websocket.close(code=1008, reason="Use the /acp WebSocket endpoint")
        return

    connection_id = next(CONNECTION_IDS)
    try:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-u",
            str(AGENT_SCRIPT),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=AGENT_SCRIPT.parent,
        )
    except OSError:
        LOGGER.exception("Connection %s: could not start the ACP agent", connection_id)
        await websocket.close(
            code=1011, reason="Could not start the ACP agent; check the server log"
        )
        return

    LOGGER.info(
        "Connection %s: started ACP agent process %s", connection_id, process.pid
    )
    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None

    # One task carries browser requests to stdio; the other streams ACP updates back.
    browser_to_agent = asyncio.create_task(copy_to_agent(websocket, process.stdin))
    agent_to_browser = asyncio.create_task(copy_to_browser(process.stdout, websocket))
    log_stderr = asyncio.create_task(log_agent_stderr(process.stderr, connection_id))

    try:
        done, pending = await asyncio.wait(
            (browser_to_agent, agent_to_browser),
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        if browser_to_agent in done and agent_to_browser not in done:
            # The browser transport ended first, so the agent was likely still
            # healthy when the session finished. stop_agent() below still gives
            # it a graceful stdin-close exit before terminating it.
            LOGGER.info(
                "Connection %s: browser connection ended first; stopping the ACP agent",
                connection_id,
            )
        for task in done:
            task.result()
        if agent_to_browser in done and websocket.close_code is None:
            # EOF on stdout means that the child stopped without closing the
            # browser transport itself. Wait briefly so its exit status and
            # final stderr lines are available in the diagnostic below.
            with suppress(TimeoutError):
                await asyncio.wait_for(process.wait(), timeout=1)
            LOGGER.error(
                "Connection %s: ACP agent closed stdout unexpectedly (exit status %s)",
                connection_id,
                (
                    process.returncode
                    if process.returncode is not None
                    else "not yet available"
                ),
            )
            await websocket.close(
                code=1011,
                reason="ACP agent stopped unexpectedly; check the server log",
            )
    except ValueError as error:
        LOGGER.warning(
            "Connection %s: invalid WebSocket message: %s", connection_id, error
        )
        await websocket.close(code=1003, reason=str(error))
    except ConnectionClosed:
        pass
    except Exception:
        LOGGER.exception("Connection %s: ACP relay failed", connection_id)
        with suppress(ConnectionClosed):
            await websocket.close(
                code=1011, reason="ACP relay failed; check the server log"
            )
    finally:
        await stop_agent(process, connection_id)
        # Let the stderr reader drain messages written while the process was
        # shutting down instead of cancelling it before the useful error.
        with suppress(TimeoutError):
            await asyncio.wait_for(log_stderr, timeout=1)
        if not log_stderr.done():
            log_stderr.cancel()
            await asyncio.gather(log_stderr, return_exceptions=True)
        LOGGER.info(
            "Connection %s: ACP agent process %s stopped with exit status %s",
            connection_id,
            process.pid,
            process.returncode,
        )


# endregion websocket-relay


# code updated - image-interception helper
def prepare_inline_images(message: str) -> tuple[str, list[str]]:
    """Validate inline images, echo them to the client, and keep them away from a text-only model."""
    record = json.loads(message)

    if record.get("method") != "session/prompt":
        return message, []

    params = record.get("params", {})
    prompt = params.get("prompt", [])
    session_id = params.get("sessionId")

    if not isinstance(prompt, list) or not session_id:
        return message, []

    transformed_prompt = []
    image_updates = []

    for part in prompt:
        if not isinstance(part, dict) or part.get("type") != "image":
            transformed_prompt.append(part)
            continue

        mime_type = part.get("mimeType")
        encoded_data = part.get("data")

        if mime_type not in {"image/png", "image/jpeg", "image/webp"}:
            raise ValueError("Only PNG, JPEG, and WebP inline images are supported.")
        if not isinstance(encoded_data, str):
            raise ValueError("Inline image data must be Base64 text.")

        try:
            image_bytes = base64.b64decode(encoded_data, validate=True)
        except (binascii.Error, ValueError) as error:
            raise ValueError("Inline image data is not valid Base64.") from error

        if len(image_bytes) > 5 * 1024 * 1024:
            raise ValueError("Inline images must be 5 MB or smaller.")

        digest = hashlib.sha256(image_bytes).hexdigest()

        transformed_prompt.append(
            {
                "type": "text",
                "text": (
                    "[Inline image received and validated by the ACP bridge. "
                    f"MIME type: {mime_type}; size: {len(image_bytes)} bytes; "
                    f"SHA-256: {digest}. "
                    "The configured Bedrock model is text-only, so do not claim "
                    "to know the image's visual contents.]"
                ),
            }
        )

        image_updates.append(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "session/update",
                    "params": {
                        "sessionId": session_id,
                        "update": {
                            "sessionUpdate": "agent_message_chunk",
                            "content": part,
                        },
                    },
                }
            )
        )

    params["prompt"] = transformed_prompt
    return json.dumps(record), image_updates


# region relay-records - code updated
async def copy_to_agent(
    websocket: ServerConnection,
    stdin: asyncio.StreamWriter,
) -> None:
    async for message in websocket:
        if isinstance(message, bytes) or "\n" in message or "\r" in message:
            raise ValueError("ACP WebSocket messages must be one text JSON-RPC record")

        transformed_message, image_updates = prepare_inline_images(message)

        for update in image_updates:
            await websocket.send(update)

        stdin.write(transformed_message.encode("utf-8") + b"\n")
        await stdin.drain()


async def copy_to_browser(
    stdout: asyncio.StreamReader, websocket: ServerConnection
) -> None:
    while line := await stdout.readline():
        message = line.rstrip(b"\r\n")
        if message:
            await websocket.send(message.decode("utf-8"))


# endregion relay-records


async def log_agent_stderr(stderr: asyncio.StreamReader, connection_id: int) -> None:
    while line := await stderr.readline():
        LOGGER.warning(
            "Connection %s, ACP agent stderr: %s",
            connection_id,
            line.decode(errors="replace").rstrip(),
        )


async def stop_agent(process: asyncio.subprocess.Process, connection_id: int) -> None:
    if process.stdin is not None:
        process.stdin.close()
        with suppress(BrokenPipeError, ConnectionResetError):
            await process.stdin.wait_closed()
    with suppress(TimeoutError):
        await asyncio.wait_for(process.wait(), timeout=2)
        return
    LOGGER.info(
        "Connection %s: ACP agent did not exit after stdin close; sending terminate"
        " (on Windows the reported exit status is 1)",
        connection_id,
    )
    process.terminate()
    with suppress(TimeoutError):
        await asyncio.wait_for(process.wait(), timeout=2)
        return
    process.kill()
    await process.wait()


# region websocket-server
async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Serve the CAB432 ACP agent over WebSocket."
    )
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", default=PORT, type=int)
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="log connections and child-process lifecycle details",
    )
    args = parser.parse_args()
    if args.verbose:
        logging.getLogger().setLevel(logging.INFO)
    async with serve(relay, args.host, args.port):
        print(f"ACP server listening at ws://{args.host}:{args.port}{PATH}")
        await asyncio.Future()


# endregion websocket-server


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.WARNING, format="%(levelname)s: %(message)s", stream=sys.stderr
    )
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
