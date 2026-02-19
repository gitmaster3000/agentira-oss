"""
AgentIRA MCP Proxy Shim — Streamable HTTP transport.

Bridges a stdio-based MCP client (e.g. Cursor, VS Code extensions) to the
AgentIRA Streamable HTTP server at /mcp.

Usage: configure your IDE to launch this script as an MCP stdio server.
The script auto-discovers the API key from:
  1. AGENTIRA_API_KEY environment variable
  2. .agent/mcp_key.txt walking up from the current directory
"""

import sys
import os
import json
import asyncio
import logging
import traceback
from typing import Optional

try:
    from mcp.client.streamable_http import streamablehttp_client
    from mcp.types import JSONRPCMessage
    from mcp.shared.message import SessionMessage
except ImportError:
    pass

LOG_FILE = r"C:\agentira\agentira_mcp_proxy.log"


def setup_logging():
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)
    logging.basicConfig(
        level=logging.INFO,
        filename=LOG_FILE,
        filemode="a",
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    return logging.getLogger("mcp_proxy")


logger = setup_logging()


async def get_api_key() -> Optional[str]:
    """Discover the API key from environment or local workspace file."""
    ev = os.environ.get("AGENTIRA_API_KEY")
    if ev:
        return ev

    current_dir = os.getcwd()
    candidates = [current_dir, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]
    for start_dir in candidates:
        search_dir = start_dir
        while search_dir:
            key_path = os.path.join(search_dir, ".agent", "mcp_key.txt")
            if os.path.exists(key_path):
                with open(key_path, "r") as f:
                    key = f.read().strip()
                    if key:
                        return key
            parent_dir = os.path.dirname(search_dir)
            if parent_dir == search_dir:
                break
            search_dir = parent_dir
    return None


async def run_proxy():
    api_key = await get_api_key()
    if not api_key:
        logger.error("CRITICAL: No API key found.")
        sys.exit(1)

    mcp_url = "http://127.0.0.1:8000/mcp"
    auth_headers = {
        "Authorization": f"Bearer {api_key}",
        "X-Proxy-Workspace": os.getcwd(),
    }

    logger.info("--- STARTING MCP PROXY SHIM (Streamable HTTP) ---")

    try:
        async with streamablehttp_client(mcp_url, headers=auth_headers) as (read_stream, write_stream, _):
            logger.info(f"CONNECTED to AgentIRA MCP at {mcp_url}")

            async def forward_to_server():
                try:
                    while True:
                        line = await asyncio.get_event_loop().run_in_executor(None, sys.stdin.readline)
                        if not line:
                            logger.info("Stdin closed")
                            break
                        raw_line = line.strip()
                        if not raw_line:
                            continue
                        try:
                            data = json.loads(raw_line)
                            message = JSONRPCMessage.model_validate(data)
                            session_msg = SessionMessage(message=message)
                            await write_stream.send(session_msg)
                            logger.debug(f"FWD -> SERVER: {raw_line[:120]}")
                        except Exception as e:
                            logger.error(f"Failed to process stdin: {e}")
                except Exception as e:
                    logger.error(f"forward_to_server error: {e}")

            async def forward_to_client():
                try:
                    async for msg_wrapper in read_stream:
                        try:
                            message = msg_wrapper.message if hasattr(msg_wrapper, "message") else msg_wrapper
                            if hasattr(message, "model_dump_json"):
                                output = message.model_dump_json()
                            elif hasattr(message, "json"):
                                output = message.json()
                            else:
                                output = json.dumps(message)
                            sys.stdout.write(output + "\n")
                            sys.stdout.flush()
                            logger.debug(f"FWD <- SERVER: {output[:120]}")
                        except Exception as e:
                            logger.error(f"Serialize error: {e}")
                except Exception as e:
                    logger.error(f"forward_to_client error: {e}")

            await asyncio.gather(forward_to_server(), forward_to_client())

    except Exception as e:
        logger.error(f"Proxy runtime error: {e}")
        logger.error(traceback.format_exc())


if __name__ == "__main__":
    try:
        asyncio.run(run_proxy())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.error(f"FATAL: {e}")
        logger.error(traceback.format_exc())
