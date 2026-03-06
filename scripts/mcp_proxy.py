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
    """Discover the API key from args, environment, or local workspace file."""
    if len(sys.argv) > 1:
        return sys.argv[1]
        
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

    mcp_base_url = "http://127.0.0.1:8000"
    auth_headers = {
        "Authorization": f"Bearer {api_key}",
        "X-Proxy-Workspace": os.getcwd(),
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    logger.info("--- STARTING MCP PROXY SHIM (Simple POST) ---")
    
    import httpx
    
    mcp_post_url = f"{mcp_base_url}/mcp"
    logger.info(f"CONNECTED to AgentIRA MCP POST endpoint at {mcp_post_url}")
    
    current_session_id = None
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            try:
                line = await asyncio.get_event_loop().run_in_executor(None, sys.stdin.readline)
                if not line:
                    logger.info("Stdin closed")
                    break
                raw_line = line.strip()
                if not raw_line:
                    continue
                
                logger.debug(f"FWD -> CLOUD: {raw_line[:120]}")
                
                # Prepare headers for this specific request
                headers = auth_headers.copy()
                if current_session_id:
                    headers["mcp-session-id"] = current_session_id
                    
                response = await client.post(mcp_post_url, headers=headers, content=raw_line)
                
                if response.status_code >= 400:
                    logger.error(f"Cloud POST failed: {response.status_code} - {response.text}")
                    continue
                
                # Capture session ID from response headers if it's there
                sid = response.headers.get("mcp-session-id")
                if sid:
                    if sid != current_session_id:
                        logger.info(f"Captured new session ID: {sid}")
                        current_session_id = sid
                
                output = response.text.strip()
                sys.stdout.write(output + "\n")
                sys.stdout.flush()
                logger.debug(f"FWD <- CLOUD: {output[:120]}")
                
            except Exception as e:
                logger.error(f"Proxy loop error: {e}")
                logger.error(traceback.format_exc())


if __name__ == "__main__":
    try:
        asyncio.run(run_proxy())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.error(f"FATAL: {e}")
        logger.error(traceback.format_exc())
