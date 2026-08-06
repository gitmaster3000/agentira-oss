
import asyncio
import httpx
import logging
import os
import sys
from mcp import ClientSession
from mcp.client.sse import sse_client

logging.basicConfig(level=logging.DEBUG, stream=sys.stdout)

async def main():
    url = "http://localhost:8000/sse"
    # Mint one in the UI (Settings → API keys) and export AGENTIRA_API_KEY.
    api_key = os.environ["AGENTIRA_API_KEY"]
    
    headers = {
        "Authorization": f"Bearer {api_key}"
    }

    try:
        print(f"Connecting to {url} (Authenticated)...")
        async with sse_client(url, headers=headers) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                print("Successfully initialized session")
                tools = await session.list_tools()
                print(f"Available tools: {tools}")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
