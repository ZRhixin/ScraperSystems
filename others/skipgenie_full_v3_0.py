#!/usr/bin/env python3
"""
SkipGenie Full Scraper - Undetected ChromeDriver (v3.0)
========================================================

Complete scraper with ENHANCED business logic:
- CSV input/output with resume capability
- DOM-based results parsing
- 60-day threshold for current resident

NEW IN v3.0 - ADDRESS GROUPING:
- Groups input rows by address (searches each address only ONCE)
- Supports multiple input owners per address
- Checks results against ALL owners for that address
- Hierarchical output: PROPERTY row + RESIDENT rows

OUTPUT STRUCTURE:
- PROPERTY row: Overall status, combined DBIDs, all input owners
- RESIDENT rows: Individual person details and their status

PROPERTY STATUS (priority order):
1. Owner-Occupied - Any input owner is living there
2. Heir-Occupied - Any heir (last name match) living there
3. Relative-Occupied - Relative with matching owner name
4. Non-Heir-Occupied - Living residents, no family connection
5. Vacant / Vacant Estate / No Results

RESIDENT STATUS:
- Input Owner - This person matches an input owner
- Heir - Last name matches an input owner
- Possible Relative - Has relative matching owner name
- Non-Heir - No connection to any input owner

USAGE:
  python3 skipgenie_full.py   (or use Start Bot launcher)
"""

import os
import re
import time
import random
import logging
import logging.handlers
import pandas as pd
import subprocess
import signal
import sys
from datetime import datetime, timedelta

# Force UTF-8 on Windows console so Unicode characters never crash
if sys.platform == "win32":
    try:
        if sys.stdout is not None:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if sys.stderr is not None:
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
from typing import List, Dict, Optional, Tuple

# =============================================================================
# Prevent system from sleeping while script runs (Windows + Mac)
# =============================================================================
CAFFEINATE_PROCESS = None

# Windows SetThreadExecutionState flags
_ES_CONTINUOUS        = 0x80000000
_ES_SYSTEM_REQUIRED   = 0x00000001
_ES_DISPLAY_REQUIRED  = 0x00000002

_keep_awake_thread = None
_keep_awake_stop = False

def start_caffeinate():
    """Prevent the system from sleeping during scraping."""
    global CAFFEINATE_PROCESS, _keep_awake_thread, _keep_awake_stop
    if sys.platform == "win32":
        try:
            import ctypes
            import threading
            _keep_awake_stop = False
            def _refresh():
                """Refresh every 30s — prevents Windows power policy from overriding."""
                while not _keep_awake_stop:
                    ctypes.windll.kernel32.SetThreadExecutionState(
                        _ES_CONTINUOUS | _ES_SYSTEM_REQUIRED | _ES_DISPLAY_REQUIRED
                    )
                    time.sleep(30)
            _keep_awake_thread = threading.Thread(target=_refresh, daemon=True)
            _keep_awake_thread.start()
            print("💡 Sleep prevention active — computer will stay awake during scraping")
        except Exception as e:
            print(f"⚠️  Could not enable sleep prevention: {e}")
    else:
        try:
            CAFFEINATE_PROCESS = subprocess.Popen(
                ['caffeinate', '-d', '-i'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            print("☕ Caffeinate started - Mac will stay awake during scraping")
        except Exception as e:
            print(f"⚠️  Could not start caffeinate: {e}")

def stop_caffeinate():
    """Re-enable system sleep when script ends."""
    global _keep_awake_stop
    if sys.platform == "win32":
        try:
            import ctypes
            _keep_awake_stop = True
            ctypes.windll.kernel32.SetThreadExecutionState(_ES_CONTINUOUS)
            print("💤 Sleep prevention removed")
        except Exception:
            pass
    else:
        global CAFFEINATE_PROCESS
        if CAFFEINATE_PROCESS:
            try:
                CAFFEINATE_PROCESS.terminate()
                CAFFEINATE_PROCESS.wait(timeout=2)
                print("☕ Caffeinate stopped - Mac can sleep now")
            except:
                pass
            CAFFEINATE_PROCESS = None

def signal_handler(signum, frame):
    """Handle Ctrl+C gracefully."""
    stop_caffeinate()
    sys.exit(0)

# Register signal handler for clean exit
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


def get_chrome_version() -> int | None:
    """Auto-detect the installed Chrome major version number."""
    if sys.platform == "win32":
        try:
            import winreg
            for hive in [winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER]:
                for path in [
                    r"SOFTWARE\Google\Chrome\BLBeacon",
                    r"SOFTWARE\Wow6432Node\Google\Chrome\BLBeacon",
                ]:
                    try:
                        with winreg.OpenKey(hive, path) as key:
                            version = winreg.QueryValueEx(key, "version")[0]
                            major = int(version.split(".")[0])
                            return major
                    except Exception:
                        pass
        except Exception:
            pass
    else:
        # macOS / Linux
        for cmd in [
            ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "--version"],
            ["google-chrome", "--version"],
            ["chromium-browser", "--version"],
        ]:
            try:
                out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode()
                match = re.search(r"(\d+)\.\d+\.\d+", out)
                if match:
                    return int(match.group(1))
            except Exception:
                pass
    return None

# Determine script directory for relative paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEBUG_LOG = os.path.join(SCRIPT_DIR, "debug.log")

# Set up logging - file gets DEBUG (detailed), console gets INFO (clean)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# File handler — rotates at 10 MB, keeps 3 backups (debug.log, debug.log.1, debug.log.2)
file_handler = logging.handlers.RotatingFileHandler(
    DEBUG_LOG, maxBytes=10 * 1024 * 1024, backupCount=3, encoding='utf-8'
)
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

# Console handler - only important messages
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.WARNING)  # Only warnings and errors to console
console_handler.setFormatter(logging.Formatter('%(message)s'))

logger.addHandler(file_handler)
logger.addHandler(console_handler)

# Suppress noisy Selenium/urllib3 logs from console
logging.getLogger('selenium').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)
logging.getLogger('undetected_chromedriver').setLevel(logging.WARNING)

# =============================================================================
# Configuration
# =============================================================================

# Single login (edit these for your SkipGenie account)
SKIPGENIE_EMAIL = "brandyn@thelocalhousebuyers.com"
SKIPGENIE_PASSWORD = "Webuyhouses123!"

LOGIN_URL = "https://web.skipgenie.com/user/login"
SEARCH_URL = "https://web.skipgenie.com/user/search?tab=name"

# SCRIPT_DIR already defined above for logging
INPUT_FILE    = os.path.join(SCRIPT_DIR, "whos_input.csv")
OUTPUT_FILE   = os.path.join(SCRIPT_DIR, "whos_output.csv")
PROCEED_FLAG  = os.path.join(SCRIPT_DIR, "proceed.flag")
STOP_FLAG     = os.path.join(SCRIPT_DIR, "stop_requested.flag")

# Thresholds
CURRENT_RESIDENT_DAYS = 60
SAVE_EVERY_N_RECORDS = 1  # Save after every address so output is never lost
RETRY_ATTEMPTS = 2  # Retry twice on failure (total 3 attempts)
MIN_DELAY = 3.0
MAX_DELAY = 6.0
MAX_PEOPLE_PER_ADDRESS = 20  # Max people to check per address (up from 8)

# =============================================================================
# Helper Functions
# =============================================================================

def human_delay(min_s=0.5, max_s=1.5):
    """Random delay to appear human."""
    time.sleep(random.uniform(min_s, max_s))

def human_type(element, text):
    """Type text with human-like speed, including occasional micro-pauses."""
    for i, char in enumerate(text):
        element.send_keys(char)
        # Occasionally pause slightly longer mid-word (like a human hesitating)
        if i > 0 and i % random.randint(4, 8) == 0:
            time.sleep(random.uniform(0.15, 0.35))
        else:
            time.sleep(random.uniform(0.04, 0.13))

def get_significant_last_name_words(last_name: str) -> List[str]:
    """
    Extract significant words from a last name for matching.

    HANDLES EDGE CASES:
    1. Hyphenated names - split into separate words ("Smith-Jones" → ["smith", "jones"])
    2. Short surnames - keeps 2+ char words, but filters common prefixes
    3. Suffixes - removes Jr, Sr, II, III, IV, etc.
    4. Common prefixes - ignores "de", "la", "da", "van", "von", etc.

    Examples:
    - "De La Cruz" → ["cruz"]
    - "Smith-Jones" → ["smith", "jones"]
    - "Lee" → ["lee"]
    - "John Smith Jr" → ["john", "smith"] (ignores Jr)
    - "O'Brien" → ["obrien"]
    - "McDonald" → ["mcdonald"]
    """
    if not last_name:
        return []

    # Common prefixes to ignore (these are NOT significant for matching)
    IGNORE_PREFIXES = {
        'de', 'la', 'da', 'van', 'der', 'von', 'del', 'los', 'las',
        'san', 'di', 'du', 'le', 'al', 'el', 'bin', 'ibn', 'mac', 'mc'
    }

    # Suffixes to filter out (typically at the end of a name)
    IGNORE_SUFFIXES = {
        'jr', 'sr', 'ii', 'iii', 'iv', 'v', 'vi',
        'junior', 'senior', 'esq', 'phd', 'md', 'dds'
    }

    # Step 1: Normalize - lowercase, replace hyphens with spaces, remove apostrophes/periods
    normalized = last_name.lower()
    normalized = normalized.replace('-', ' ')  # Split hyphenated names
    normalized = re.sub(r"['\.]", "", normalized)  # Remove apostrophes and periods

    # Step 2: Split into words
    words = normalized.split()

    # Step 3: Filter out suffixes and prefixes
    significant = []
    for word in words:
        # Skip common suffixes
        if word in IGNORE_SUFFIXES:
            continue
        # Skip common prefixes (only if there are other words)
        if word in IGNORE_PREFIXES and len(words) > 1:
            continue
        # Keep words with 2+ characters
        if len(word) >= 2:
            significant.append(word)

    return significant


def last_names_match(input_last_name: str, person_name: str, check_type: str = "exact") -> bool:
    """
    Check if last names match, handling multi-word last names.

    Args:
        input_last_name: The owner's last name from input (e.g., "De La Cruz")
        person_name: The full name or last name to check against
        check_type: "exact" for heir check (person's last name must match)
                   "contains" for relative check (any part can match)

    Returns:
        True if there's a significant match
    """
    if not input_last_name or not person_name:
        return False

    # Get significant words from input owner's last name
    input_words = get_significant_last_name_words(input_last_name)

    if not input_words:
        # If no significant words, fall back to full string match (unusual case)
        return input_last_name.lower() in person_name.lower()

    # For the person, get their last name (last word of full name) or all words
    person_lower = person_name.lower()
    person_words = re.sub(r"['\-.]", "", person_lower).split()

    if check_type == "exact":
        # For heir check: person's LAST word must match one of our significant words
        if not person_words:
            return False
        person_last = person_words[-1]
        return any(word == person_last for word in input_words)
    else:
        # For relative/contains check: any significant word appears anywhere
        return any(word in person_lower for word in input_words)


def normalize_address(address: str) -> str:
    """Normalize address for comparison."""
    if not address:
        return ""

    address = address.lower().strip()

    replacements = {
        "street": "st", "st.": "st", "avenue": "ave", "ave.": "ave",
        "road": "rd", "rd.": "rd", "drive": "dr", "dr.": "dr",
        "boulevard": "blvd", "blvd.": "blvd", "lane": "ln", "ln.": "ln",
        "court": "ct", "ct.": "ct", "place": "pl", "pl.": "pl",
        "highway": "hwy", "hwy.": "hwy",
        "north": "n", "south": "s", "east": "e", "west": "w",
        "northeast": "ne", "northwest": "nw", "southeast": "se", "southwest": "sw",
    }

    for full, abbr in replacements.items():
        address = address.replace(full, abbr)

    # Remove punctuation and extra spaces
    address = re.sub(r'[,.\-]', ' ', address)
    address = ' '.join(address.split())

    return address

def addresses_match(search_street: str, search_state: str, result_address: str) -> bool:
    """Check if result address matches search address."""
    search_norm = normalize_address(search_street)
    state_norm = normalize_address(search_state)
    result_norm = normalize_address(result_address)

    # Check if street number and key parts match
    search_parts = search_norm.split()
    if not search_parts:
        return False

    # Street number must be in result
    if search_parts[0] not in result_norm:
        return False

    # State must be in result
    if state_norm not in result_norm:
        return False

    return True

def parse_date_range(date_str: str) -> Tuple[Optional[datetime], Optional[datetime]]:
    """Parse date range like '01/15/2020 to 12/31/2024'."""
    try:
        if ' to ' in date_str:
            parts = date_str.split(' to ')
            from_date = datetime.strptime(parts[0].strip(), "%m/%d/%Y")
            to_date = datetime.strptime(parts[1].strip(), "%m/%d/%Y")
            return (from_date, to_date)
    except ValueError:
        pass
    return (None, None)

def is_current_resident(to_date: Optional[datetime]) -> bool:
    """Check if to_date is within CURRENT_RESIDENT_DAYS of today."""
    if to_date is None:
        return False
    cutoff = datetime.now() - timedelta(days=CURRENT_RESIDENT_DAYS)
    return to_date >= cutoff

# =============================================================================
# Address Grouping Helper
# =============================================================================

def group_input_by_address(df: pd.DataFrame) -> Dict[str, List[Dict]]:
    """
    Group input rows by unique address.
    Returns dict: { "address_key": [list of owner dicts] }

    Each owner dict contains: DBID, First Name, Last Name
    """
    groups = {}

    for idx, row in df.iterrows():
        # Create unique address key
        street = str(row['Street Address 1']).strip() if pd.notna(row['Street Address 1']) else ""
        city = str(row['City 1']).strip() if pd.notna(row['City 1']) else ""
        state = str(row['State 1']).strip() if pd.notna(row['State 1']) else ""
        zipcode = str(int(row['Zipcode 1'])) if pd.notna(row['Zipcode 1']) else ""

        # If no street address, treat as its own individual row so blank-address rows
        # are never merged together into one giant group
        if not street:
            addr_key = f"__blank__{idx}"
        else:
            addr_key = f"{street}|{city}|{state}|{zipcode}"

        if addr_key not in groups:
            groups[addr_key] = {
                'street': street,
                'city': city,
                'state': state,
                'zipcode': zipcode,
                'owners': []
            }

        # Add this owner to the address group
        groups[addr_key]['owners'].append({
            'dbid': str(row['DBID']).strip() if pd.notna(row.get('DBID')) and str(row.get('DBID', '')).strip() not in ('', 'nan') else '',
            'first_name': str(row['First Name']).strip() if pd.notna(row['First Name']) else "",
            'last_name': str(row['Last Name']).strip() if pd.notna(row['Last Name']) else "",
        })

    return groups


# =============================================================================
# Scraper Class
# =============================================================================

class SkipGenieScraper:
    def __init__(self):
        self.driver = None
        self.output_data: List[Dict] = []
        self.processed_addresses: set = set()  # Tracks unique address keys

    def wait_for_proceed(self, reason: str = "") -> bool:
        """
        Pause and wait for the user to click 'Proceed' in the GUI.
        Prints [WAITING_FOR_PROCEED] so the GUI enables the button.
        Returns True when proceed received, False on timeout (10 min).
        """
        # Clear any stale flag first
        if os.path.exists(PROCEED_FLAG):
            os.remove(PROCEED_FLAG)

        print("\n" + "=" * 60)
        if reason:
            print(f"⏸  {reason}")
        print("⏸  Click  ▶ Proceed  in the SG-BOT window when ready.")
        print("=" * 60)
        print("[WAITING_FOR_PROCEED]")   # GUI watches for this line

        for _ in range(300):             # poll for up to 10 minutes
            if os.path.exists(PROCEED_FLAG):
                os.remove(PROCEED_FLAG)
                print("[PROCEED_RECEIVED]")
                print("✅ Proceeding with search...\n")
                return True
            # Also stop if stop flag dropped while waiting
            if os.path.exists(STOP_FLAG):
                return False
            time.sleep(2)

        print("⏰ Timed out waiting for Proceed (10 min).")
        return False

    def _kill_stale_drivers(self):
        """Kill any leftover chromedriver processes from previous crashed runs."""
        if sys.platform != "win32":
            return
        try:
            killed = 0
            result = subprocess.run(
                ['taskkill', '/F', '/IM', 'undetected_chromedriver.exe', '/T'],
                capture_output=True
            )
            if result.returncode == 0:
                killed += 1
            result2 = subprocess.run(
                ['taskkill', '/F', '/IM', 'chromedriver.exe', '/T'],
                capture_output=True
            )
            if result2.returncode == 0:
                killed += 1
            if killed:
                print("Cleaned up stale driver processes.")
                time.sleep(1)
        except Exception:
            pass

    def setup_driver(self):
        """Initialize undetected Chrome — fresh window every time, cookies handle login."""
        self._kill_stale_drivers()
        print("Launching Chrome...")

        options = uc.ChromeOptions()
        options.add_argument("--start-maximized")
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")
        # Keep Chrome running at full speed even when minimized
        options.add_argument("--disable-background-timer-throttling")
        options.add_argument("--disable-renderer-backgrounding")
        options.add_argument("--disable-backgrounding-occluded-windows")
        options.add_argument("--disable-background-media-suspend")

        chrome_ver = get_chrome_version()
        if chrome_ver:
            print(f"Detected Chrome version: {chrome_ver}")
            self.driver = uc.Chrome(options=options, version_main=chrome_ver)
        else:
            print("Could not detect Chrome version — letting undetected-chromedriver auto-detect.")
            self.driver = uc.Chrome(options=options)
        print("Chrome launched.")
        time.sleep(3)

    def _save_cookies(self, cookies_file: str):
        """Save current browser cookies for next run."""
        import pickle
        try:
            with open(cookies_file, "wb") as f:
                pickle.dump(self.driver.get_cookies(), f)
            print("Session saved — next run will skip login automatically.")
        except Exception:
            pass

    def _is_authenticated(self) -> bool:
        """
        True only when we have positive evidence of an authenticated search page.
        URL alone is not enough because SkipGenie can show /user/search while unauthenticated.
        """
        try:
            # Explicit login route means not authenticated
            if "/user/login" in (self.driver.current_url or ""):
                return False

            # Login form still visible => not authenticated
            if self.driver.find_elements(By.NAME, "email") or self.driver.find_elements(By.NAME, "password"):
                return False

            # SkipGenie sometimes serves /user/search with unauthenticated toasts
            page_lower = (self.driver.page_source or "").lower()
            if "unauthenticated" in page_lower:
                return False

            # Authenticated search view should expose the Street input
            street_inputs = self.driver.find_elements(By.XPATH, "//input[contains(@placeholder, 'Street')]")
            return len(street_inputs) > 0
        except Exception:
            return False

    def login(self):
        """
        Two-path login, both ending at the same Proceed pause:

        PATH A — saved session exists:
          1. Go to login page, inject cookies, go to search URL
          2. If already logged in → show Proceed button → user clicks → done
          3. If session expired → delete stale cookies → fall into Path B

        PATH B — fresh login:
          1. Go to login page, fill email + password
          2. Show Proceed button — bot does nothing else
          3. User solves CAPTCHA, clicks Login, accepts Terms
          4. User clicks Proceed → bot saves cookies → done
        """
        import pickle
        cookies_file = os.path.join(SCRIPT_DIR, "skipgenie_cookies.pkl")

        # ── PATH A: try saved session ──────────────────────────────────────
        if os.path.exists(cookies_file):
            print("Checking saved session...")
            try:
                self.driver.get(LOGIN_URL)          # must be on the domain to inject cookies
                time.sleep(1)
                with open(cookies_file, "rb") as f:
                    for cookie in pickle.load(f):
                        try:
                            self.driver.add_cookie(cookie)
                        except Exception:
                            pass
                self.driver.get(SEARCH_URL)         # if session valid, lands here logged in
                time.sleep(2)
                if self._is_authenticated():
                    print("✅ Already logged in!")
                    if not self.wait_for_proceed(
                        "Chrome is open and logged in. "
                        "Accept any prompts, then click Proceed to start searching."
                    ):
                        return False
                    self._save_cookies(cookies_file)
                    return True
                # Session expired — clear it and drop into Path B
                print("Saved session expired — will log in fresh.")
            except Exception as e:
                print(f"Session restore failed ({type(e).__name__}) — will log in fresh.")
            # Remove stale cookies so next run doesn't hit the same error
            try:
                os.remove(cookies_file)
            except Exception:
                pass
            # If the browser session died, relaunch Chrome cleanly
            try:
                self.driver.get(LOGIN_URL)
                time.sleep(1)
            except Exception:
                try:
                    self.driver.quit()
                except Exception:
                    pass
                self.driver = None
                self.setup_driver()

        # ── PATH B: fresh login ────────────────────────────────────────────
        print("Navigating to login page...")
        try:
            self.driver.get(LOGIN_URL)
            time.sleep(2)
        except Exception as e:
            print(f"Could not open login page: {e}")
            return False

        try:
            email_field = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.NAME, "email"))
            )
            human_type(email_field, SKIPGENIE_EMAIL)
            human_delay(0.5, 1)
            human_type(self.driver.find_element(By.NAME, "password"), SKIPGENIE_PASSWORD)
            print("✅ Credentials entered!")
        except Exception as e:
            print(f"Could not fill login form ({e}) — please fill in manually in Chrome.")

        if not self.wait_for_proceed(
            "Solve the CAPTCHA, click Login, accept any Terms/prompts, "
            "then click Proceed here when you are on the search page."
        ):
            return False

        # User may click Proceed too early. Keep pausing until auth is truly valid.
        while not self._is_authenticated():
            print("⚠️  Still not authenticated yet.")
            if not self.wait_for_proceed(
                "Login is not complete yet. In Chrome: finish login and prompts, "
                "then click Proceed again."
            ):
                return False

        self._save_cookies(cookies_file)
        return True


    def navigate_to_search(self):
        """Navigate to Name Search tab, re-logging in automatically if session expired."""
        print("\nNavigating to Name Search...")
        self.driver.get(SEARCH_URL)
        human_delay(2, 3)

        # Detect session expiry / invalid auth and re-login
        if not self._is_authenticated():
            print("  ⚠️  Session expired mid-run — re-logging in automatically...")
            if not self.login():
                print("  ❌ Re-login failed.")
                return False
            # login() already navigated to search and waited for Proceed — re-navigate cleanly
            self.driver.get(SEARCH_URL)
            human_delay(2, 3)

        # Check for Terms overlay — if present, pause and let the user handle it
        if self.driver.find_elements(By.CSS_SELECTOR, ".skipg_fullPage_overlay"):
            if not self.wait_for_proceed("Terms overlay appeared in Chrome — accept it, then click Proceed."):
                return False

        try:
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.XPATH, "//input[contains(@placeholder, 'Street')]"))
            )
            print("Search form loaded!")
            return True
        except:
            print("Could not load search form.")
            return False

    def fill_search_form(self, street: str, city: str, state: str, zipcode: str) -> bool:
        """Fill the address search form."""
        print(f"  Filling: {street}, {city}, {state} {zipcode}")

        try:
            # Street Address
            street_field = self.driver.find_element(By.XPATH, "//input[contains(@placeholder, 'Street')]")
            human_delay(0.4, 0.9)  # pause before clicking into field
            street_field.clear()
            human_delay(0.3, 0.6)
            human_type(street_field, street)
            human_delay(0.8, 1.5)  # pause after typing, like tabbing to next field

            # City
            city_field = self.driver.find_element(By.XPATH, "//input[contains(@placeholder, 'City')]")
            human_delay(0.3, 0.7)
            city_field.clear()
            human_delay(0.2, 0.4)
            human_type(city_field, city)
            human_delay(0.8, 1.5)

            # State
            state_field = self.driver.find_element(By.XPATH, "//input[contains(@placeholder, 'State')]")
            human_delay(0.3, 0.7)
            state_field.clear()
            human_delay(0.2, 0.4)
            human_type(state_field, state)
            human_delay(0.8, 1.5)

            # Zip
            zip_field = self.driver.find_element(By.XPATH, "//input[contains(@placeholder, 'Zip') or contains(@placeholder, 'Postal')]")
            human_delay(0.3, 0.7)
            zip_field.clear()
            human_delay(0.2, 0.4)
            human_type(zip_field, str(zipcode))
            human_delay(1.0, 2.0)  # pause after last field before finding the button

            return True

        except Exception as e:
            print(f"  Error filling form: {e}")
            return False

    def click_get_info(self) -> bool:
        """Click GET INFO button."""
        try:
            get_info_btn = self.driver.find_element(
                By.XPATH, "//button[contains(text(), 'Get Info') or contains(@class, 'pu_btn_user_search')]"
            )
            # Scroll button into view and pause as if hovering over it
            self.driver.execute_script("arguments[0].scrollIntoView(true);", get_info_btn)
            human_delay(0.5, 1.2)
            get_info_btn.click()
            human_delay(1.5, 3.0)
            return True
        except Exception as e:
            print(f"  Error clicking GET INFO: {e}")
            return False

    def handle_confirmation_popup(self) -> bool:
        """Handle confirmation popup."""
        human_delay(1, 2)

        try:
            buttons = self.driver.find_elements(By.TAG_NAME, "button")
            for btn in buttons:
                if "EXECUTE" in btn.text.upper():
                    self.driver.execute_script("arguments[0].scrollIntoView(true);", btn)
                    human_delay(0.3, 0.5)
                    btn.click()
                    print("  Clicked EXECUTE SEARCH")
                    human_delay(3, 5)
                    return True
            return False
        except Exception as e:
            print(f"  Popup error: {e}")
            return False

    def extract_results(self, address_group: Dict) -> List[Dict]:
        """
        Extract and parse results from the page.

        ENHANCED LOGIC v3.0 - MULTI-OWNER SUPPORT:
        - Takes an address_group with multiple owners
        - Checks each person against ALL input owners
        - Returns PROPERTY row + RESIDENT rows
        - Tracks which input owner(s) matched
        """
        results = []

        # Extract address info from group
        street = address_group['street']
        city = address_group['city']
        state = address_group['state']
        # Strip any trailing .0 that pandas can introduce when reading float zipcodes
        zipcode = str(address_group['zipcode']).split('.')[0]
        owners = address_group['owners']  # List of {dbid, first_name, last_name}

        # Build search address
        search_address = f"{street} {city}, {state} {zipcode}"

        # Combine DBIDs and owner names for output (skip blank/nan DBIDs)
        combined_dbids = ";".join([o['dbid'] for o in owners if o['dbid']])
        combined_owners = "; ".join([f"{o['first_name']} {o['last_name']}" for o in owners])

        # Build list of all owner last names for heir matching
        all_owner_last_names = list(set([o['last_name'].lower() for o in owners if o['last_name']]))

        two_months_ago = datetime.now() - timedelta(days=CURRENT_RESIDENT_DAYS)

        # Track status across all results
        any_owner_found = False
        any_owner_deceased = False
        any_owner_at_address = False
        historical_residents_found = False

        logger.info(f"")
        logger.info(f"  ┌{'─'*70}")
        logger.info(f"  │ SEARCH ADDRESS: {search_address}")
        logger.info(f"  │ INPUT OWNERS ({len(owners)} total):")
        for o in owners:
            logger.info(f"  │   - {o['first_name']} {o['last_name']} (DBID: {o['dbid']})")
        logger.info(f"  │ ALL OWNER LAST NAMES FOR MATCHING: {all_owner_last_names}")
        logger.info(f"  │ CURRENT CUTOFF: {two_months_ago.strftime('%m/%d/%Y')} (anything after this = current)")
        logger.info(f"  └{'─'*70}")

        try:
            # Wait for results - 25s is plenty; results load fast or not at all
            results_found = False
            try:
                WebDriverWait(self.driver, 25).until(
                    EC.presence_of_element_located((By.CLASS_NAME, "skipg_seach_details_box"))
                )
                results_found = True
            except:
                # Timeout - if we're still on the search page, SkipGenie returned no data
                current_url = self.driver.current_url
                logger.info(f"  Timeout waiting for results. URL: {current_url}")

                try:
                    page_text = self.driver.find_element(By.TAG_NAME, "body").text.lower()
                    if any(phrase in page_text for phrase in ["no matches", "no results", "0 results", "no records"]):
                        logger.info(f"  'No matches' message detected")
                        return self._no_match_record(address_group, property_status="No Results")
                except Exception:
                    pass

                # If still on search page after timeout → no results (not an error worth retrying)
                if "/user/search" in current_url:
                    logger.info(f"  Still on search page - treating as No Results")
                    return self._no_match_record(address_group, property_status="No Results")

                # Otherwise it's a real error
                raise Exception(f"Timeout and unexpected URL: {current_url}")

            # Pause after results appear - like a human taking a moment to look at the page
            human_delay(1.5, 3.5)

            # Try primary class name first
            result_boxes = self.driver.find_elements(By.CLASS_NAME, "skipg_seach_details_box")

            # If not found, try alternative selectors
            if not result_boxes:
                logger.info(f"  No results with 'skipg_seach_details_box' class, trying alternatives...")
                result_boxes = self.driver.find_elements(By.CLASS_NAME, "skipg_search_details_box")  # Fixed spelling

            if not result_boxes:
                # Try finding any div that looks like a result box
                result_boxes = self.driver.find_elements(By.XPATH, "//div[contains(@class, 'skipg') and contains(@class, 'details')]")

            logger.info(f"  Found {len(result_boxes)} people in results")

            if not result_boxes:
                logger.info(f"  → NO RESULTS RETURNED FROM SKIPGENIE")
                return self._no_match_record(address_group, property_status="No Results")

            people_at_address = []
            max_results = min(len(result_boxes), MAX_PEOPLE_PER_ADDRESS)

            for idx, box in enumerate(result_boxes[:max_results]):
                # Small pause between reading each person result (like scanning down the page)
                if idx > 0:
                    human_delay(0.4, 1.0)
                try:
                    logger.info(f"")
                    logger.info(f"  ╔{'═'*70}")
                    logger.info(f"  ║ PERSON {idx+1} OF {max_results}")
                    logger.info(f"  ╠{'═'*70}")

                    # ===== PARSE HEADER (name, age, deceased) =====
                    header = box.find_element(By.CLASS_NAME, "skipg_seach_details_highlight").find_element(By.TAG_NAME, "h6")
                    header_html = header.get_attribute("innerHTML")

                    # Use [^<]+ so the name capture never bleeds across HTML tag boundaries
                    # (deceased names have an extra <span class="text-danger"> between name and "at AGE")
                    name_match = re.search(r'<span class="text-success">([^<]+)</span>', header_html)
                    age_match  = re.search(r'\bat\s+(\d+)\s+-', header_html)
                    if name_match:
                        name = name_match.group(1).strip()
                        age  = age_match.group(1) if age_match else "NA"
                    else:
                        name = "Unknown"
                        age  = "NA"

                    deceased = "Yes" if '<span class="text-danger">DECEASED</span>' in header_html else "No"

                    deceased_tag = " [DECEASED]" if deceased == "Yes" else ""
                    print(f"    [{idx+1}/{max_results}] {name}, {age}{deceased_tag}")

                    logger.info(f"  ║ NAME: {name}")
                    logger.info(f"  ║ AGE: {age}")
                    logger.info(f"  ║ DECEASED: {deceased}")

                    # ===== CHECK IF THIS PERSON IS ANY OF THE INPUT OWNERS =====
                    person_name_lower = name.lower() if name else ""
                    matched_owner = None  # Will store which owner matched, if any
                    is_input_owner = False

                    # Check against ALL input owners
                    for owner in owners:
                        owner_first = owner['first_name'].lower()
                        owner_last = owner['last_name'].lower()

                        if owner_first and owner_last:
                            name_parts = person_name_lower.split()
                            if len(name_parts) >= 2:
                                person_first = name_parts[0]
                                person_last = name_parts[-1]

                                # Match if first name starts with owner first name or vice versa
                                first_match = (owner_first in person_first or
                                              person_first in owner_first or
                                              (len(person_first) >= 3 and len(owner_first) >= 3 and
                                               owner_first[:3] == person_first[:3]))
                                last_match = owner_last == person_last

                                if first_match and last_match:
                                    is_input_owner = True
                                    matched_owner = f"{owner['first_name']} {owner['last_name']}"
                                    break

                    if is_input_owner:
                        any_owner_found = True
                        if deceased == "Yes":
                            any_owner_deceased = True
                        logger.info(f"  ║ ⭐ MATCHES INPUT OWNER: {matched_owner}! (Deceased: {deceased})")

                    # ===== PARSE ALL ADDRESSES (single JS call - no extra network requests) =====
                    address_history = []
                    try:
                        raw_pairs = self.driver.execute_script("""
                            var box = arguments[0];
                            var links = box.querySelectorAll('.skipg_seach_link_highlight');
                            var results = [];
                            var seen = {};
                            links.forEach(function(link) {
                                var addr = (link.textContent || '').trim();
                                if (!addr || addr.length < 10) return;
                                if (!/[0-9]/.test(addr)) return;
                                if (/^[(][0-9]{3}[)][ ]*[0-9]{3}-[0-9]{4}$/.test(addr)) return;
                                var timeText = null;
                                var el = link.nextElementSibling;
                                for (var i = 0; i < 4 && el && !timeText; i++) {
                                    if (el.tagName === 'P' && el.textContent.indexOf(' to ') > -1) {
                                        timeText = el.textContent.trim();
                                    } else {
                                        var p = el.querySelector('p');
                                        if (p && p.textContent.indexOf(' to ') > -1) {
                                            timeText = p.textContent.trim();
                                        }
                                    }
                                    el = el.nextElementSibling;
                                }
                                if (!timeText) {
                                    var parent = link.parentElement;
                                    for (var lvl = 0; lvl < 3 && parent && !timeText; lvl++) {
                                        var p = parent.querySelector('p');
                                        if (p && p.textContent.indexOf(' to ') > -1) {
                                            timeText = p.textContent.trim();
                                        }
                                        parent = parent.parentElement;
                                    }
                                }
                                var dateMatch = timeText && timeText.match(/[0-9]{2}[/][0-9]{2}[/][0-9]{4} to [0-9]{2}[/][0-9]{2}[/][0-9]{4}/);
                                if (dateMatch) {
                                    var key = addr + '|' + dateMatch[0];
                                    if (!seen[key]) {
                                        seen[key] = true;
                                        results.push([addr, dateMatch[0]]);
                                    }
                                }
                            });
                            return results;
                        """, box)

                        for addr, time_text in (raw_pairs or []):
                            address_history.append((addr.strip(), time_text.strip()))
                            logger.debug(f"  Parsed: {addr} | {time_text}")

                        logger.debug(f"  JS extracted {len(address_history)} address+date pairs")

                    except Exception as e:
                        logger.error(f"  ║ Error getting address history: {e}")

                    # ===== LOG ALL ADDRESSES WITH ANALYSIS =====
                    logger.info(f"  ║")
                    logger.info(f"  ║ ADDRESS HISTORY ({len(address_history)} addresses):")
                    logger.info(f"  ║ {'─'*66}")

                    matched_address = None
                    time_at_address = "NA"
                    is_current_at_search = False
                    other_current_addresses = []

                    for addr_idx, (addr, time_text) in enumerate(address_history):
                        # Parse the to-date
                        to_date = None
                        is_current = False
                        if " to " in time_text:
                            try:
                                to_date_str = time_text.split(" to ")[1]
                                to_date = datetime.strptime(to_date_str, "%m/%d/%Y")
                                is_current = to_date >= two_months_ago
                            except:
                                pass

                        # Check if matches search address
                        matches_search = self.addresses_match(search_address, addr)

                        # Build status indicators
                        status = []
                        if is_current:
                            status.append("CURRENT")
                        else:
                            status.append("OLD")
                        if matches_search:
                            status.append("MATCHES SEARCH")

                        status_str = f"[{', '.join(status)}]"

                        logger.info(f"  ║   {addr_idx+1}. {addr}")
                        logger.info(f"  ║      Time: {time_text}")
                        logger.info(f"  ║      Status: {status_str}")

                        # Track for logic
                        if matches_search and is_current:
                            is_current_at_search = True
                            matched_address = addr
                            time_at_address = time_text
                        elif is_current and not matches_search:
                            other_current_addresses.append(addr)

                    # ===== SUMMARY FOR THIS PERSON =====
                    logger.info(f"  ║")
                    logger.info(f"  ║ ANALYSIS SUMMARY:")
                    logger.info(f"  ║ {'─'*66}")
                    logger.info(f"  ║   Current at search address?: {is_current_at_search}")
                    if is_current_at_search:
                        logger.info(f"  ║   Matched address: {matched_address}")
                        logger.info(f"  ║   Time at address: {time_at_address}")
                    logger.info(f"  ║   Other current addresses: {len(other_current_addresses)}")
                    for oca in other_current_addresses:
                        logger.info(f"  ║     - {oca}")

                    has_overlap = len(other_current_addresses) > 0
                    logger.info(f"  ║   HAS ADDRESS OVERLAP (possibly moved)?: {has_overlap}")

                    # ===== CHECK HEIR/RELATIVE STATUS =====
                    if is_current_at_search:
                        # Check against ALL owner last names for heir status
                        is_heir = False
                        heir_match_owner = None
                        is_relative = False
                        relative_match_owner = None

                        # Track if input owner is at this address
                        if is_input_owner:
                            any_owner_at_address = True

                        # Get person's last word for logging
                        person_name_parts = name.lower().split() if name and name != "Unknown" else []
                        person_last_word = person_name_parts[-1] if person_name_parts else ""

                        logger.info(f"  ║")
                        logger.info(f"  ║ HEIR CHECK (checking against ALL {len(owners)} owners):")

                        # Check each owner's last name for heir match
                        for owner in owners:
                            owner_last = owner['last_name']
                            significant_words = get_significant_last_name_words(owner_last)
                            matches = last_names_match(owner_last, name, check_type="exact")
                            logger.info(f"  ║   vs '{owner['first_name']} {owner['last_name']}': words={significant_words}, match={matches}")
                            if matches and not is_heir:
                                is_heir = True
                                heir_match_owner = f"{owner['first_name']} {owner['last_name']}"

                        logger.info(f"  ║   Person's last word: '{person_last_word}'")
                        logger.info(f"  ║   Is input owner?: {is_input_owner} {f'(matched: {matched_owner})' if matched_owner else ''}")
                        logger.info(f"  ║   Is heir?: {is_heir} {f'(matches: {heir_match_owner})' if heir_match_owner else ''}")

                        # Check relatives if not direct heir and not the owner
                        if not is_heir and not is_input_owner:
                            try:
                                relatives = box.find_elements(By.XPATH, ".//h5[text()='Possible Relatives']/following-sibling::h6")
                                logger.info(f"  ║")
                                logger.info(f"  ║ RELATIVE CHECK ({len(relatives)} relatives, checking vs ALL owners):")
                                for rel in relatives:
                                    rel_name = rel.text.strip()
                                    # Check against ALL owner last names
                                    for owner in owners:
                                        owner_last = owner['last_name']
                                        rel_matches = last_names_match(owner_last, rel_name, check_type="contains")
                                        if rel_matches and not is_relative:
                                            is_relative = True
                                            relative_match_owner = f"{owner['first_name']} {owner['last_name']}"
                                            logger.info(f"  ║   - {rel_name}: ✓ matches owner '{relative_match_owner}'")
                                            break
                                    if not is_relative:
                                        logger.info(f"  ║   - {rel_name}: no match")
                            except Exception as rel_err:
                                logger.debug(f"  ║ Error checking relatives: {rel_err}")

                        # ===== DETERMINE RESIDENT STATUS =====
                        if is_input_owner:
                            resident_status = f"Input Owner ({matched_owner})"
                        elif is_heir:
                            resident_status = f"Heir (matches {heir_match_owner})"
                        elif is_relative:
                            resident_status = f"Possible Relative (of {relative_match_owner})"
                        else:
                            resident_status = "Non-Heir"

                        # ===== FINAL DECISION FOR THIS PERSON =====
                        logger.info(f"  ║")
                        logger.info(f"  ╠{'═'*70}")
                        logger.info(f"  ║ DECISION: ADDING TO RESULTS")
                        logger.info(f"  ║   Name: {name}, Age: {age}, Deceased: {deceased}")
                        logger.info(f"  ║   Resident Status: {resident_status}")
                        logger.info(f"  ║   Has Overlap: {has_overlap}")
                        logger.info(f"  ╚{'═'*70}")

                        people_at_address.append({
                            'name': name,
                            'age': age,
                            'deceased': deceased,
                            'current_address': matched_address,
                            'time_at_address': time_at_address,
                            'is_input_owner': is_input_owner,
                            'matched_owner': matched_owner,
                            'is_heir': is_heir,
                            'heir_match_owner': heir_match_owner,
                            'is_relative': is_relative,
                            'relative_match_owner': relative_match_owner,
                            'resident_status': resident_status,
                            'has_overlap': has_overlap,
                        })
                    else:
                        # Track that we found historical residents (not current)
                        # Check if any address matched the search address (even if old)
                        for addr, time_text in address_history:
                            if self.addresses_match(search_address, addr):
                                historical_residents_found = True
                                break

                        logger.info(f"  ║")
                        logger.info(f"  ╠{'═'*70}")
                        logger.info(f"  ║ DECISION: NOT ADDING (not current at search address)")
                        logger.info(f"  ║   Historical match found?: {historical_residents_found}")
                        logger.info(f"  ╚{'═'*70}")

                except Exception as e:
                    logger.error(f"  Error parsing person {idx + 1}: {e}")
                    import traceback
                    traceback.print_exc()
                    continue

            # ===== FINAL OCCUPANCY STATUS =====
            logger.info(f"")
            logger.info(f"  ┌{'─'*70}")
            logger.info(f"  │ FINAL OCCUPANCY DETERMINATION")
            logger.info(f"  │ Total people found at search address: {len(people_at_address)}")
            logger.info(f"  │ Any Owner Found: {any_owner_found}")
            logger.info(f"  │ Any Owner Deceased: {any_owner_deceased}")
            logger.info(f"  │ Any Owner at Address: {any_owner_at_address}")
            logger.info(f"  │ Historical Residents Found: {historical_residents_found}")

            # Determine owner status strings for output
            if any_owner_found:
                owner_found_str = "Yes - Deceased" if any_owner_deceased else "Yes - Living"
            else:
                owner_found_str = "No"
            owner_deceased_str = "Yes" if any_owner_deceased else ("No" if any_owner_found else "Unknown")

            property_status = self.determine_occupancy_status(
                people_at_address,
                owner_found=any_owner_found,
                owner_deceased=any_owner_deceased,
                owner_at_address=any_owner_at_address,
                historical_residents_found=historical_residents_found
            )

            logger.info(f"  │ FINAL PROPERTY STATUS: {property_status}")
            logger.info(f"  └{'─'*70}")

            print(f"  Property status: {property_status} ({len(people_at_address)} residents)")

            # ===== BUILD OUTPUT RECORDS (NEW HIERARCHICAL STRUCTURE) =====

            # 1. PROPERTY ROW (always first)
            results.append({
                'Row Type': 'PROPERTY',
                'DBID': combined_dbids,
                'Input Owners': combined_owners,
                'Input Address': street,
                'Input City': city,
                'Input State': state,
                'Input Zipcode': zipcode,
                'Property Status': property_status,
                'Owner Found': owner_found_str,
                'Owner Deceased': owner_deceased_str,
                # Resident-specific fields blank for property row
                'Name': '',
                'Age': '',
                'Deceased': '',
                'Current Address': '',
                'Time at Address': '',
                'Resident Status': '',
                'Has Overlap': '',
            })

            # 2. RESIDENT ROWS (one per person found)
            if people_at_address:
                for person in people_at_address:
                    results.append({
                        'Row Type': 'RESIDENT',
                        'DBID': '',  # Blank for resident rows
                        'Input Owners': '',
                        'Input Address': '',
                        'Input City': '',
                        'Input State': '',
                        'Input Zipcode': '',
                        'Property Status': '',  # Blank for resident rows
                        'Owner Found': '',
                        'Owner Deceased': '',
                        # Resident-specific fields
                        'Name': person['name'],
                        'Age': person['age'],
                        'Deceased': person['deceased'],
                        'Current Address': person['current_address'],
                        'Time at Address': person['time_at_address'],
                        'Resident Status': person['resident_status'],
                        'Has Overlap': 'Yes' if person.get('has_overlap') else 'No',
                    })
            else:
                # No residents - add info row explaining why
                if historical_residents_found:
                    results[-1]['Property Status'] = "Vacant Building"
                else:
                    results[-1]['Property Status'] = "No Results"

            return results

        except Exception as e:
            logger.error(f"  Error extracting results: {e}")
            import traceback
            traceback.print_exc()
            return self._no_match_record(address_group, property_status="Error")

    def _no_match_record(self, address_group: Dict, property_status: str = 'Unknown',
                          owner_found: str = 'No', owner_deceased: str = 'NA') -> List[Dict]:
        """Create a PROPERTY row for no-match or error cases."""
        combined_dbids = ";".join([o['dbid'] for o in address_group['owners'] if o['dbid']])
        combined_owners = "; ".join([f"{o['first_name']} {o['last_name']}" for o in address_group['owners']])

        return [{
            'Row Type': 'PROPERTY',
            'DBID': combined_dbids,
            'Input Owners': combined_owners,
            'Input Address': address_group['street'],
            'Input City': address_group['city'],
            'Input State': address_group['state'],
            'Input Zipcode': str(address_group['zipcode']).split('.')[0],
            'Property Status': property_status,
            'Owner Found': owner_found,
            'Owner Deceased': owner_deceased,
            'Name': '',
            'Age': '',
            'Deceased': '',
            'Current Address': '',
            'Time at Address': '',
            'Resident Status': '',
            'Has Overlap': '',
        }]

    def addresses_match(self, search_address: str, result_address: str) -> bool:
        """
        Check if addresses match - uses same logic as old script.
        Checks street number, state, and key street name parts.
        """
        search_norm = normalize_address(search_address)
        result_norm = normalize_address(result_address)

        logger.debug(f"    ADDRESS MATCH CHECK:")
        logger.debug(f"      Search (norm): '{search_norm}'")
        logger.debug(f"      Result (norm): '{result_norm}'")

        search_parts = search_norm.split()
        result_parts = result_norm.split()

        if len(search_parts) < 3 or len(result_parts) < 3:
            logger.debug(f"      FAIL: Not enough parts (search={len(search_parts)}, result={len(result_parts)})")
            return False

        # Find zip codes
        search_zip = None
        result_zip = None
        for part in search_parts:
            if part.isdigit() and len(part) == 5:
                search_zip = part
                break
        for part in result_parts:
            if part.isdigit() and len(part) == 5:
                result_zip = part
                break

        logger.debug(f"      Zip: search={search_zip}, result={result_zip}")

        # Zip codes must match if both exist
        if search_zip and result_zip and search_zip != result_zip:
            logger.debug(f"      FAIL: Zip mismatch ({search_zip} != {result_zip})")
            return False

        # Find street numbers
        search_num = None
        result_num = None
        for part in search_parts:
            if part.isdigit() and len(part) <= 5:
                search_num = part
                break
        for part in result_parts:
            if part.isdigit() and len(part) <= 5:
                result_num = part
                break

        logger.debug(f"      Street#: search={search_num}, result={result_num}")

        # Street numbers must match
        if search_num and result_num and search_num != result_num:
            logger.debug(f"      FAIL: Street number mismatch ({search_num} != {result_num})")
            return False

        # Check state codes
        search_state = None
        result_state = None
        if search_zip:
            zip_idx = search_parts.index(search_zip)
            if zip_idx > 0 and len(search_parts[zip_idx-1]) == 2:
                search_state = search_parts[zip_idx-1]
        if result_zip:
            zip_idx = result_parts.index(result_zip)
            if zip_idx > 0 and len(result_parts[zip_idx-1]) == 2:
                result_state = result_parts[zip_idx-1]

        logger.debug(f"      State: search={search_state}, result={result_state}")

        if search_state and result_state and search_state != result_state:
            logger.debug(f"      FAIL: State mismatch ({search_state} != {result_state})")
            return False

        # Check key street parts are present
        search_remaining = [p for p in search_parts if p not in [search_num, search_zip, search_state]]
        result_remaining = [p for p in result_parts if p not in [result_num, result_zip, result_state]]

        search_key = search_remaining[:3]
        logger.debug(f"      Key parts to find: {search_key}")
        logger.debug(f"      In result parts: {result_remaining}")

        matches = all(any(part in rp or rp in part for rp in result_remaining) for part in search_key)
        if matches:
            logger.debug(f"      ✓ MATCH SUCCESS")
        else:
            logger.debug(f"      FAIL: Key parts not found in result")

        return matches

    def determine_occupancy_status(self, people: List[Dict],
                                     owner_found: bool = False,
                                     owner_deceased: bool = False,
                                     owner_at_address: bool = False,
                                     historical_residents_found: bool = False) -> str:
        """
        Determine occupancy status based on found people.

        ENHANCED PRIORITY ORDER (v2.0):
        1. Owner-Occupied - Input owner is living at the address
        2. Vacant Estate - Input owner is deceased, no one else living there
        3. Heir-Occupied - Owner deceased/not found, heir (same last name) living there
        4. Relative-Occupied - Relative with matching last name living there
        5. Non-Heir-Occupied - Living residents but no family connection
        6. Possibly Vacant - Address Overlap - All living have another current address
        7. Vacant - No living current residents (different from historical)
        """
        logger.info(f"  │")
        logger.info(f"  │ OCCUPANCY LOGIC (v2.0 Enhanced):")
        logger.info(f"  │   Total people at address: {len(people)}")
        logger.info(f"  │   Owner found in results: {owner_found}")
        logger.info(f"  │   Owner deceased: {owner_deceased}")
        logger.info(f"  │   Owner currently at address: {owner_at_address}")

        # List all people with enhanced info
        for p in people:
            logger.info(f"  │     - {p['name']} (deceased: {p['deceased']}, is_owner: {p.get('is_input_owner')}, heir: {p.get('is_heir')}, relative: {p.get('is_relative')}, overlap: {p.get('has_overlap')})")

        # Filter out deceased
        living = [p for p in people if p['deceased'] != 'Yes']
        deceased_people = [p for p in people if p['deceased'] == 'Yes']

        logger.info(f"  │")
        logger.info(f"  │   Living: {len(living)}, Deceased: {len(deceased_people)}")

        # ===== CHECK 1: Owner-Occupied =====
        living_owners = [p for p in living if p.get('is_input_owner', False)]
        if living_owners:
            logger.info(f"  │")
            logger.info(f"  │   → OWNER-OCCUPIED (input owner is living at address)")
            return 'Owner-Occupied'

        # ===== CHECK 2: Vacant Estate =====
        if owner_deceased and not living:
            logger.info(f"  │")
            logger.info(f"  │   → VACANT BUILDING (owner deceased, no living residents)")
            return 'Vacant Building'

        # ===== CHECK 3: No living residents =====
        if not living:
            logger.info(f"  │")
            logger.info(f"  │   → VACANT BUILDING (no living current residents)")
            return 'Vacant Building'

        # ===== CHECK 4: Address Overlap (now per-person, only if ALL have overlap) =====
        overlap_status = [(p['name'], p.get('has_overlap', False)) for p in living]
        all_overlap = all(p.get('has_overlap', False) for p in living)
        some_overlap = any(p.get('has_overlap', False) for p in living)

        logger.info(f"  │")
        logger.info(f"  │   OVERLAP CHECK:")
        for name, has_overlap in overlap_status:
            logger.info(f"  │     - {name}: has_overlap = {has_overlap}")
        logger.info(f"  │   All have overlap?: {all_overlap}, Some have overlap?: {some_overlap}")

        # Only mark as possibly vacant if ALL living residents have overlap
        # This prevents false positives when some residents clearly live there
        if all_overlap:
            logger.info(f"  │")
            logger.info(f"  │   → POSSIBLY VACANT - ADDRESS OVERLAP (all residents may have moved)")
            return 'Possibly Vacant - Address Overlap'

        # ===== CHECK 5: Heir-Occupied (includes case where owner deceased) =====
        heirs = [p for p in living if p.get('is_heir', False) and not p.get('is_input_owner', False)]
        logger.info(f"  │")
        logger.info(f"  │   HEIR CHECK: {len(heirs)} heirs found")
        for h in heirs:
            logger.info(f"  │     - {h['name']} is an heir (same last name)")

        if heirs:
            # If owner is deceased and heir is living there, it's an estate situation
            if owner_deceased:
                logger.info(f"  │")
                logger.info(f"  │   → ESTATE - HEIR OCCUPIED (owner deceased, heir living there)")
                return 'Estate - Heir Occupied'
            else:
                logger.info(f"  │")
                logger.info(f"  │   → HEIR-OCCUPIED")
                return 'Heir-Occupied'

        # ===== CHECK 6: Non-Heir with Possible Relatives =====
        # Check if any living resident has a relative with owner's last name
        # This is different from direct heir - they don't share the name but might be connected
        relatives = [p for p in living if p.get('is_relative', False)]
        logger.info(f"  │")
        logger.info(f"  │   POSSIBLE RELATIVES CHECK: {len(relatives)} residents have relatives matching owner's last name")
        for r in relatives:
            logger.info(f"  │     - {r['name']} has a relative with last name matching input owner")

        if relatives:
            logger.info(f"  │")
            logger.info(f"  │   → OCCUPIED (POSSIBLE RELATIVE)")
            logger.info(f"  │     (Resident doesn't share last name, but has a relative who does)")
            return 'Occupied (Possible Relative)'

        # ===== DEFAULT: Non-Heir-Occupied (no connection at all) =====
        logger.info(f"  │")
        logger.info(f"  │   → OCCUPIED (NON-HEIR) (no family connection found)")
        return 'Occupied (Non-Heir)'

    def load_input_data(self) -> pd.DataFrame:
        """Load and validate input CSV."""
        if not os.path.exists(INPUT_FILE):
            raise FileNotFoundError(
                f"Input file not found: {INPUT_FILE}\n"
                "Add whos_input.csv to the skipgenie folder and try again."
            )

        df = pd.read_csv(INPUT_FILE, encoding='latin-1')

        # Validate required columns
        required = ['First Name', 'Last Name', 'Street Address 1', 'City 1', 'State 1', 'Zipcode 1']
        missing = [c for c in required if c not in df.columns]
        if missing:
            raise ValueError(
                f"whos_input.csv is missing required columns: {missing}\n"
                f"Columns found: {list(df.columns)}"
            )

        if len(df) == 0:
            raise ValueError("whos_input.csv is empty — add addresses and try again.")

        print(f"Loaded {len(df)} addresses from input file")
        return df

    def load_existing_output(self):
        """Load existing output for resume capability."""
        if os.path.exists(OUTPUT_FILE):
            df = pd.read_csv(OUTPUT_FILE, encoding='latin-1')
            self.output_data = df.to_dict('records')

            # Track processed addresses (only from PROPERTY rows)
            property_count = 0
            for record in self.output_data:
                if record.get('Row Type') == 'PROPERTY':
                    # Build address key from property row
                    # Handle zipcode as int to match input format (avoid 28803.0 vs 28803)
                    zipcode = record.get('Input Zipcode', '')
                    if pd.notna(zipcode):
                        try:
                            zipcode = str(int(float(zipcode)))
                        except (ValueError, TypeError):
                            zipcode = str(zipcode)
                    else:
                        zipcode = ''

                    addr_key = f"{record['Input Address']}|{record['Input City']}|{record['Input State']}|{zipcode}"
                    self.processed_addresses.add(addr_key)
                    property_count += 1

            print(f"Loaded {len(self.output_data)} existing records ({property_count} properties)")

    def save_output(self):
        """Save output to CSV with hierarchical PROPERTY/RESIDENT structure."""
        if not self.output_data:
            return

        df = pd.DataFrame(self.output_data)
        columns = [
            'Row Type',  # PROPERTY or RESIDENT
            'DBID',      # Combined DBIDs for property
            'Input Owners',  # All owners for this address
            'Input Address', 'Input City', 'Input State', 'Input Zipcode',
            'Property Status',  # Overall status (on PROPERTY row)
            'Owner Found', 'Owner Deceased',
            # Resident-specific columns
            'Name', 'Age', 'Deceased', 'Current Address',
            'Time at Address', 'Resident Status', 'Has Overlap'
        ]

        for col in columns:
            if col not in df.columns:
                df[col] = ''

        df = df[columns]
        df.to_csv(OUTPUT_FILE, index=False)

        # Count properties vs residents
        property_count = len(df[df['Row Type'] == 'PROPERTY'])
        resident_count = len(df[df['Row Type'] == 'RESIDENT'])
        print(f"Saved {property_count} properties, {resident_count} residents")

    def process_address_group(self, address_group: Dict) -> bool:
        """Process a single address group (may have multiple owners)."""
        street = address_group['street']
        city = address_group['city']
        state = address_group['state']
        zipcode = address_group['zipcode']
        owners = address_group['owners']

        print(f"  Owners: {', '.join([o['first_name'] + ' ' + o['last_name'] for o in owners])}")

        # Fill form
        if not self.fill_search_form(street, city, state, zipcode):
            return False

        # Click GET INFO
        if not self.click_get_info():
            return False

        # Handle popup
        self.handle_confirmation_popup()

        # Extract results (passing the full address group with all owners)
        results = self.extract_results(address_group)

        # Add to output
        for record in results:
            self.output_data.append(record)

        # Count property vs resident rows
        property_rows = len([r for r in results if r.get('Row Type') == 'PROPERTY'])
        resident_rows = len([r for r in results if r.get('Row Type') == 'RESIDENT'])
        print(f"  → {property_rows} property, {resident_rows} residents")
        return True

    def run(self):
        """Main run function."""
        print("\n  SkipGenie Bot starting...")
        print(f"  Login: {SKIPGENIE_EMAIL}\n")
        print("""
╔═══════════════════════════════════════════════════════════════╗
║     SkipGenie Full Scraper v3.0 - Address Grouping            ║
╠═══════════════════════════════════════════════════════════════╣
║  Groups addresses - searches each unique address ONCE         ║
║  Hierarchical output (PROPERTY + RESIDENT rows)               ║
║  Sleep prevention keeps system awake                         ║
║  Close this window or Ctrl+C to stop (progress saved)         ║
╚═══════════════════════════════════════════════════════════════╝
""")
        start_caffeinate()

        try:
            # Backup existing output before touching it
            if os.path.exists(OUTPUT_FILE):
                import shutil
                backup = OUTPUT_FILE.replace('.csv', '_backup.csv')
                shutil.copy2(OUTPUT_FILE, backup)
                print(f"Output backed up → {os.path.basename(backup)}")

            # Load data
            input_df = self.load_input_data()
            self.load_existing_output()

            # Group input by unique address
            address_groups = group_input_by_address(input_df)

            print(f"\nInput rows: {len(input_df)} | Unique addresses: {len(address_groups)}")
            print(f"Already processed: {len(self.processed_addresses)}")

            # Filter to only unprocessed addresses
            remaining_groups = {}
            for addr_key, group in address_groups.items():
                if addr_key not in self.processed_addresses:
                    remaining_groups[addr_key] = group

            print(f"Remaining to process: {len(remaining_groups)}")

            if len(remaining_groups) == 0:
                print("All addresses already processed!")
                return

            # Setup driver
            self.setup_driver()

            # Login
            if not self.login():
                if os.path.exists(STOP_FLAG):
                    os.remove(STOP_FLAG)
                    print("\n🛑 Stopped during login — no data to save.")
                else:
                    print("\n❌ Login failed or timed out.")
                    print("   Run the bot again and solve the CAPTCHA in the Chrome window when prompted.")
                raise SystemExit(1)

            # Navigate to search
            if not self.navigate_to_search():
                return

            # Process address groups
            records_since_save = 0
            total_groups = len(remaining_groups)
            stopped_early = False

            for idx, (addr_key, group) in enumerate(remaining_groups.items()):
                print(f"\n[{idx + 1}/{total_groups}] {group['street']}, {group['city']}, {group['state']} {group['zipcode']}")

                logger.info(f"\n{'='*70}")
                logger.info(f"[{idx + 1}/{total_groups}] PROCESSING: {group['street']}, {group['city']}, {group['state']} {group['zipcode']}")
                logger.info(f"Owners ({len(group['owners'])}): {', '.join([o['first_name'] + ' ' + o['last_name'] for o in group['owners']])}")
                logger.info(f"{'='*70}")

                # Hard guard: never attempt a search while unauthenticated.
                if not self._is_authenticated():
                    print("⚠️  Authentication lost before search — re-authenticating...")
                    if not self.login():
                        print("❌ Re-authentication failed — stopping run and saving progress.")
                        self.save_output()
                        break
                    if not self.navigate_to_search():
                        print("❌ Could not return to search after re-auth — stopping run and saving progress.")
                        self.save_output()
                        break

                # Try with retry
                success = False
                abort_run = False
                for attempt in range(RETRY_ATTEMPTS + 1):
                    # Bail out of retries immediately if stop was requested
                    if os.path.exists(STOP_FLAG):
                        break
                    try:
                        if self.process_address_group(group):
                            success = True
                            break
                    except Exception as e:
                        print(f"  Attempt {attempt + 1} failed: {e}")
                        if attempt < RETRY_ATTEMPTS:
                            human_delay(2, 3)
                            if not self.navigate_to_search():
                                abort_run = True
                                break

                if abort_run:
                    print("\n❌ Could not recover navigation/auth state — stopping run and saving progress.")
                    self.save_output()
                    break

                if not success:
                    # Add error record
                    error_record = self._no_match_record(group, property_status="Error")[0]
                    self.output_data.append(error_record)

                # Mark processed
                self.processed_addresses.add(addr_key)
                records_since_save += 1

                # Save periodically
                if records_since_save >= SAVE_EVERY_N_RECORDS:
                    self.save_output()
                    records_since_save = 0

                # Check for graceful stop request from GUI
                if os.path.exists(STOP_FLAG):
                    os.remove(STOP_FLAG)
                    stopped_early = True
                    print("\n🛑 Stop requested — finished current address. Saving and closing...")
                    break

                # Navigate back for next search — stop the run if navigation fails
                if not self.navigate_to_search():
                    print("\n❌ Could not return to search page — stopping run and saving progress.")
                    self.save_output()
                    break

                # Human delay between searches - occasionally take a longer "thinking" break
                if random.random() < 0.12:
                    idle = random.uniform(8, 18)
                    logger.debug(f"  Taking a longer break: {idle:.1f}s")
                    time.sleep(idle)
                else:
                    time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))

            # Final save
            self.save_output()
            if stopped_early:
                print("\n🛑 Stopped. Progress saved.")
            else:
                print("\n✅ All addresses processed!")

        except KeyboardInterrupt:
            print("\n\nInterrupted! Saving progress...")
            self.save_output()
        except Exception as e:
            print(f"\nError: {e}")
            import traceback
            traceback.print_exc()
            self.save_output()

        finally:
            stop_caffeinate()

            if self.driver:
                print("\nClosing browser...")
                self.driver.quit()


if __name__ == "__main__":
    scraper = SkipGenieScraper()
    scraper.run()
