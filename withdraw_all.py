import time
import json
import os
import re
import random
import sys
from datetime import datetime, timedelta
from playwright.sync_api import expect
from login import login_and_get_context

def withdraw_all():
    json_file = 'scraped_connections.json'
    
    if not os.path.exists(json_file):
        print(f"[ERROR] {json_file} nahi mili!", flush=True)
        sys.exit(1)

    with open(json_file, 'r', encoding='utf-8') as f:
        connections = json.load(f)

    if not connections:
        print("[INFO] JSON khali hai.", flush=True)
        return

    # --- CONDITION 1: Latest Timestamp + 7 Days Check ---
    timestamps = [datetime.strptime(c['timestamp'], "%Y-%m-%d %H:%M:%S") for c in connections if 'timestamp' in c]
    
    if not timestamps:
        print("[WAIT] Kisi bhi record mein timestamp nahi mila.", flush=True)
        return

    latest_ts = max(timestamps)
    print(f"[INFO] Latest Timestamp found: {latest_ts}", flush=True)

    current_date = datetime.now()
    threshold_date = latest_ts + timedelta(days=7)

    if threshold_date > current_date:
        print(f"[WAIT] (Latest TS + 7 days) {threshold_date} is in the future. Current is {current_date}.", flush=True)
        status_1 = "WAIT"
    else:
        print(f"[PROCEED] 7 days have passed since the latest invitation.", flush=True)
        status_1 = "PROCEED"

    # --- CONDITION 2: Check if 'withdraw' key exists in ALL elements ---
    all_have_withdraw = all('withdraw' in c for c in connections)
    
    if all_have_withdraw:
        print("[PROCEED] All elements have the 'withdraw' key.", flush=True)
        status_2 = "PROCEED"
    else:
        print("[WAIT] Some elements are missing the 'withdraw' key.", flush=True)
        status_2 = "WAIT"

    if status_1 == "PROCEED" and status_2 == "PROCEED":
        print("\n[START] Both conditions met. Navigating to LinkedIn Manager...", flush=True)
    else:
        print("\n[STOP] Conditions not met. Ending program.", flush=True)
        return

    # 2. Start Stealth Browser (Login)
    pw, browser, context, page = login_and_get_context()

    try:
        page.goto("https://www.linkedin.com/mynetwork/invitation-manager/sent/")
        print("[NAVIGATE] Sent invitations page loaded.", flush=True)
        time.sleep(random.uniform(8, 15))

        retry_count = 0
        max_retries = 3

        while True:
            # Locate: Withdraw Link
            target_link = page.get_by_role('listitem').get_by_role('link', name="Withdraw").first

            if target_link.count() == 0 or not target_link.is_visible():
                if retry_count < max_retries:
                    retry_count += 1
                    print(f"[SCROLL] No buttons visible. Attempting scroll {retry_count}/{max_retries}...", flush=True)
                    
                    # Workspace locator ko scroll down karna
                    workspace = page.locator('#workspace')
                    if workspace.count() > 0:
                        workspace.evaluate("el => el.scrollTop = el.scrollHeight")
                    else:
                        # Fallback: Agar workspace na mile toh window scroll
                        page.mouse.wheel(0, 1000)
                    
                    time.sleep(random.uniform(5, 15))
                    continue # Firse check karega loop ke shuru mein
                else:
                    print("[FINISH] No more withdraw buttons found after 3 scrolls. All done.", flush=True)
                    break

            # Reset retry_count agar button mil gaya
            retry_count = 0

            print(f"[ACTION] Found a pending invitation. Clicking Withdraw...", flush=True)
            target_link.click()
            
            time.sleep(random.uniform(5, 15))
            popup_heading = page.get_by_role('heading', name='Withdraw invitation')
            
            if popup_heading.is_visible():
                print("[VERIFIED] Withdraw popup opened.", flush=True)
                time.sleep(random.uniform(5, 15))
                
                confirm_btn = page.get_by_role('button', name=re.compile(r"Withdraw", re.IGNORECASE))
                
                if confirm_btn.is_visible():
                    confirm_btn.click()
                    print("[SUCCESS] Invitation withdrawn.", flush=True)
                    time.sleep(random.uniform(5, 15))
                else:
                    print("[ERROR] Confirmation button not found!", flush=True)
                    sys.exit(1)
            else:
                print("[ERROR] Popup heading not found!", flush=True)
                sys.exit(1)

            time.sleep(random.uniform(2, 5))

    except Exception as e:
        print(f"[CRITICAL ERROR] {e}", flush=True)
        sys.exit(1)
    finally:
        print("[INFO] Closing session.", flush=True)
        browser.close()
        pw.stop()

if __name__ == "__main__":
    withdraw_all()