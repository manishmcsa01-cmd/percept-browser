import asyncio
from playwright.async_api import async_playwright
import sys
import os

sys.path.append("c:\\manish\\SchoolOfAI\\session9\\S9SharedCode\\code")
from browser.dom import enumerate_interactives

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://huggingface.co/models?pipeline_tag=text-generation&sort=likes", wait_until="networkidle")
        snap = await enumerate_interactives(page)
        with open("snap.txt", "w", encoding="utf-8") as f:
            for e in snap.elements:
                f.write(e.legend_line() + "\n")
        await browser.close()
        print("Done. Saved to snap.txt")

if __name__ == "__main__":
    asyncio.run(main())
