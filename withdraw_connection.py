import os
import sys
import json
import time
import random
import base64
import re
from datetime import datetime, timedelta
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

LINKEDIN_COOKIES_FILE = "linkedin_cookies.json.encrypted"
CONNECTIONS_FILE = "scraped_connections.json"

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


# =========================
# JSON DATA HANDLING
# =========================
def load_connections(file_path: Path) -> List[Dict[str, Any]]:
    if not file_path.exists():
        print(f"[ERROR] {file_path.name} not found.", flush=True)
        return []
    with file_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_connections(file_path: Path, data: List[Dict[str, Any]]):
    with file_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    print(f"[INFO] Saved status updates to {file_path.name}", flush=True)


# =========================
# MAIN
# =========================
def run(decrypt_key: str):
    print("[START] Script started", flush=True)

    connections_path = Path(CONNECTIONS_FILE)
    connections = load_connections(connections_path)

    if not connections:
        print("[DONE] No data found in connections JSON file.", flush=True)
        sys.exit(0)

    target_item = None
    target_index = -1
    seven_days_ago = datetime.now() - timedelta(days=7)

    # 1. JSON filter validation conditions check karna
    for index, item in enumerate(connections):
        # Condition A: withdrawn false hona chahiye (ya key missing ho)
        if item.get("withdrawn") is False:
            timestamp_str = item.get("timestamp")
            if timestamp_str:
                try:
                    # Expected format matching your logs: "YYYY-MM-DD HH:MM:SS"
                    item_time = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
                    
                    # Condition B: Timestamp 7 din se pehle (old) ka hona chahiye
                    if item_time < seven_days_ago:
                        target_item = item
                        target_index = index
                        break
                except ValueError:
                    print(f"[WARNING] Invalid date format for index {index}, skipping.", flush=True)

    # Agar koi profile conditions meet nahi karti, toh sysexit0
    if target_item is None:
        print("[INFO] No profiles found with withdrawn=False and timestamp older than 7 days. Exiting.", flush=True)
        sys.exit(0)

    name = target_item.get("name", "Unknown")
    profile_link = target_item.get("profile_link")

    if not profile_link:
        print(f"[ERROR] Target profile '{name}' doesn't have a valid profile_link. Exiting.", flush=True)
        sys.exit(0)

    print(f"[ELIGIBLE] Found Profile: {name} | Timestamp: {target_item['timestamp']}", flush=True)

    # Decrypt cookies only when validation passes
    cookies = load_cookies(Path(LINKEDIN_COOKIES_FILE), decrypt_key)

    stealth = Stealth()
    pw_cm = stealth.use_sync(sync_playwright())
    pw = pw_cm.__enter__()

    browser = None
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

        linkedin_url = "https://www.linkedin.com/feed/"
        print(f"[STEP] Opening LinkedIn Feed: {linkedin_url}", flush=True)
        page.goto(linkedin_url, wait_until="load")
        
        print("[STEP] Verifying login status via 'Me' button...", flush=True)
        me_button = page.get_by_role('button', name='Me', exact=True)
        me_button.wait_for(state="visible", timeout=120000)
        print("[SUCCESS] Login success! 'Me' button detected.\n", flush=True)

        print(f"[NAVIGATION] Navigating to target profile: {profile_link}", flush=True)
        page.goto(profile_link, wait_until="load")
        custom_random_wait(3, 6) # Page fully load hone ka short wait

        # Locators setup
        pending_button = page.get_by_test_id('lazy-column').get_by_role('link', name='Pending, click to withdraw')

        # Check if Pending button is visible
        if pending_button.is_visible() or pending_button.count() > 0:
            print("[ACTION] Pending button found. Clicking to open withdraw modal...", flush=True)
            pending_button.click()
            
            # Wait 15 to 30 random seconds after click
            custom_random_wait(15, 30)

            # Locate and click: Withdraw confirmation button (Regex pattern safe text matching)
            confirm_regex = re.compile(r"Withdraw invitation sent to", re.IGNORECASE)
            withdraw_confirm_btn = page.get_by_role('button', name=confirm_regex)

            if withdraw_confirm_btn.is_visible() or withdraw_confirm_btn.count() > 0:
                print("[ACTION] Clicking confirmation 'Withdraw invitation sent to' button.", flush=True)
                withdraw_confirm_btn.click()
                
                # Wait 15 to 30 seconds after final interaction
                custom_random_wait(15, 30)
            else:
                print("[INFO] Confirmation withdraw popup button not found/visible.", flush=True)
        else:
            print("[INFO] 'Pending, click to withdraw' button not found on this profile.", flush=True)

        # Update json array structure state (Chahe pending button mile ya na mile)
        connections[target_index]["withdrawn"] = True
        save_connections(connections_path, connections)
        print(f"[SUCCESS] JSON state updated: withdrawn=True for {name}.", flush=True)

        # Browser close karne se pehle requirement delay wait
        print("[SHUTDOWN] Executing pre-close session buffer wait...", flush=True)
        custom_random_wait(15, 30)

    except SystemExit:
        raise
    except Exception as e:
        print("[ERROR] Script execution broke down due to trace:", e, flush=True)
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