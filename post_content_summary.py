import subprocess
import sys
import json
import re
import os
import requests
import time
import random
import shutil

# --- Automatic Update Logic ---
def update_packages():
    """Har baar run hone se pehle g4f ko update karta hai"""
    print("[INIT] Updating g4f package... please wait.")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-U", "g4f"])
        print("[INIT] g4f updated to the latest version.\n")
    except Exception as e:
        print(f"[WARNING] Update failed, continuing with current version: {e}")

# Script shuru hote hi update call
update_packages()

import g4f
from login import login_and_get_context

# --- Configuration ---
GITHUB_RAW_URL = "https://raw.githubusercontent.com/affnarayani/ninetynine_credits_legal_advice_app_content/refs/heads/main/content.json"
CONTENT_FILE = "content.json"
POSTED_FILE = "posted_content.json"
TEMP_FOLDER = "temp"

def sanitize_ai_content(text):
    """AI content se * aur ** symbols ko remove karna"""
    # Remove bold/italic markers and special symbols
    clean_text = text.replace("**", "").replace("*", "")
    # Remove leading/trailing quotes or extra spaces
    clean_text = clean_text.strip().strip('"').strip("'")
    return clean_text

def rewrite_with_g4f(text):
    """g4f rewrite with strict no-formatting rules (Target: ~120 words)"""
    print("[AI] Rewriting description with g4f...")
    
    prompt = (
        f"Task: Rewrite the legal content below into a high-engagement LinkedIn post of approximately 120 words.\n"
        f"Rules:\n"
        f"1. Structure: Exactly two paragraphs. First paragraph must be a bold 'Hook' to grab attention. Second paragraph should be the 'Body' explaining the core takeaway.\n"
        f"2. Engagement: End with an engagement-seeking question to encourage comments.\n"
        f"3. SEO Friendly: Use professional, searchable, and clear language.\n"
        f"4. Formatting: Start directly with the content. No intro/outro text (like 'Here is your post').\n"
        f"5. No Symbols: Do NOT use any special characters like * or **. Use plain text only.\n"
        f"6. Spacing: Use a single empty line (\n\n) between the two paragraphs.\n"
        f"Content: {text}"
    )
    
    try:
        response = g4f.ChatCompletion.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
        )
        return sanitize_ai_content(response)
    except Exception as e:
        print(f"[ERROR] g4f rewrite failed: {e}. Using original clean text.")
        return sanitize_ai_content(text)

def random_delay(step_name, min_s=5, max_s=15):
    delay = random.uniform(min_s, max_s)
    print(f"[STEP] {step_name} | Waiting for {delay:.2f} seconds...")
    time.sleep(delay)

def clean_temp():
    if os.path.exists(TEMP_FOLDER):
        shutil.rmtree(TEMP_FOLDER)
    os.makedirs(TEMP_FOLDER)

def clean_html(raw_html):
    """Initial cleaning of GitHub HTML content"""
    clean_text = re.sub(r'</?p>', '', raw_html)
    clean_text = re.sub(r'\n\s*\n+', '\n\n', clean_text)
    return clean_text.strip()

def download_image(url):
    print(f"[INFO] Downloading image: {url}")
    local_filename = os.path.join(TEMP_FOLDER, "post_image.jpg")
    try:
        with requests.get(url, stream=True, timeout=20) as r:
            r.raise_for_status()
            with open(local_filename, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        return os.path.abspath(local_filename)
    except Exception as e:
        print(f"[ERROR] Image download failed: {e}")
        return None

def run_post_automation():
    clean_temp()
    
    # 1. Fetch Content
    try:
        response = requests.get(GITHUB_RAW_URL, timeout=20)
        new_content = response.json()
    except Exception as e:
        print(f"[ERROR] Fetch failed: {e}")
        return

    # 2. History check
    posted_data = []
    if os.path.exists(POSTED_FILE):
        with open(POSTED_FILE, "r", encoding="utf-8") as f:
            try: posted_data = json.load(f)
            except: posted_data = []
    
    posted_titles = [item['title'] for item in posted_data]

    # 3. Find target (Char Limit Check Hataya Gaya Hai)
    target_item = None
    original_desc = ""
    for item in reversed(new_content):
        if item['title'] not in posted_titles:
            original_desc = clean_html(item['description'])
            target_item = item
            break

    if not target_item:
        print("[INFO] No new content found.")
        return

    # 4. AI Rewrite & Sanitize
    final_description = rewrite_with_g4f(original_desc)

    # 5. Media
    image_path = download_image(target_item['image'])
    if not image_path: return

    # 6. LinkedIn Upload
    pw, browser, context, page = login_and_get_context()

    try:
        random_delay("LinkedIn Load", 15, 25)
        page.get_by_role("button", name="Start a post").click()
        random_delay("Editor Open")

        editor = page.get_by_role("textbox", name="Text editor for creating")
        editor.wait_for(state="visible")
        editor.fill(final_description)
        random_delay("Post-typing")
        
        page.get_by_role("button", name="Add media").click()
        page.set_input_files("input[type='file']", image_path)
        random_delay("Upload delay")
        
        page.get_by_role("button", name="Next").click()
        random_delay("Next click")
        
        page.get_by_role("button", name="Post", exact=True).click()
        random_delay("Final Sync", 15, 20)

        # 7. Update JSON
        posted_data.insert(0, target_item)
        with open(POSTED_FILE, "w", encoding="utf-8") as f:
            json.dump(posted_data, f, indent=4)
        print(f"[SUCCESS] Posted: {target_item['title']}")

    except Exception as e:
        print(f"[ERROR] Failed: {e}")
    finally:
        browser.close()
        pw.stop()
        clean_temp()

if __name__ == "__main__":
    run_post_automation()