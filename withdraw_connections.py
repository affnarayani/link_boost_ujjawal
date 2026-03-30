import time
import json
import os
import re
import random
from datetime import datetime, timedelta
import sys
from login import login_and_get_context 

def get_eligible_index():
    """
    JSON scan karke pehla eligible candidate dhoondhna:
    1. invited == True
    2. 'withdraw' key present nahi honi chahiye (Fresh profile)
    3. timestamp >= 7 days old
    """
    json_file = 'scraped_connections.json'
    if not os.path.exists(json_file):
        print(f"[ERROR] {json_file} nahi mili!")
        sys.exit(1)

    with open(json_file, 'r', encoding='utf-8') as f:
        connections = json.load(f)

    current_time = datetime.now()
    seven_days_ago = current_time - timedelta(days=7)

    for index, person in enumerate(connections):
        # RULE 1: Invite sent hona chahiye
        # RULE 2: 'withdraw' key honi hi nahi chahiye (matlab process nahi hua hai)
        if person.get('invited') is True and 'withdraw' not in person:
            ts_str = person.get('timestamp')
            if ts_str:
                try:
                    post_time = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                    # RULE 3: 7 din purana logic
                    if post_time <= seven_days_ago:
                        return index 
                except ValueError:
                    continue
    return None

def run_withdrawal():
    # Pehle eligibility check karo
    print("[CHECK] Searching for fresh eligible candidates (> 7 days and unprocessed)...")
    target_index = get_eligible_index()

    if target_index is None:
        print("[FINISH] No fresh eligible connections found. Browser session skipped.")
        return

    # Agar mil gaya, tabhi Login call hoga
    print(f"[INFO] Found fresh candidate at index {target_index}. Starting Browser...")
    pw, browser, context, page = login_and_get_context()

    try:
        with open('scraped_connections.json', 'r', encoding='utf-8') as f:
            connections = json.load(f)

        person = connections[target_index]
        profile_link = person.get('link')
        profile_name = person.get('name', 'User')

        print(f"\n[PROCESS] Target: {profile_name}")
        print(f"[NAVIGATE] Visiting: {profile_link}")
        
        page.goto(profile_link)
        # Random wait for profile load
        time.sleep(random.uniform(8, 15))

        # Withdraw Trigger (Pending button)
        withdraw_trigger = page.get_by_test_id('lazy-column').get_by_role('link', name=re.compile(r"Pending.*", re.IGNORECASE))

        if withdraw_trigger.count() > 0 and withdraw_trigger.first.is_visible():
            print(f"[ACTION] Pending button found. Opening popup...")
            withdraw_trigger.first.click()
            
            time.sleep(random.uniform(6, 12))
            
            # Confirm Withdraw Button
            confirm_regex = re.compile(r"Withdrawn invitation sent to.*", re.IGNORECASE)
            withdraw_confirm_btn = page.get_by_role('button', name=confirm_regex)
            
            try:
                # Click and finalize
                withdraw_confirm_btn.click()
                print(f"[SUCCESS] Withdrawn successfully for {profile_name}!")
                
                time.sleep(random.uniform(5, 10))
                connections[target_index]['withdraw'] = True
            except Exception as e:
                print(f"[WARNING] Popup button click failed: {e}")
                sys.exit(1)
                # Button nahi mila par attempt ho gaya, isliye true/false mark karna zaroori hai
                connections[target_index]['withdraw'] = False
        else:
            print(f"[SKIP] Pending button not found (Maybe already withdrawn or accepted).")
            connections[target_index]['withdraw'] = False

        # Save result and exit
        with open('scraped_connections.json', 'w', encoding='utf-8') as f:
            json.dump(connections, f, indent=4)
        print("[SAVE] JSON updated. Closing program.")

    except Exception as e:
        print(f"[CRITICAL ERROR] Execution failed: {e}")
        sys.exit(1)
    finally:
        browser.close()
        pw.stop()

if __name__ == "__main__":
    run_withdrawal()