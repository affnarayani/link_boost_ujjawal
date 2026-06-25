import os
import sys
import json
import time
import random
import base64
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
STATUS_FILE = Path("comment_status.json")
POST_DATA_FILE = Path("post_to_comment.json")
COMMENTED_FILE = Path("commented.json")

PBKDF2_ITERATIONS = 200_000

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"


# =========================
# DYNAMIC WAITS
# =========================
def custom_random_wait(min_sec, max_sec):
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
    # 1. CONDITION CHECK: comment_status.json
    # ---------------------------------------------------------
    if not STATUS_FILE.exists():
        print(f"[ERROR] {STATUS_FILE.name} nahi mili! Execution stopped.", flush=True)
        sys.exit(0)

    try:
        with STATUS_FILE.open("r", encoding="utf-8") as f:
            status_data = json.load(f)
    except Exception as e:
        print(f"[ERROR] {STATUS_FILE.name} parse karne me issue: {e}", flush=True)
        sys.exit(0)

    # Status validation logic
    if (status_data.get("post_to_comment_found") is True and 
        status_data.get("comment_generated") is True and 
        status_data.get("comment_posted") is False):
        print("[OK] Target status matched. Proceeding with browser setup...", flush=True)
    else:
        print(f"[INFO] Status requirements match nahi hui. Status mila: {status_data}. Exiting...", flush=True)
        sys.exit(0)

    # ---------------------------------------------------------
    # 2. READ DATA FROM post_to_comment.json
    # ---------------------------------------------------------
    if not POST_DATA_FILE.exists():
        print(f"[ERROR] {POST_DATA_FILE.name} nahi mili! Content aur URL extraction missing.", flush=True)
        sys.exit(0)

    try:
        with POST_DATA_FILE.open("r", encoding="utf-8") as f:
            post_data = json.load(f)
        target_url = post_data.get("url", "").strip()
        comment_text = post_data.get("comment", "").strip()
    except Exception as e:
        print(f"[ERROR] {POST_DATA_FILE.name} read karne me error: {e}", flush=True)
        sys.exit(0)

    if not target_url or not comment_text:
        print(f"[ERROR] URL ya Comment Text dono me se koi ek data missing hai file me. Exiting...", flush=True)
        sys.exit(0)

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

        # Feed page par jaana aur login verify karna
        linkedin_url = "https://www.linkedin.com/feed/"
        print(f"[STEP] Opening LinkedIn Feed: {linkedin_url}", flush=True)
        page.goto(linkedin_url, wait_until="load")
        
        print("[STEP] Verifying login status via 'Me' button...", flush=True)
        me_button = page.get_by_role('button', name='Me', exact=True)
        me_button.wait_for(state="visible", timeout=120000)
        print("[SUCCESS] Login success! 'Me' button detected.", flush=True)

        custom_random_wait(5, 10)

        # ---------------------------------------------------------
        # 3. NAVIGATE TO TARGET POST URL
        # ---------------------------------------------------------
        print(f"[STEP] Navigating to target post URL: {target_url}", flush=True)
        page.goto(target_url, wait_until="load")
        custom_random_wait(6, 12)

        # ---------------------------------------------------------
        # 4. LOCATE TEXTBOX AND TYPE LIKE HUMAN
        # ---------------------------------------------------------
        print("[STEP] Locating comment text editor input...", flush=True)
        
        # CSS class locator
        comment_box = page.locator('.comments-comment-box-comment__text-editor')
        
        comment_box.wait_for(state="visible", timeout=60000)
        comment_box.click()
        
        custom_random_wait(2, 4)
        
        print("[STEP] Typing comment with human simulation delay...", flush=True)
        # FIX: timeout=0 add kiya hai taaki lamba comment type hote waqt Playwright crash na kare
        comment_box.press_sequentially(comment_text, delay=random.uniform(60, 140), timeout=0)
        
        # Type karne ke baad wait for 3, 6 sec
        custom_random_wait(3, 6)

        # ---------------------------------------------------------
        # 5. KEYBOARD NAVIGATION: 3x TAB THEN ENTER WITH INTERVALS
        # ---------------------------------------------------------
        print("[STEP] Executing Keyboard Flow: 3 Times TAB then 1 Time ENTER...", flush=True)
        for i in range(1, 4):
            print(f"[ACTION] Pressing TAB key ({i}/3)...", flush=True)
            page.keyboard.press("Tab")
            custom_random_wait(3, 6)
            
        print("[ACTION] Pressing ENTER key to post comment...", flush=True)
        page.keyboard.press("Enter")
        
        # Post submission ke baad wait for 6, 12 seconds
        custom_random_wait(6, 12)

        # ---------------------------------------------------------
        # 6. REACT LIKE ON THE POST
        # ---------------------------------------------------------
        print("[STEP] Locating and clicking 'React Like' button...", flush=True)
        like_btn = page.get_by_role('button', name='React Like', exact=True)
        if like_btn.count() > 0:
            like_btn.first.click()
            print("[SUCCESS] Post liked successfully.", flush=True)
        else:
            print("[WARNING] 'React Like' button screen par locate nahi ho paya.", flush=True)

        # ---------------------------------------------------------
        # 7. APPEND URL TO commented.json
        # ---------------------------------------------------------
        print(f"[STEP] Sourcing and appending URL to {COMMENTED_FILE.name}...", flush=True)
        commented_urls = []
        
        if COMMENTED_FILE.exists():
            try:
                with COMMENTED_FILE.open("r", encoding="utf-8") as f:
                    commented_urls = json.load(f)
                if not isinstance(commented_urls, list):
                    commented_urls = [commented_urls]
            except Exception:
                commented_urls = []

        commented_urls.append(target_url)

        with COMMENTED_FILE.open("w", encoding="utf-8") as f:
            json.dump(commented_urls, f, indent=4, ensure_ascii=False)
        print(f"[SUCCESS] URL safely appended to history in {COMMENTED_FILE.name}.", flush=True)

        # =========================================================
        # SUCCESS-ONLY STEPS (Skipped entirely if program fails)
        # =========================================================
        
        # Step 1: comment_status.json mein comment_posted true kar do
        print(f"[STEP] Updating {STATUS_FILE.name} -> comment_posted = true", flush=True)
        status_data["comment_posted"] = True
        with STATUS_FILE.open("w", encoding="utf-8") as f:
            json.dump(status_data, f, indent=4, ensure_ascii=False)
        print("[SUCCESS] Comment status updated to posted.", flush=True)

        # Step 2: 15, 30 sec ke wait ke baad browser close (Wait yahan hoga, close finally me hoga)
        print("[STEP] Execution successful. Waiting 15-30 seconds before environment teardown...", flush=True)
        custom_random_wait(15, 30)

        # Step 3: comment_status.json mein sab ko false kar do
        print(f"[STEP] Resetting all flags to false inside {STATUS_FILE.name}...", flush=True)
        reset_status = {
            "post_to_comment_found": False,
            "comment_generated": False,
            "comment_posted": False
        }
        with STATUS_FILE.open("w", encoding="utf-8") as f:
            json.dump(reset_status, f, indent=4, ensure_ascii=False)
        print("[SUCCESS] All status flags reset to false after full completion.", flush=True)

    except SystemExit:
        raise
    except Exception as e:
        print("[ERROR] Script crashed during active execution state:", e, flush=True)
        sys.exit(1)

    finally:
        # UNIVERSAL CLEANUP: Browser har haal me close hoga (Chahe Success ho ya Fail)
        if browser:
            try:
                browser.close()
                print("[INFO] Browser closed cleanly via finally block.", flush=True)
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