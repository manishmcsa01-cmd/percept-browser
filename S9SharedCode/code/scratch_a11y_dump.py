import asyncio
from playwright.async_api import async_playwright
import os
import sys

# add parent dir to path so we can import browser.dom
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from browser.dom import enumerate_interactives

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://huggingface.co/models?pipeline_tag=text-generation&sort=likes", wait_until="networkidle")
        snap = await enumerate_interactives(page)
        for e in snap.elements:
            if "deepseek" in e.name.lower() or "llama" in e.name.lower():
                print(e.legend_line())
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
