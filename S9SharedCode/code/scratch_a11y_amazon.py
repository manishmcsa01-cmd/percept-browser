import asyncio
from browser.driver import BaseDriver
from playwright.async_api import async_playwright
from browser.dom import enumerate_interactives

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        
        await page.goto("https://www.amazon.in/s?k=laptops+under+80000&s=price-asc-rank")
        await asyncio.sleep(2)
        
        snap = await enumerate_interactives(page)
        summary = snap.legend()
        print("A11y summary preview:")
        print(summary[:2000])
        print("...\nTotal length:", len(summary))
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
