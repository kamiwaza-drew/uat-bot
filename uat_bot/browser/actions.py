from __future__ import annotations

from playwright.async_api import Page


async def navigate(page: Page, url: str) -> None:
    await page.goto(url, wait_until="domcontentloaded")


async def click(page: Page, selector: str) -> None:
    await page.click(selector)


async def fill(page: Page, selector: str, value: str) -> None:
    await page.fill(selector, value)
