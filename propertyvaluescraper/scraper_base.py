import asyncio
import os
import random

from dotenv import load_dotenv
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
from playwright_stealth import Stealth

load_dotenv()

DEBUG = os.getenv("SCRAPER_DEBUG", "").lower() in ("1", "true")

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
]


def _get_proxy() -> dict | None:
    host = os.getenv("PROXY_HOST")
    port = os.getenv("PROXY_PORT")
    if not host or not port:
        return None
    config = {"server": f"http://{host}:{port}"}
    user = os.getenv("PROXY_USER")
    pwd = os.getenv("PROXY_PASS")
    if user and pwd:
        config["username"] = user
        config["password"] = pwd
    return config


def _get_headers(ua: str) -> dict:
    is_firefox = "Firefox" in ua
    return {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
        **({"Sec-Ch-Ua-Mobile": "?0", "Sec-Ch-Ua-Platform": '"Windows"'} if not is_firefox else {}),
    }


async def random_delay(min_s: float = 2.0, max_s: float = 5.0):
    await asyncio.sleep(random.uniform(min_s, max_s))


async def new_page(playwright):
    ua = random.choice(_USER_AGENTS)
    browser = await playwright.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
    )
    context = await browser.new_context(
        user_agent=ua,
        viewport={"width": random.choice([1280, 1366, 1440, 1920]), "height": random.choice([768, 800, 900, 1080])},
        extra_http_headers=_get_headers(ua),
        locale="en-US",
        timezone_id="America/New_York",
    )
    page = await context.new_page()
    await Stealth().apply_stealth_async(page)
    return browser, page


async def goto_with_retry(page, url: str, max_retries: int = 3) -> bool:
    for attempt in range(max_retries):
        try:
            await page.goto(url, timeout=40000, wait_until="domcontentloaded")
            await random_delay(1.5, 3.0)
            if DEBUG:
                body = await page.inner_text("body")
                print(f"[debug] url={page.url}")
                print(f"[debug] body[:500]:\n{body[:500]}\n")
            return True
        except PlaywrightTimeout:
            if attempt == max_retries - 1:
                return False
            wait = (2 ** attempt) + random.uniform(0, 1)
            if DEBUG:
                print(f"[debug] timeout on attempt {attempt + 1}, retrying in {wait:.1f}s")
            await asyncio.sleep(wait)
        except Exception as exc:
            if attempt == max_retries - 1:
                raise
            await asyncio.sleep(2 ** attempt)
    return False


async def run_with_retry(fn, max_retries: int = 3) -> dict:
    last_exc = None
    for attempt in range(max_retries):
        try:
            return await fn()
        except Exception as exc:
            last_exc = exc
            wait = (2 ** attempt) + random.uniform(0, 1)
            if DEBUG:
                print(f"[debug] attempt {attempt + 1} failed: {exc}, retrying in {wait:.1f}s")
            await asyncio.sleep(wait)
    return {"value": None, "error": str(last_exc)}
