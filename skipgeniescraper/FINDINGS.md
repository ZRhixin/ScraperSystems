# Research Wizard Scraper — Findings & Notes

## Project Overview

Automation scrapers for the Research Wizard n8n workflow. Hosted at `D:\Github\scraperstesting`.
Python 3.11.7, virtual environment at `.venv`.

---

## Property Value Scraper (`propertyvaluescraper/`)

### Goal
Given a property address, return the estimated value from Zillow, Redfin, and Realtor.com.

### Architecture
- `scraper_base.py` — shared engine (proxy, user agents, headers, delays, retries)
- `property_value_scraper.py` — per-site scrapers using Playwright
- `property_value_handler.py` — HTTP server for n8n webhook (POST on port 8000)
- `main.py` — entry point

### n8n Integration
```
POST http://your-host:8000
Body: { "address": "123 Main St, Austin TX 78701" }
Response: { "address": "...", "zillow": {...}, "redfin": {...}, "realtor": {...} }
```

### Bot Detection — What We Tried

| Approach | Result |
|---|---|
| Playwright headless (plain) | Blocked immediately — Cloudflare / IP block |
| playwright-stealth | Still blocked — Cloudflare detects headless signals |
| 2captcha | Not viable — Zillow uses "Press & Hold" (no extractable sitekey); Realtor hard IP blocks (not a CAPTCHA) |
| ScraperAPI (standard) | Zillow + Realtor return 500 — require `premium=true` tier; Redfin lands on homepage (hash fragment URLs don't work server-side) |
| RentCast API | Works perfectly but replaced scraping with a data API |

### Current Implementation
Uses **Playwright + playwright-stealth + residential proxy (IPRoyal)**:
- 9 rotating real browser user agents (Chrome/Firefox/Safari/Edge)
- Full realistic headers (`Sec-Fetch-*`, `DNT`, `Cache-Control`)
- Random viewport sizes per session
- `random_delay(2–5s)` between page actions
- `goto_with_retry()` — 3 attempts with exponential backoff
- Proxy auto-loads from `.env` — works with or without proxy

### Proxy Setup (IPRoyal)
Fill in `.env` after signup at iproyal.com:
```
PROXY_HOST=geo.iproyal.com
PROXY_PORT=12321
PROXY_USER=your_username
PROXY_PASS=your_password
```
Estimated cost: ~$0.06 per address lookup (3 sites × ~3MB rendered).

### Known Selectors (may break if sites update)

**Zillow** — looks for Zestimate near keyword `"zestimate"` in page body
- Structured: `[data-testid='zestimate-text']`, `span[class*='Zestimate']`, `.zestimate-value`
- Fallback: text scan within 80 chars of keyword

**Redfin** — looks for Redfin Estimate
- Structured: `[data-rf-test-id='avmValue']`, `.avm-value span`, `.statsValue`
- Fallback: text scan near `"redfin estimate"`

**Realtor** — looks for listing price
- Structured: `[data-testid='card-price']`, `[data-testid='list-price']`
- Fallback: text scan near `"list price"`, `"home value"`

### Debugging
```
SCRAPER_DEBUG=1 python debug_scraper.py
```
Prints body sample and saves PNG screenshots for each site.

---

## SkipGenie Scraper (`skipgeniescraper/`)

### Goal
Given a person's name and/or address, search SkipGenie and return the result list.

### Site
- Login URL: `https://web.skipgenie.com/`
- Search URL: `https://web.skipgenie.com/user/search`
- SSL certificate is expired/invalid — requires `ignore_https_errors=True` in Playwright

### Authentication Findings

| Approach | Result |
|---|---|
| Direct login with Playwright | reCAPTCHA v2 checkbox escalates to image challenge ("select crosswalks") — bot detected |
| Cookie injection only (`utoken`) | Failed — app uses Redux Persist; `persist:root` in localStorage is also required |
| Cookie + localStorage injection | Works ✅ |

**Session storage mechanism:**
- Auth cookie: `utoken` (JWT, 24hr validity)
- Cookie browser expiry: ~4 hours (Playwright rejects expired cookies — must force `expires` to future)
- localStorage keys used: `persist:root` (Redux Persist), `_grecaptcha`, `device_id`
- **Critical**: `persist:root` must be restored for the session to be recognised

**Session workflow:**
1. First time: run `save_session.py` — opens visible browser, log in manually, session saved to `session.json`
2. `skipgenie_scraper.py` loads `session.json` and injects cookies + all localStorage keys via `add_init_script`
3. On expiry: scraper auto-detects redirect → calls `auto_login.py` → 2captcha solves reCAPTCHA → fresh session saved automatically

**Auto re-login (2captcha):**
- Detects session expiry by redirect away from `/user/search`
- Extracts reCAPTCHA sitekey → submits to 2captcha (~30s solve)
- Injects token → submits login form → saves fresh `session.json`
- Cost: ~$3/1000 re-logins (only on expiry, not per search)
- Requires `TWOCAPTCHA_API_KEY` in `.env`

### Search Form (at `/user/search`)
Inputs identified by placeholder (no `name`/`id` attributes — React app):

| Placeholder | Field |
|---|---|
| ` Enter First Name` | First name |
| ` Enter Last Name` | Last name |
| ` Enter Middle Name` | Middle name |
| ` Street Address` | Street address (appears twice — use `nth(0)` for Name Search section) |
| ` City` | City |
| ` State` | State |
| ` Zip/Postal Code` | Zip code |

**Submit flow:**
1. Fill form fields
2. Click `text=GET INFO` (Name Search) or `text=Get Info` (Address Search)
3. Confirmation dialog appears → click `text=Yes, Execute Search`
4. Wait ~5s for results

### Files
| File | Purpose |
|---|---|
| `save_session.py` | One-time manual login to capture full session state |
| `session.json` | Saved session (cookies + localStorage) — refresh daily |
| `test_login.py` | Verify session is valid and explore form structure |
| `skipgenie_scraper.py` | Main scraper — fill form, submit, extract results |

### Status
- Session injection: ✅ working
- Form filling + submission: built, not yet tested
- Result extraction: pending — need to see result HTML structure

---

## Environment

### `.env` keys in use
```
PROXY_HOST=geo.iproyal.com
PROXY_PORT=12321
PROXY_USER=
PROXY_PASS=
PORT=8000
SCRAPER_DEBUG=0
SKIPGENIE_EMAIL=...
SKIPGENIE_PASSWORD=...
```

### `requirements.txt`
```
requests
beautifulsoup4
lxml
playwright
playwright-stealth
python-dotenv
2captcha-python
```

### Running the property value server
```powershell
source .venv/Scripts/activate
python main.py         # starts on port 8000
```

### Testing property value scraper
```powershell
python debug_scraper.py
```

### Testing SkipGenie session
```powershell
python skipgeniescraper/save_session.py    # capture session (run when expired)
python skipgeniescraper/test_login.py      # verify session works
python skipgeniescraper/skipgenie_scraper.py  # run a test search
```
