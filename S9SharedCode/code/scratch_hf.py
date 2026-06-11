import asyncio
from playwright.async_api import async_playwright
import json

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        print("Navigating to URL...")
        await page.goto("https://huggingface.co/models?pipeline_tag=text-generation&sort=likes", wait_until="networkidle")
        print("Fetching a11y tree...")
        tree = await page.accessibility.snapshot()
        print("Writing a11y tree to tree.json...")
        with open("tree.json", "w", encoding="utf-8") as f:
            json.dump(tree, f, indent=2)
        await browser.close()
        print("Done.")

if __name__ == "__main__":
    asyncio.run(main())
