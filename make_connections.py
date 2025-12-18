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

def main():
    print("Loading scraped_connections.json...", flush=True)
    # Load scraped_connections.json
    with open('scraped_connections.json', 'r', encoding='utf-8') as f:
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

        # Find connect button by checking XPath with i from 1 to 9
        print("Finding connect button...", flush=True)
        connect_button_element = None
        follow_found = False
        for i in range(1, 10):
            print(f"Checking for i={i}...", flush=True)
            xpath = f'/html/body/div[{i}]/div[3]/div/div/div[2]/div/div/main/section[1]/div[2]/div[3]/div/button/span'
            try:
                element = wait.until(EC.presence_of_element_located((By.XPATH, xpath)))
                text = element.text.strip()
                if text == "Connect":
                    connect_button_element = element
                    print(f"Connect button found at div[{i}] with text 'Connect'.", flush=True)
                    break
                elif text == "Follow":
                    print(f"Follow button found at div[{i}], marking as sent_request.", flush=True)
                    follow_found = True
                    break
            except Exception as e:
                continue

        if follow_found:
            # Update the JSON for follow case
            print("Updating JSON file for Follow case...", flush=True)
            profile['sent_request'] = True
            profile['sent_request_timestamp'] = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')

            # Save back to file
            with open('scraped_connections.json', 'w', encoding='utf-8') as f:
                json.dump(connections, f, indent=4)

            print("Successfully marked as sent_request due to Follow.", flush=True)
            return

        if not connect_button_element:
            print("Connect button not found or does not contain text 'Connect'. Exiting.", flush=True)
            exit(1)

        # Click the connect button
        print("Clicking the connect button...", flush=True)
        connect_button_element.click()
        print("Connect button clicked successfully.", flush=True)

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
        with open('scraped_connections.json', 'w', encoding='utf-8') as f:
            json.dump(connections, f, indent=4)

        print("Successfully processed connection.", flush=True)

    finally:
        # Quit the browser
        print("Quitting browser.", flush=True)
        driver.quit()

if __name__ == "__main__":
    main()
