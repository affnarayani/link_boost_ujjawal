import os
import sys
import json
import time
import random
import base64
import re  # Hidden characters aur special verified string patterns clean karne ke liye
from pathlib import Path
from typing import List, Dict, Any

from dotenv import load_dotenv

from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth


# =========================
# CONFIG
# =========================
HEADLESS = True
TARGET_URL = "https://www.linkedin.com/search/results/people/?keywords=advocate&origin=FACETED_SEARCH&geoUrn=%5B%22113536609%22%5D"

LINKEDIN_COOKIES_FILE = "linkedin_cookies.json.encrypted"
OUTPUT_FILE = "scraped_connections.json"

PBKDF2_ITERATIONS = 200_000

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"


# =========================
# DYNAMIC WAITS
# =========================
def custom_random_wait(min_sec=15, max_sec=30):
    seconds = random.uniform(min_sec, max_sec)
    print(f"[WAIT] Sleeping for {seconds:.2f} seconds...", flush=True)
    time.sleep(seconds)


# =========================
# CRYPTO (COOKIES DECRYPTION)
# =========================
def _derive_key(password: bytes, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
    )
    return kdf.derive(password)


def _decrypt_payload(payload: Dict[str, Any], password: str) -> bytes:
    salt = base64.b64decode(payload["s"])
    nonce = base64.b64decode(payload["n"])
    ciphertext = base64.b64decode(payload["ct"])

    key = _derive_key(password.encode("utf-8"), salt)
    aesgcm = AESGCM(key)

    try:
        return aesgcm.decrypt(nonce, ciphertext, None)
    except InvalidTag:
        raise RuntimeError("❌ Decryption failed (InvalidTag)")


def load_cookies(file_path: Path, decrypt_key: str) -> List[Dict[str, Any]]:
    print("[STEP] Loading and decrypting cookies...", flush=True)

    with file_path.open("r", encoding="utf-8") as f:
        payload = json.load(f)

    plaintext = _decrypt_payload(payload, decrypt_key)
    cookies = json.loads(plaintext.decode("utf-8"))

    if isinstance(cookies, dict):
        if "cookies" in cookies and isinstance(cookies["cookies"], list):
            cookies = cookies["cookies"]
        else:
            cookies = [cookies]

    for c in cookies:
        if "partitionKey" in c and isinstance(c["partitionKey"], dict):
            if "topLevelSite" in c["partitionKey"]:
                c["partitionKey"] = str(c["partitionKey"]["topLevelSite"])
            else:
                del c["partitionKey"]

        if "sameSite" in c:
            val = str(c["sameSite"]).lower()
            if val in ["no_restriction", "none", "unspecified", "null"]:
                c["sameSite"] = "None"
            elif val == "lax":
                c["sameSite"] = "Lax"
            elif val == "strict":
                c["sameSite"] = "Strict"
            else:
                c["sameSite"] = "Lax"

    print("[OK] Cookies loaded successfully", flush=True)
    return cookies


def clear_json_file(file_path: str):
    print(f"[INIT] Clearing contents of {file_path}...", flush=True)
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump([], f)


def append_to_json(file_path: str, data: Dict[str, str]):
    existing_data = []
    path = Path(file_path)
    if path.exists() and path.stat().st_size > 0:
        try:
            with open(path, "r", encoding="utf-8") as f:
                existing_data = json.load(f)
        except Exception:
            existing_data = []
    
    existing_data.append(data)
    
    with open(path, "w", encoding="utf-8") as f:
        json.dump(existing_data, f, ensure_ascii=False, indent=4)


# =========================
# MAIN
# =========================
def run(decrypt_key: str):
    print("[START] Script started", flush=True)

    clear_json_file(OUTPUT_FILE)

    cookies = load_cookies(Path(LINKEDIN_COOKIES_FILE), decrypt_key)

    stealth = Stealth()
    pw_cm = stealth.use_sync(sync_playwright())
    pw = pw_cm.__enter__()

    browser = None
    page = None
    try:
        browser = pw.chromium.launch(
            headless=HEADLESS,
            args=[
                "--start-maximized",
                "--disable-blink-features=AutomationControlled"
            ]
        )

        context = browser.new_context(
            no_viewport=True,
            user_agent=USER_AGENT
        )

        context.grant_permissions(["clipboard-read", "clipboard-write"])
        context.add_cookies(cookies)

        page = context.new_page()

        linkedin_feed = "https://www.linkedin.com/feed/"
        print(f"[STEP] Opening LinkedIn Feed: {linkedin_feed}", flush=True)
        page.goto(linkedin_feed, wait_until="load")
        
        print("[VALIDATE] Searching for login verification locator: 'Me' button (Timeout: 120s)...", flush=True)
        login_indicator = page.get_by_role('button', name='Me', exact=True)
        
        login_indicator.wait_for(state="visible", timeout=120000)
        print("[SUCCESS] Login verified via 'Me' button. Proceeding to target URL page...", flush=True)

        current_page = 1
        empty_pages_count = 0

        while True:
            url_to_navigate = TARGET_URL if current_page == 1 else f"{TARGET_URL}&page={current_page}"
            print(f"[STEP] Navigating to target page {current_page}: {url_to_navigate}", flush=True)
            page.goto(url_to_navigate, wait_until="load")
            page.wait_for_timeout(5000)

            all_links = page.get_by_role('link').all()
            
            if not all_links:
                print(f"[INFO] No role links found on page {current_page}.", flush=True)
                sys.exit(1)

            profiles_scraped_on_this_page = 0
            processed_names = set()

            for link in all_links:
                try:
                    raw_text = link.inner_text()
                    if not raw_text:
                        continue
                    
                    # Newline aur extra/hidden spaces ko clean karke single space se normalize karein
                    normalized_text = re.sub(r'\s+', ' ', raw_text).strip()
                    
                    if not normalized_text or len(normalized_text) > 80:
                        continue
                    
                    # Cleaned name nikalne ke liye 'Verified' check lagayein
                    if "Verified" in normalized_text:
                        clean_name = re.sub(r'\s+Verified$', '', normalized_text).strip()
                    else:
                        clean_name = normalized_text

                    if not clean_name or clean_name in processed_names:
                        continue

                    # Name match karne ke liye flexible regex patterns jo normal aur verified dono ko handle karein
                    name_regex = re.compile(rf"^{re.escape(clean_name)}(\s+Verified)?$")
                    name_locator = page.get_by_role('link', name=name_regex, exact=True)
                    
                    # Connect text button ke liye cleaned structural identity pass karein
                    connect_locator = page.get_by_role('link', name=f'Invite {clean_name} to connect', exact=True)

                    if name_locator.count() > 0 and connect_locator.count() > 0:
                        processed_names.add(clean_name)
                        profile_url = name_locator.first.get_attribute("href")
                        if profile_url and profile_url.startswith("/"):
                            profile_url = f"https://www.linkedin.com{profile_url}"

                        print(f"[SCRAPE] Match found strictly via specified locators: {clean_name}", flush=True)
                        profile_data = {
                            "name": clean_name,
                            "profile_link": profile_url
                        }
                        append_to_json(OUTPUT_FILE, profile_data)
                        profiles_scraped_on_this_page += 1
                        
                except Exception:
                    continue

            print(f"[PAGE SUMMARY] Page {current_page} execution done. Appended: {profiles_scraped_on_this_page}", flush=True)

            if profiles_scraped_on_this_page == 0:
                empty_pages_count += 1
            else:
                empty_pages_count = 0

            if empty_pages_count >= 3:
                print("[TERMINATE] Continuous 3 pages with 0 results recorded. Stopping workflow.", flush=True)
                break

            current_page += 1
            time.sleep(random.uniform(2, 5))

        print("[SUCCESS] All rules executed. Preparing final window teardown.", flush=True)
        custom_random_wait(15, 30)

    except SystemExit:
        raise
    except Exception as e:
        print("[ERROR] Script execution broke down due to trace:", e, flush=True)
        if page:
            try:
                screenshot_path = "failure_screenshot.png"
                page.screenshot(path=screenshot_path, full_page=True)
                print(f"[SCREENSHOT] Failure screenshot saved at: {screenshot_path}", flush=True)
            except Exception as s_e:
                print(f"[ERROR] Could not capture screenshot: {s_e}", flush=True)
        sys.exit(1)

    finally:
        if browser:
            try:
                browser.close()
            except:
                pass

        try:
            pw_cm.__exit__(None, None, None)
        except:
            pass

        print("[DONE] Script execution environment torn down cleanly.", flush=True)


if __name__ == "__main__":
    load_dotenv()
    DECRYPT_KEY = os.getenv("DECRYPT_KEY")
    if not DECRYPT_KEY:
        raise RuntimeError("DECRYPT_KEY missing in environment variables")
    run(DECRYPT_KEY)