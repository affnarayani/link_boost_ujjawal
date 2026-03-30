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
        print(f"[ERROR] {json_file} nahi mili!")
        sys.exit(1)

    # 1. JSON Load aur Validation
    with open(json_file, 'r', encoding='utf-8') as f:
        connections = json.load(f)

    if not connections:
        print("[INFO] JSON khali hai.")
        return

    # --- CONDITION 1: Latest Timestamp + 7 Days Check ---
    # Saare timestamps nikaal kar latest dhoondho
    timestamps = [datetime.strptime(c['timestamp'], "%Y-%m-%d %H:%M:%S") for c in connections if 'timestamp' in c]
    
    if not timestamps:
        print("[WAIT] Kisi bhi record mein timestamp nahi mila.")
        return

    latest_ts = max(timestamps)
    print(f"[INFO] Latest Timestamp found: {latest_ts}")

    current_date = datetime.now()
    threshold_date = latest_ts + timedelta(days=7)

    if threshold_date > current_date:
        print(f"[WAIT] (Latest TS + 7 days) {threshold_date} is in the future. Current is {current_date}.")
        status_1 = "WAIT"
    else:
        print(f"[PROCEED] 7 days have passed since the latest invitation.")
        status_1 = "PROCEED"

    # --- CONDITION 2: Check if 'withdraw' key exists in ALL elements ---
    # Saare elements mein 'withdraw' key honi chahiye (True/False doesn't matter)
    all_have_withdraw = all('withdraw' in c for c in connections)
    
    if all_have_withdraw:
        print("[PROCEED] All elements have the 'withdraw' key.")
        status_2 = "PROCEED"
    else:
        print("[WAIT] Some elements are missing the 'withdraw' key.")
        status_2 = "WAIT"

    # --- FINAL TRIGGER ---
    if status_1 == "PROCEED" and status_2 == "PROCEED":
        print("\n[START] Both conditions met. Navigating to LinkedIn Manager...")
    else:
        print("\n[STOP] Conditions not met. Ending program.")
        return

    # 2. Start Stealth Browser (Login)
    pw, browser, context, page = login_and_get_context()

    try:
        # Invitation Manager Page par jao
        page.goto("https://www.linkedin.com/mynetwork/invitation-manager/sent/")
        print("[NAVIGATE] Sent invitations page loaded.")
        time.sleep(random.uniform(8, 15))

        while True:
            # 3. Locate: Withdraw Link (nth(2) inside listitem)
            # Regex used for hasText to match any person/title
            withdraw_target = page.get_by_role('listitem').filter(has_text=re.compile(r".*", re.IGNORECASE)).get_by_role('link', name="Withdraw").nth(0) 
            # Note: nth(2) usually LinkedIn structure mein 'Withdraw' text wala link hota hai.
            # Agar nth(2) exact element hai, toh hum usko target karenge:
            target_link = page.get_by_role('listitem').get_by_role('link', name="Withdraw").first

            if target_link.count() == 0 or not target_link.is_visible():
                print("[FINISH] No more withdraw buttons found. All done.")
                break

            print(f"[ACTION] Found a pending invitation. Clicking Withdraw...")
            target_link.click()
            
            # Pop-up wait and verify
            time.sleep(random.uniform(5, 15))
            popup_heading = page.get_by_role('heading', name='Withdraw invitation')
            
            if popup_heading.is_visible():
                print("[VERIFIED] Withdraw popup opened.")
                time.sleep(random.uniform(5, 15))
                
                # Final Confirm Button
                confirm_btn = page.get_by_role('button', name=re.compile(r"Withdraw", re.IGNORECASE))
                
                if confirm_btn.is_visible():
                    confirm_btn.click()
                    print("[SUCCESS] Invitation withdrawn.")
                    time.sleep(random.uniform(5, 15))
                else:
                    print("[ERROR] Confirmation button not found!")
                    sys.exit(1)
            else:
                print("[ERROR] Popup heading not found!")
                sys.exit(1)

            # Page ko thoda settle hone do next loop se pehle
            time.sleep(random.uniform(2, 5))

    except Exception as e:
        print(f"[CRITICAL ERROR] {e}")
        sys.exit(1)
    finally:
        print("[INFO] Closing session.")
        browser.close()
        pw.stop()

if __name__ == "__main__":
    withdraw_all()