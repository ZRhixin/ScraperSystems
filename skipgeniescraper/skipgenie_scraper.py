import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

SESSION_FILE = Path(__file__).parent / "session.json"
SEARCH_URL = "https://web.skipgenie.com/user/search"


def _load_session() -> dict:
    if not SESSION_FILE.exists():
        raise FileNotFoundError("session.json not found — run auto_login.py first")
    return json.loads(SESSION_FILE.read_text())


async def _ensure_session() -> bool:
    """Re-login via 2captcha if session.json is missing or expired."""
    from .auto_login import login
    print("[*] Session expired — attempting auto re-login via 2captcha...")
    return await login()


async def _restore_session(context, session: dict):
    if session.get("cookies"):
        await context.add_cookies(session["cookies"])
    ls = json.dumps(session["storage"].get("localStorage", {}))
    ss = json.dumps(session["storage"].get("sessionStorage", {}))
    await context.add_init_script(f"""
        const ls = {ls};
        const ss = {ss};
        Object.keys(ls).forEach(k => localStorage.setItem(k, ls[k]));
        Object.keys(ss).forEach(k => sessionStorage.setItem(k, ss[k]));
    """)


async def search(
    first_name: str = "",
    last_name: str = "",
    middle_name: str = "",
    street_address: str = "",
    city: str = "",
    state: str = "",
    zip_code: str = "",
) -> dict:
    session = _load_session()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(ignore_https_errors=True)
        await _restore_session(context, session)
        page = await context.new_page()

        try:
            await page.goto(SEARCH_URL, timeout=30000, wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)

            # Verify session is still valid — auto re-login if expired
            if page.url.rstrip("/") != SEARCH_URL.rstrip("/"):
                print("[*] Session invalid, triggering auto re-login...")
                success = await _ensure_session()
                if not success:
                    return {"error": "session_expired", "message": "Auto re-login failed — check 2captcha key"}
                # Retry once with fresh session
                return await search(
                    first_name=first_name, last_name=last_name,
                    middle_name=middle_name, street_address=street_address,
                    city=city, state=state, zip_code=zip_code,
                )

            # Ensure Name Search tab is active
            name_tab = page.locator("li.active-tabs").first
            if await name_tab.count() == 0:
                await page.locator("li.tabs").first.click()
                await page.wait_for_timeout(500)

            # Fill Name Search form fields by placeholder
            fields = {
                "Enter First Name": first_name,
                "Enter Last Name": last_name,
                "Enter Middle Name": middle_name,
                "Street Address": street_address,
                "City": city,
                "State": state,
                "Zip/Postal Code": zip_code,
            }
            for placeholder, value in fields.items():
                if value:
                    el = page.locator(f"input[placeholder*='{placeholder}']").nth(0)
                    if await el.count() > 0:
                        await el.fill(value)

            await page.screenshot(path="skipgeniescraper/search_filled.png")

            # Click Get Info button (Name Search section)
            await page.locator("button.pu_btn_user_search").first.click()
            await page.wait_for_timeout(1500)
            await page.screenshot(path="skipgeniescraper/search_confirm.png")

            # Handle confirmation dialog
            confirm_btn = page.locator("text=Yes, Execute Search")
            if await confirm_btn.count() > 0:
                await confirm_btn.click()

            # Wait for results to load
            await page.wait_for_timeout(5000)
            await page.screenshot(path="skipgeniescraper/search_results.png")

            # Extract results from #userSearchdata container
            results_container = page.locator("#userSearchdata")
            if await results_container.count() > 0:
                results_html = await results_container.inner_html()
                results_text = await results_container.inner_text()
                print(f"[*] Results container found. Text (first 2000 chars):\n{results_text[:2000]}")
                (Path(__file__).parent / "search_results.html").write_text(results_html)
                print("[*] Results HTML saved to skipgeniescraper/search_results.html")
                return {"status": "ok", "url": page.url, "results_text": results_text}
            else:
                body = await page.inner_text("body")
                print(f"[*] No results container found. Body (first 2000 chars):\n{body[:2000]}")
                html = await page.content()
                (Path(__file__).parent / "search_results.html").write_text(html)
                print("[*] Full HTML saved to skipgeniescraper/search_results.html")
                return {"status": "ok", "url": page.url, "results_text": None}

        except PlaywrightTimeout:
            return {"error": "timeout"}
        except Exception as exc:
            return {"error": str(exc)}
        finally:
            await browser.close()


if __name__ == "__main__":
    result = asyncio.run(search(
        first_name="James",
        last_name="Smith",
        city="Miami",
        state="FL",
    ))
    print(result)
