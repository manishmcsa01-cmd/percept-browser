import asyncio
from mcp_server import fetch_url

async def test_fetch():
    result = await fetch_url("https://example.com")
    print(f"Status: {result.get('status')}")
    print(f"Text snippet: {result.get('text')[:100]}")

if __name__ == "__main__":
    asyncio.run(test_fetch())
