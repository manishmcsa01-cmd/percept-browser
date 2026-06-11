import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://huggingface.co/models?pipeline_tag=text-generation&sort=likes", wait_until="networkidle")
        card = await page.locator("article").first.evaluate("el => el.outerHTML")
        print(card)
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
