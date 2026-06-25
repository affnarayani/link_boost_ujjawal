import os
import sys
import json
import time
import random
import base64
import re
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
JSON_OUTPUT_FILE = "post_to_comment.json"
STATUS_FILE = "comment_status.json"

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
# MAIN
# =========================
def run(decrypt_key: str):
    print("[START] Script started", flush=True)

    # ---------------------------------------------------------
    # CONDITION CHECK: comment_status.json
    # ---------------------------------------------------------
    status_path = Path(STATUS_FILE)
    if not status_path.exists():
        print(f"[ERROR] {STATUS_FILE} nahi mili! Script aage nahi badhegi.", flush=True)
        sys.exit(1)

    with open(status_path, "r", encoding="utf-8") as f:
        try:
            status_data = json.load(f)
        except json.JSONDecodeError:
            print(f"[ERROR] {STATUS_FILE} ka format invalid hai.", flush=True)
            sys.exit(1)

    if (status_data.get("post_to_comment_found") is not False or 
        status_data.get("comment_generated") is not False or 
        status_data.get("comment_posted") is not False):
        print("[INFO] Status check failed: Flags are not all 'false'. Execution stopped.", flush=True)
        sys.exit(0)

    print("[OK] comment_status.json checks passed. Proceeding...", flush=True)

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
        print("[SUCCESS] Login success! 'Me' button detected.", flush=True)

        custom_random_wait(6, 12)

        # 1. Locate and click control menu for the first post
        print("[STEP] Locating control menu for the first post...", flush=True)
        control_menu_btn = page.get_by_role("button", name=re.compile(r"Open control menu for post by.*", re.IGNORECASE)).first
        control_menu_btn.click()
        custom_random_wait(6, 12)

        # 2. Click 'Copy link to post'
        print("[STEP] Clicking 'Copy link to post'...", flush=True)
        page.get_by_text("Copy link to post").click()
        custom_random_wait(6, 12)

        # 3. Read clipboard and trim URL
        print("[STEP] Reading link from clipboard...", flush=True)
        raw_url = page.evaluate("navigator.clipboard.readText()")
        trimmed_url = raw_url.split("?")[0]
        print(f"[INFO] Trimmed URL: {trimmed_url}", flush=True)
        custom_random_wait(6, 12)

        commented_file = Path("commented.json")
        if commented_file.exists():
            try:
                with open(commented_file, "r", encoding="utf-8") as f:
                    commented_data = json.load(f)
                if isinstance(commented_data, list) and trimmed_url in commented_data:
                    print(f"[INFO] URL already commented: {trimmed_url}. Exiting execution without updates.", flush=True)
                    sys.exit(1)
            except Exception as json_err:
                print(f"[WARNING] commented.json read karne me error aaya: {json_err}", flush=True)

        # 4. Navigate to trimmed link
        print(f"[STEP] Navigating to individual post page...", flush=True)
        page.goto(trimmed_url, wait_until="load")
        custom_random_wait(6, 12)

        # 5. Extract post content
        print("[STEP] Extracting post content...", flush=True)
        post_content = page.locator(".update-components-text").first.inner_text().strip()
        
        # CONDITION CHECK: Character Length < 150
        content_length = len(post_content)
        print(f"[INFO] Extracted content length: {content_length} characters", flush=True)
        
        if content_length < 150:
            print("[FAIL] Content 150 char se kam hai. File update nahi ki jayegi.", flush=True)
            sys.exit(1)

        custom_random_wait(6, 12)

        # ---------------------------------------------------------
        # 6. REPLACE/OVERWRITE JSON FILE (No appending)
        # ---------------------------------------------------------
        print(f"[STEP] Replacing data in {JSON_OUTPUT_FILE}...", flush=True)
        json_path = Path(JSON_OUTPUT_FILE)
        
        # Purana data load nahi kiya ja raha hai, direct naya dict write hoga
        new_post_data = {
            "url": trimmed_url,
            "content": post_content
        }

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(new_post_data, f, indent=4, ensure_ascii=False)
        
        print("[SUCCESS] Old data replaced with new post details successfully.", flush=True)

        # ---------------------------------------------------------
        # UPDATE STATUS ON SUCCESS
        # ---------------------------------------------------------
        print(f"[STEP] Updating {STATUS_FILE}...", flush=True)
        status_data["post_to_comment_found"] = True
        with open(status_path, "w", encoding="utf-8") as f:
            json.dump(status_data, f, indent=4, ensure_ascii=False)
        print("[SUCCESS] post_to_comment_found set to true.", flush=True)

        # BROWSER CLOSE WAIT
        print("[STEP] Final wait before closing browser...", flush=True)
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