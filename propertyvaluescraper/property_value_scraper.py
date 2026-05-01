import asyncio
import os
import re
from urllib.parse import quote_plus

from dotenv import load_dotenv
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

from .scraper_base import DEBUG, goto_with_retry, new_page, random_delay, run_with_retry

load_dotenv()


def _extract_dollar(text: str) -> str | None:
    match = re.search(r"\$[\d,]+(?:\.\d+)?[KkMm]?", text or "")
    return match.group() if match else None


def _find_near_keyword(body: str, keyword: str, window: int = 80) -> str | None:
    idx = body.lower().find(keyword.lower())
    if idx == -1:
        return None
    return _extract_dollar(body[max(0, idx - 5): idx + window])


async def scrape_zillow(address: str) -> dict:
    async def _run():
        async with async_playwright() as p:
            browser, page = await new_page(p)
            try:
                encoded = quote_plus(address)
                ok = await goto_with_retry(page, f"https://www.zillow.com/homes/{encoded}_rb/")
                if not ok:
                    return {"value": None, "error": "timeout"}

                # If search results page, click first property card
                card = page.locator("article[data-test='property-card']").first
                if await card.count() > 0:
                    await random_delay(1.0, 2.5)
                    async with page.expect_navigation(timeout=25000):
                        await card.click()
                    await random_delay(2.0, 4.0)

                # Structured selectors
                for selector in [
                    "[data-testid='zestimate-text']",
                    "span[class*='Zestimate']",
                    ".zestimate-value",
                ]:
                    el = page.locator(selector).first
                    if await el.count() > 0:
                        text = await el.text_content(timeout=5000)
                        value = _extract_dollar(text)
                        if value:
                            return {"value": value, "source": "zillow"}

                # Text fallback
                body = await page.inner_text("body")
                value = _find_near_keyword(body, "zestimate")
                if value:
                    return {"value": value, "source": "zillow"}

                if DEBUG:
                    print(f"[debug:zillow] body sample:\n{body[:1500]}")

                return {"value": None, "error": "value not found"}

            finally:
                await browser.close()

    return await run_with_retry(_run)


async def scrape_redfin(address: str) -> dict:
    async def _run():
        async with async_playwright() as p:
            browser, page = await new_page(p)
            try:
                encoded = quote_plus(address)
                ok = await goto_with_retry(page, f"https://www.redfin.com/search#location={encoded}")
                if not ok:
                    return {"value": None, "error": "timeout"}

                await random_delay(2.0, 4.0)

                # Click first result card
                for selector in [
                    "a[data-rf-test-id='basic-card-link']",
                    ".HomeCardContainer a",
                    ".homes.summary a",
                ]:
                    result = page.locator(selector).first
                    if await result.count() > 0:
                        async with page.expect_navigation(timeout=25000):
                            await result.click()
                        await random_delay(2.0, 4.0)
                        break

                # Structured selectors
                for selector in [
                    "[data-rf-test-id='avmValue']",
                    ".avm-value span",
                    ".statsValue",
                    "[class*='estimateValue']",
                ]:
                    el = page.locator(selector).first
                    if await el.count() > 0:
                        text = await el.text_content(timeout=5000)
                        value = _extract_dollar(text)
                        if value:
                            return {"value": value, "source": "redfin"}

                # Text fallback
                body = await page.inner_text("body")
                value = _find_near_keyword(body, "redfin estimate")
                if value:
                    return {"value": value, "source": "redfin"}

                if DEBUG:
                    print(f"[debug:redfin] body sample:\n{body[:1500]}")

                return {"value": None, "error": "value not found"}

            finally:
                await browser.close()

    return await run_with_retry(_run)


async def scrape_realtor(address: str) -> dict:
    async def _run():
        async with async_playwright() as p:
            browser, page = await new_page(p)
            try:
                encoded = quote_plus(address)
                ok = await goto_with_retry(page, f"https://www.realtor.com/realestateandhomes-search/{encoded}")
                if not ok:
                    return {"value": None, "error": "timeout"}

                # Try price from first card directly
                for selector in [
                    "[data-testid='card-price']",
                    "[data-testid='listing-price']",
                    ".price-label",
                ]:
                    el = page.locator(selector).first
                    if await el.count() > 0:
                        text = await el.text_content(timeout=5000)
                        value = _extract_dollar(text)
                        if value:
                            return {"value": value, "source": "realtor"}

                # Click first listing for detail page
                link = page.locator("a[data-testid='property-anchor']").first
                if await link.count() > 0:
                    await random_delay(1.0, 2.5)
                    async with page.expect_navigation(timeout=25000):
                        await link.click()
                    await random_delay(2.0, 4.0)

                    for selector in [
                        "[data-testid='list-price']",
                        "[data-testid='price-avm']",
                        ".price-display",
                    ]:
                        el = page.locator(selector).first
                        if await el.count() > 0:
                            text = await el.text_content(timeout=5000)
                            value = _extract_dollar(text)
                            if value:
                                return {"value": value, "source": "realtor"}

                # Text fallback
                body = await page.inner_text("body")
                for keyword in ["home value", "estimated value", "list price"]:
                    value = _find_near_keyword(body, keyword)
                    if value:
                        return {"value": value, "source": "realtor"}

                if DEBUG:
                    print(f"[debug:realtor] body sample:\n{body[:1500]}")

                return {"value": None, "error": "value not found"}

            finally:
                await browser.close()

    return await run_with_retry(_run)


async def scrape_all(address: str) -> dict:
    zillow, redfin, realtor = await asyncio.gather(
        scrape_zillow(address),
        scrape_redfin(address),
        scrape_realtor(address),
    )
    return {
        "address": address,
        "zillow": zillow,
        "redfin": redfin,
        "realtor": realtor,
    }
