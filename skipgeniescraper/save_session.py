"""
Run this once to capture a full session after manual login.
It opens a visible browser — log in yourself, then press Enter in the terminal.
All localStorage/cookies are saved to session.json for reuse.
"""
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

SESSION_FILE = Path(__file__).parent / "session.json"


async def capture():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(ignore_https_errors=True)
        page = await context.new_page()

        await page.goto("https://web.skipgenie.com/", wait_until="domcontentloaded")
        print("\n[*] Browser is open — log in manually (complete the CAPTCHA if needed).")
        print("[*] Press Enter here once you are fully logged in and see the dashboard...", end="", flush=True)
        await asyncio.get_event_loop().run_in_executor(None, input)

        # Capture full localStorage + sessionStorage
        storage = await page.evaluate("""() => ({
            localStorage: Object.keys(localStorage).reduce((a, k) => {
                a[k] = localStorage.getItem(k); return a;
            }, {}),
            sessionStorage: Object.keys(sessionStorage).reduce((a, k) => {
                a[k] = sessionStorage.getItem(k); return a;
            }, {})
        })""")

        # Capture cookies
        cookies = await context.cookies()

        session = {"storage": storage, "cookies": cookies, "url": page.url}
        SESSION_FILE.write_text(json.dumps(session, indent=2))
        print(f"\n[+] Session saved to {SESSION_FILE}")
        print(f"    localStorage keys: {list(storage['localStorage'].keys())}")
        print(f"    cookies: {[c['name'] for c in cookies]}")

        await browser.close()


asyncio.run(capture())
