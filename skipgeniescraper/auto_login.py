"""
Automated SkipGenie login using 2captcha to solve the reCAPTCHA.
Saves the full session (cookies + localStorage) to session.json on success.
Called automatically by the scraper when session expires.
"""
import asyncio
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
from twocaptcha import TwoCaptcha

load_dotenv()

EMAIL = os.getenv("SKIPGENIE_EMAIL")
PASSWORD = os.getenv("SKIPGENIE_PASSWORD")
API_KEY = os.getenv("TWOCAPTCHA_API_KEY")
LOGIN_URL = "https://web.skipgenie.com/"
SESSION_FILE = Path(__file__).parent / "session.json"


async def _extract_sitekey(page) -> str | None:
    import re

    # Wait for reCAPTCHA iframe to appear (it's injected by JS)
    try:
        await page.wait_for_selector(
            "iframe[src*='recaptcha'], .g-recaptcha, [data-sitekey]",
            timeout=10000,
        )
    except Exception:
        pass

    # Try extracting from rendered DOM via JS
    sitekey = await page.evaluate("""() => {
        const el = document.querySelector('[data-sitekey]');
        if (el) return el.getAttribute('data-sitekey');
        const iframe = document.querySelector('iframe[src*="recaptcha"]');
        if (iframe) {
            const match = iframe.src.match(/[?&]k=([^&]+)/);
            if (match) return match[1];
        }
        return null;
    }""")

    if sitekey:
        return sitekey

    # Fallback: regex on full rendered HTML
    html = await page.content()
    match = re.search(r'data-sitekey=["\']([^"\']+)["\']', html)
    if match:
        return match.group(1)

    # Last resort: check iframe src for sitekey param
    match = re.search(r'recaptcha[^"\']*[?&]k=([A-Za-z0-9_-]+)', html)
    return match.group(1) if match else None


async def _solve_recaptcha(page) -> str | None:
    """Submit reCAPTCHA to 2captcha and return the solution token."""
    if not API_KEY:
        raise RuntimeError("TWOCAPTCHA_API_KEY not set in .env")

    sitekey = await _extract_sitekey(page)
    if not sitekey:
        # Debug: show what's on the page
        body = await page.inner_text("body")
        print(f"[!] Could not find reCAPTCHA sitekey. Page content:\n{body[:600]}")
        return None

    print(f"[*] Sending reCAPTCHA to 2captcha (sitekey: {sitekey[:20]}...)...")
    solver = TwoCaptcha(API_KEY)

    # Run blocking 2captcha call in thread to avoid blocking event loop
    result = await asyncio.to_thread(
        solver.recaptcha,
        sitekey=sitekey,
        url=page.url,
    )
    token = result["code"]
    print(f"[*] Got solution token: {token[:30]}...")
    return token


async def _inject_recaptcha_token(page, token: str):
    """Inject the 2captcha solution token into the reCAPTCHA response field."""
    await page.evaluate(f"""
        (() => {{
            // Standard reCAPTCHA v2 response field
            const el = document.getElementById('g-recaptcha-response');
            if (el) {{
                el.innerHTML = '{token}';
                el.value = '{token}';
            }}
            // Also set on any hidden textarea with similar names
            document.querySelectorAll('[name="g-recaptcha-response"]').forEach(e => {{
                e.value = '{token}';
            }});
            // Trigger the reCAPTCHA callback if defined
            if (typeof grecaptcha !== 'undefined') {{
                try {{
                    const widgetId = Object.keys(grecaptcha).find(k => !isNaN(k));
                    if (widgetId !== undefined) grecaptcha.getResponse(widgetId);
                }} catch(e) {{}}
            }}
        }})()
    """)


async def login() -> bool:
    """
    Perform automated login with 2captcha CAPTCHA solving.
    Returns True if login succeeded and session was saved.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(ignore_https_errors=True)
        page = await context.new_page()

        try:
            print("[*] Navigating to login page...")
            await page.goto(LOGIN_URL, timeout=30000, wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)
            await page.screenshot(path="skipgeniescraper/login_01_loaded.png")

            print("[*] Filling credentials...")
            await page.fill(
                "input[type='email'], input[name='email'], input[placeholder*='email' i]",
                EMAIL,
            )
            await page.fill(
                "input[type='password'], input[name='password'], input[placeholder*='password' i]",
                PASSWORD,
            )
            await page.wait_for_timeout(1000)
            await page.screenshot(path="skipgeniescraper/login_02_filled.png")

            # Solve reCAPTCHA
            token = await _solve_recaptcha(page)
            if not token:
                return False

            await _inject_recaptcha_token(page, token)
            await page.wait_for_timeout(1500)
            await page.screenshot(path="skipgeniescraper/login_03_token_injected.png")

            # Log all buttons visible on page
            buttons = await page.query_selector_all("button, input[type='submit']")
            print(f"[*] Buttons found ({len(buttons)}):")
            for btn in buttons:
                txt = await btn.inner_text()
                t = await btn.get_attribute("type")
                disabled = await btn.get_attribute("disabled")
                print(f"    type={t} disabled={disabled} text={txt.strip()!r}")

            # Submit the login form
            print("[*] Submitting login form...")
            await page.click(
                "button[type='submit'], input[type='submit'], "
                "button:has-text('Login'), button:has-text('Sign in')"
            )

            # React SPA — no full navigation, wait for URL to change away from login
            try:
                await page.wait_for_function(
                    f"() => window.location.href !== '{LOGIN_URL}' && "
                    "!window.location.href.includes('login')",
                    timeout=20000,
                )
            except Exception:
                pass

            await page.wait_for_timeout(3000)
            print(f"[*] Post-submit URL: {page.url}")

            # Verify we're logged in
            if page.url.rstrip("/") == LOGIN_URL.rstrip("/") or "login" in page.url.lower():
                body = await page.inner_text("body")
                print(f"[!] Still on login page. Body:\n{body[:400]}")
                return False

            print(f"[+] Login successful — URL: {page.url}")

            # Save full session
            storage = await page.evaluate("""() => ({
                localStorage: Object.keys(localStorage).reduce((a, k) => {
                    a[k] = localStorage.getItem(k); return a;
                }, {}),
                sessionStorage: Object.keys(sessionStorage).reduce((a, k) => {
                    a[k] = sessionStorage.getItem(k); return a;
                }, {})
            })""")
            cookies = await context.cookies()
            session = {"storage": storage, "cookies": cookies, "url": page.url}
            SESSION_FILE.write_text(json.dumps(session, indent=2))
            print(f"[+] Session saved to {SESSION_FILE}")
            return True

        except PlaywrightTimeout as exc:
            print(f"[!] Timeout during login: {exc}")
            await page.screenshot(path="skipgeniescraper/login_timeout.png")
            return False
        except Exception as exc:
            print(f"[!] Login error: {exc}")
            return False
        finally:
            await browser.close()


if __name__ == "__main__":
    success = asyncio.run(login())
    print("[+] Done" if success else "[!] Login failed")
