import asyncio
import trafilatura
import httpx
from browser.skill import _extract, detect_gateway_block, _fetch_html

async def main():
    url = "https://www.amazon.in/s?k=laptops+under+80000"
    html, final_url = await _fetch_html(url)
    block = detect_gateway_block(html)
    print("Block:", block)
    content = _extract(html)
    print("Content preview:")
    print(content[:1000])
    print("...")
    print("Content length:", len(content))

if __name__ == "__main__":
    asyncio.run(main())
