import sys
import os
import json
import asyncio
import logging
import traceback
from typing import Optional

try:
    from mcp.client.sse import sse_client
    from mcp.types import JSONRPCMessage
    from mcp.shared.message import SessionMessage
except ImportError:
    # This shouldn't happen in the real environment but good for local testing
    pass

# Configuration
LOG_FILE = r"C:\agentira\agentira_mcp_proxy.log"

def setup_logging():
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)
    logging.basicConfig(
        level=logging.INFO,
        filename=LOG_FILE,
        filemode='a',
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
    )
    return logging.getLogger("mcp_proxy")

logger = setup_logging()

async def get_api_key() -> Optional[str]:
    """Discover the API key from environment or local workspace file."""
    ev = os.environ.get("AGENTIRA_API_KEY")
    if ev: return ev
    
    current_dir = os.getcwd()
    candidates = [current_dir, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]
    for start_dir in candidates:
        search_dir = start_dir
        while search_dir:
            key_path = os.path.join(search_dir, ".agent", "mcp_key.txt")
            if os.path.exists(key_path):
                with open(key_path, 'r') as f:
                    key = f.read().strip()
                    if key: return key
            parent_dir = os.path.dirname(search_dir)
            if parent_dir == search_dir: break
            search_dir = parent_dir
    return None

async def run_proxy():
    api_key = await get_api_key()
    if not api_key:
        logger.error("CRITICAL: No API key found.")
        sys.exit(1)

    # Note: Using the consolidated /sse endpoint
    cloud_url = "http://127.0.0.1:8000/sse"
    auth_headers = {
        "Authorization": f"Bearer {api_key}",
        "X-Proxy-Workspace": os.getcwd(),
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    logger.info(f"--- STARTING MCP PROXY SHIM ---")
    
    try:
        async with sse_client(cloud_url, headers=auth_headers) as (read_stream, write_stream):
            logger.info(f"CONNECTED to cloud MCP at {cloud_url}")
            
            async def forward_to_cloud():
                try:
                    while True:
                        line = await asyncio.get_event_loop().run_in_executor(None, sys.stdin.readline)
                        if not line:
                            logger.info("Stdin closed")
                            break
                        
                        raw_line = line.strip()
                        if not raw_line: continue
                        
                        try:
                            data = json.loads(raw_line)
                            message = JSONRPCMessage.model_validate(data)
                            session_msg = SessionMessage(message=message)
                            await write_stream.send(session_msg)
                            logger.debug(f"FWD -> CLOUD: {raw_line[:100]}")
                        except Exception as e:
                            logger.error(f"Failed to process stdin: {e}")
                except Exception as e:
                    logger.error(f"forward_to_cloud error: {e}")

            async def forward_to_client():
                try:
                    async for msg_wrapper in read_stream:
                        try:
                            # Extract the raw JSONRPCMessage if it's wrapped in a SessionMessage
                            message = msg_wrapper.message if hasattr(msg_wrapper, "message") else msg_wrapper
                            
                            # Use Pydantic serialization for the JSONRPCMessage
                            if hasattr(message, "model_dump_json"):
                                output = message.model_dump_json()
                            elif hasattr(message, "json"):
                                output = message.json()
                            else:
                                output = json.dumps(message)
                            
                            sys.stdout.write(output + "\n")
                            sys.stdout.flush()
                            logger.debug(f"FWD <- CLIENT: {output[:100]}")
                        except Exception as e:
                            logger.error(f"Serialize error: {e}")
                except Exception as e:
                    logger.error(f"forward_to_client error: {e}")

            await asyncio.gather(forward_to_cloud(), forward_to_client())

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
