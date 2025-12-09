import json
import os
import time
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from login import login_and_get_driver

# Headless variable - set to False by default, developer can toggle to True for headless mode
headless = True

# Set environment variable based on headless
os.environ['HEADLESS'] = 'true' if headless else 'false'

# XPath for connect button
connect_button = '//*[@id="workspace"]/div/div/div[1]/div/div/div[2]/div/section/div/div/div[2]/div[3]/div/div/div/div/div/a/span'

def main():
    print("Loading scraped_connections.json...", flush=True)
    # Load scraped_connections.json
    with open('scraped_connections.json', 'r') as f:
        connections = json.load(f)

    # Find the first connection where sent_request is False
    profile = None
    for conn in connections:
        if not conn.get('sent_request', False):
            profile = conn
            break

    if not profile:
        print("No pending connections to process.", flush=True)
        return

    profile_url = profile['profile_url']
    print(f"Processing profile: {profile_url}", flush=True)

    # Get logged-in driver from login.py
    print("Logging in and getting driver...", flush=True)
    driver = login_and_get_driver()
    wait = WebDriverWait(driver, 30)

    try:
        # Open the profile URL
        print(f"Opening profile URL: {profile_url}", flush=True)
        driver.get(profile_url)

        # Wait for page to load (basic wait)
        print("Waiting for page to load...", flush=True)
        time.sleep(5)  # Adjust if needed

        # Find and click the first xpath
        print("Finding and clicking the connect button...", flush=True)
        xpath_found = False
        try:
            element1 = wait.until(EC.element_to_be_clickable((By.XPATH, connect_button)))
            element1.click()
            xpath_found = True
            print("Connect button clicked successfully.", flush=True)
        except Exception as e:
            print(f"Connect button not found", flush=True)

        if xpath_found:
            # Wait 15 seconds
            print("Waiting 15 seconds after first click...", flush=True)
            time.sleep(15)

            # Press TAB 3 times with 5s intervals, then ENTER
            print("Sending TAB keys...", flush=True)
            for i in range(3):
                webdriver.ActionChains(driver).send_keys(Keys.TAB).perform()
                print(f"Pressed TAB {i+1}", flush=True)
                time.sleep(5)

            print("Waiting 5 seconds before pressing ENTER...", flush=True)
            time.sleep(5)

            print("Pressing ENTER...", flush=True)
            webdriver.ActionChains(driver).send_keys(Keys.ENTER).perform()

            # Wait 15 seconds
            print("Waiting 15 seconds after sending keys...", flush=True)
            time.sleep(15)

        # Update the JSON
        print("Updating JSON file...", flush=True)
        profile['sent_request'] = True
        profile['sent_request_timestamp'] = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')

        # Save back to file
        with open('scraped_connections.json', 'w') as f:
            json.dump(connections, f, indent=4)

        print("Successfully processed connection.", flush=True)

    finally:
        # Quit the browser
        print("Quitting browser.", flush=True)
        driver.quit()

if __name__ == "__main__":
    main()
