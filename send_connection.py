import os
import sys
import json
import time
import random
import base64
import re
from datetime import datetime
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

    cookies = load_cookies(Path(LINKEDIN_COOKIES_FILE), decrypt_key)
    connections_path = Path(CONNECTIONS_FILE)
    connections = load_connections(connections_path)

    if not connections:
        print("[DONE] No connections data to process.", flush=True)
        return

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

        # Loop over profiles in JSON
        for index, item in enumerate(connections):
            # Agar 'sent' key already present hai, toh skip karein
            if "sent" in item:
                continue

            name = item.get("name", "Unknown")
            profile_link = item.get("profile_link")

            if not profile_link:
                print(f"[SKIP] Missing profile link for index {index}", flush=True)
                continue

            print(f"[PROCESSING] Moving to profile: {name} ({profile_link})", flush=True)
            
            try:
                # 1. Target Profile Par Jana
                page.goto(profile_link, wait_until="load")
                custom_random_wait(3, 6) # Page fully stabilize hone ke liye chota wait

                # 2. Lazy Column locator inside checking pattern text match structure
                regex_pattern = re.compile(f"Invite {re.escape(name)}", re.IGNORECASE)
                connect_button = page.get_by_test_id('lazy-column').get_by_role('link', name=regex_pattern)

                if connect_button.is_visible() or connect_button.count() > 0:
                    print(f"[ACTION] 'Invite' button found for {name}. Clicking now...", flush=True)
                    connect_button.click()
                    
                    # Connect click karne ke baad wait: 15, 30 random seconds
                    custom_random_wait(15, 30)

                    # Confirmation button handle karna
                    confirm_button = page.get_by_role('button', name='Send without a note', exact=True)
                    if confirm_button.is_visible() or confirm_button.count() > 0:
                        print("[ACTION] 'Send without a note' clicked.", flush=True)
                        confirm_button.click()
                        
                        # Note submit confirm click ke baad wait: 15, 30 random seconds
                        custom_random_wait(15, 30)
                    else:
                        print("[INFO] 'Send without a note' button popup missing or auto-sent.", flush=True)
                else:
                    print(f"[INFO] Connect / Invite link button not found for {name}.", flush=True)

            except Exception as item_error:
                print(f"[WARNING] Error handling item {name}: {item_error}", flush=True)

            # 3. State JSON append step (Chahe button mile ya na mile)
            item["sent"] = True
            item["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            item["withdrawn"] = False

            # JSON file live save update line
            save_connections(connections_path, connections)
            print(f"[SUCCESS] Logs updated for {name}. Requesting browser environment teardown exit sequence.\n", flush=True)
            
            # Browser exit policy for per execution batch cycle
            break

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