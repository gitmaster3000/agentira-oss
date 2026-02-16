import sys
import os
import json
import asyncio
import logging
from typing import Optional
from mcp.client.session import ClientSession
from mcp.client.sse import sse_client

# Configure logging to file to avoid stdout pollution
log_file = os.path.join(os.path.expanduser("~"), ".agentira_mcp_proxy.log")
logging.basicConfig(
    level=logging.INFO,
    filename=log_file,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger("mcp_proxy")

async def get_api_key() -> Optional[str]:
    """Discover the API key from environment or local workspace file."""
    # 1. Environment Variable
    ev = os.environ.get("AGENTIRA_API_KEY")
    if ev:
        logger.info("Using API key from environment variable.")
        return ev
    
    # 2. Local File
    key_path = os.path.join(os.getcwd(), ".agent", "mcp_key.txt")
    if os.path.exists(key_path):
        with open(key_path, 'r') as f:
            key = f.read().strip()
            if key:
                logger.info(f"Using API key from {key_path}")
                return key
    
    return None

async def run_proxy():
    """
    Standard input/output (stdio) proxy to Cloud SSE server.
    """
    api_key = await get_api_key()
    if not api_key:
        logger.error("No API key found in AGENTIRA_API_KEY or .agent/mcp_key.txt")
        # Send an error message back to the client if possible, or just exit
        sys.exit(1)

    # Cloud URL - In production, this would be your hosted endpoint
    cloud_url = "http://127.0.0.1:8111/sse" 
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "X-Proxy-Workspace": os.getcwd()
    }

    try:
        async with sse_client(cloud_url, headers=headers) as (read_stream, write_stream):
            logger.info(f"Connected to cloud MCP at {cloud_url}")
            
            # Bridge stdio to SSE
            # IDE -> Proxy (stdin) -> Cloud (write_stream)
            # Cloud (read_stream) -> Proxy -> IDE (stdout)
            
            async def forward_to_cloud():
                while True:
                    line = await asyncio.get_event_loop().run_in_executor(None, sys.stdin.readline)
                    if not line:
                        break
                    try:
                        # Forward the raw JSON message
                        await write_stream.send(line)
                        logger.debug(f"FWD -> CLOUD: {line.strip()}")
                    except Exception as e:
                        logger.error(f"Error forwarding to cloud: {e}")
                        break

            async def forward_to_client():
                async for message in read_stream:
                    # Message is already a string from sse_client
                    sys.stdout.write(message)
                    sys.stdout.flush()
                    logger.debug(f"FWD <- CLIENT: {message.strip()}")

            # Run both forwarding tasks concurrently
            await asyncio.gather(
                forward_to_cloud(),
                forward_to_client()
            )

    except Exception as e:
        logger.error(f"Proxy runtime error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--test-key":
        # Helper mode to verify key discovery
        key = asyncio.run(get_api_key())
        print(f"Discovered Key: {key}")
    else:
        try:
            asyncio.run(run_proxy())
        except KeyboardInterrupt:
            pass
