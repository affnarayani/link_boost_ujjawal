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
TOPICS_FILE = "ujjawal_linkedin_topics.json"
POST_FILE = "post.json"
IMAGE_PATH = "image/image.png"

PBKDF2_ITERATIONS = 200_000

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"


# =========================
# DYNAMIC WAITS
# =========================
def custom_random_wait(min_sec=15, max_sec=30):
    seconds = random.uniform(min_sec, max_sec)
    print(f"[WAIT] Sleeping for {seconds:.2f} seconds...", flush=True)
    time.sleep(seconds)

def step_wait():
    """Har action ke baad 6 se 12 seconds ka random wait human simulation ke liye"""
    seconds = random.uniform(6, 12)
    print(f"[WAIT] Dynamic step delay: sleeping for {seconds:.2f} seconds...", flush=True)
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
# TEXT PARSING HELPER
# =========================
def clean_and_format_post(post_data: Dict[str, Any]) -> str:
    """Multiple newlines ko single newline me convert karta hai aur content assemble karta hai"""
    p1 = re.sub(r'\n+', '\n', post_data.get("p1", ""))
    p2 = re.sub(r'\n+', '\n', post_data.get("p2", ""))
    p3 = re.sub(r'\n+', '\n', post_data.get("p3", ""))
    conclusion = re.sub(r'\n+', '\n', post_data.get("conclusion", ""))
    
    # Saare paragraphs ko single newline ke sath join karna
    combined_body = f"{p1}\n{p2}\n{p3}\n{conclusion}"
    # Agar joining ke dauran kahin double newline bani ho toh use sanitize karna
    combined_body = re.sub(r'\n+', '\n', combined_body)
    
    # Keywords ko hashtags me badalna
    keywords = post_data.get("keywords", [])
    hashtags = " ".join([f"#{kw.strip()}" for kw in keywords])
    
    # Conclusion ke baad next line me hashtags add karna
    full_text = f"{combined_body}\n{hashtags}"
    return full_text


# =========================
# MAIN RUNNER
# =========================
def run(decrypt_key: str):
    print("[START] Script started", flush=True)

    # 1. Post File aur Topics File Validation Check
    p_file = Path(POST_FILE)
    t_file = Path(TOPICS_FILE)

    if not p_file.exists() or not t_file.exists():
        print(f"[ERROR] Required files missing ({POST_FILE} or {TOPICS_FILE})", flush=True)
        return

    with p_file.open("r", encoding="utf-8") as f:
        post_data = json.load(f)
    current_title = post_data.get("title")

    with t_file.open("r", encoding="utf-8") as f:
        topics_list = json.load(f)

    # Topic ko list mein dhoondhna aur criteria check karna
    target_topic = None
    target_index = -1
    for idx, item in enumerate(topics_list):
        if item.get("topic") == current_title:
            target_topic = item
            target_index = idx
            break

    if not target_topic:
        print(f"[SKIP] Topic '{current_title}' ujjawal_linkedin_topics.json mein nahi mila.", flush=True)
        return

    # Condition Validation
    if not (target_topic.get("content_generated") is True and 
            target_topic.get("image_generated") is True and 
            target_topic.get("posted") is False):
        print(f"[SKIP] Conditions match nahi hui. Script run nahi karega.", flush=True)
        print(f"Current State -> content_generated: {target_topic.get('content_generated')}, image_generated: {target_topic.get('image_generated')}, posted: {target_topic.get('posted')}", flush=True)
        return

    print(f"[PROCEED] Title matching successfully: '{current_title}' is ready to post.", flush=True)

    # Cookies load karega verification ke baad
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
        step_wait()

        # Step 2: Click on 'Start a post'
        print("[STEP] Locating and clicking 'Start a post'...", flush=True)
        page.get_by_role('link', name='Start a post').click()
        step_wait()

        # Step 3: Parse content & Human Simulation Typing
        full_post_text = clean_and_format_post(post_data)
        print("[STEP] Typing post content with human speed simulation...", flush=True)
        
        editor = page.get_by_role('textbox', name='Text editor for creating')
        editor.focus()
        
        # FIXED: timeout=0 daal diya hai taaki typing ke beech me timeout crash na ho
        editor.press_sequentially(full_post_text, delay=40, timeout=0)
        step_wait()

        # Step 4: Media/Image Upload Without OS File Dialog Window
        print("[STEP] Preparing to upload media...", flush=True)
        img_file = Path(IMAGE_PATH)
        if not img_file.exists():
            raise FileNotFoundError(f"❌ Upload hone wali image missing hai: {IMAGE_PATH}")

        with page.expect_file_chooser() as fc_info:
            page.get_by_role('button', name='Add media').click()
        
        file_chooser = fc_info.value
        file_chooser.set_files(str(img_file))
        print("[SUCCESS] Image uploaded successfully.", flush=True)
        step_wait()

        # Step 5: Click Next button on Media Pop-up
        print("[STEP] Clicking 'Next' on the media confirmation popup...", flush=True)
        page.get_by_test_id('interop-shadowdom').get_by_role('button', name='Next').click()
        step_wait()

        # Step 6: Click Final Post Button
        print("[STEP] Clicking 'Post' button to publish...", flush=True)
        page.get_by_role('button', name='Post', exact=True).click()
        step_wait()

        # Step 7: Update JSON Configuration File State
        print(f"[STEP] Updating state in {TOPICS_FILE}...", flush=True)
        topics_list[target_index]["posted"] = True
        
        with t_file.open("w", encoding="utf-8") as f:
            json.dump(topics_list, f, indent=4, ensure_ascii=False)
        print("[SUCCESS] JSON state successfully updated to 'posted': true", flush=True)

        # Final normal verification delay before tearing down
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