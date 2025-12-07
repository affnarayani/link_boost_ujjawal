# make_connections.py
# Sends LinkedIn connection requests based on scraped_connections.json and config.json
# - Filters by verified status (Yes/No/Any)
# - Respects send_max_connection and random delay between requests
# - Marks sent_request=true for sent, pending, or already-connected cases

from __future__ import annotations

# Headless mode toggle: set True to run Chrome headless; False for visible (headful)
# You can also override via environment variable before running the script.
# Accepted env: HEADLESS=1/true/yes (headless), HEADLESS=0/false/no (headful)
headless = False

# Verified filter toggle: set to one of 'Any', 'Yes', 'No'.
# Accepted values: Yes/Y/True/T/1, No/N/False/F/0, Any/A/* (case-insensitive)
VERIFIED_FILTER = 'Any'

import json
import os
import random
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Tuple

# Console output styling similar to get_info.py
try:
    from colorama import init as colorama_init, Fore, Style
    colorama_init(autoreset=True)
    _USE_COLOR = True
except Exception:
    class _Dummy:
        RESET_ALL = ""
    class _Fore:
        CYAN = ""
        GREEN = ""
        YELLOW = ""
        MAGENTA = ""
        RED = ""
        WHITE = ""
    class _Style:
        BRIGHT = ""
        RESET_ALL = ""
    Fore = _Fore()
    Style = _Style()
    _USE_COLOR = False


def log(kind: str, msg: str) -> None:
    colors = {
        'INFO': Fore.MAGENTA,
        'SENT': Fore.GREEN,
        'PENDING': Fore.YELLOW,
        'ALREADY': Fore.CYAN,
        'ERR': Fore.RED,
        'WARN': Fore.YELLOW,
        'SLEEP': Fore.WHITE,
    }
    color = colors.get(kind.upper(), "")
    print(f"[{kind.upper()}] {msg}", flush=True)

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# Reuse login flow from existing script
try:
    from login import login_and_get_driver  # type: ignore
except Exception as e:
    print("ERROR: Unable to import login.login_and_get_driver. Ensure login.py exists and is valid.", file=sys.stderr)
    raise

# Absolute XPaths provided
X_PROFILE_CONNECT_SPAN = '/html/body/div/div[2]/div[2]/div[2]/div/main/div/div/div[1]/div/div/div[2]/div/section/div/div/div[2]/div[3]/div/div/div/div/div/a/span'
X_SEND_INVITE_MODAL = '/html/body/div[1]/div[4]//div/div[1]/div/div'
X_SEND_INVITE_CONFIRM_SPAN = '/html/body/div[1]/div[4]//div/div[1]/div/div/div[3]/button[2]'

# Paths (resolve relative to this script's directory)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCRAPED_PATH = os.path.join(BASE_DIR, 'scraped_connections.json')
CONFIG_PATH = os.path.join(BASE_DIR, 'config.json')


def load_json_file(path: str) -> Any:
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_json_file(path: str, data: Any) -> None:
    tmp_path = path + ".tmp"
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    # Atomic-ish replace
    os.replace(tmp_path, path)


def load_config(path: str) -> Dict[str, Any]:
    raw = load_json_file(path)
    if isinstance(raw, list):
        merged: Dict[str, Any] = {}
        for item in raw:
            if isinstance(item, dict):
                merged.update(item)
        return merged
    elif isinstance(raw, dict):
        return raw
    else:
        raise ValueError("config.json must be a dict or a list of dicts")


def parse_verified_choice(value: str | None) -> str:
    """Normalize verified choice to one of: 'yes', 'no', 'any'.

    Accepted inputs:
    - Yes: yes, y, true, t, 1
    - No: no, n, false, f, 0
    - Any: any, a, * (default)
    Case-insensitive.
    """
    if not value:
        return 'any'
    v = value.strip().lower()
    if v in {'yes', 'y', 'true', 't', '1'}:
        return 'yes'
    if v in {'no', 'n', 'false', 'f', '0'}:
        return 'no'
    if v in {'any', 'a', '*'}:
        return 'any'
    # Fallback to any if unrecognized
    return 'any'


def verified_matches(profile_verified: Any, choice: str) -> bool:
    if choice == 'any':
        return True
    if choice == 'yes':
        return bool(profile_verified) is True
    if choice == 'no':
        return bool(profile_verified) is False
    return True


def find_connect_span(driver, timeout: int = 15) -> Any:
    """Try to locate the Connect/Pending span, waiting up to `timeout` seconds.

    Tries absolute XPaths with varying top-level div indices: div[8]..div[1].
    Returns the first matching element or None if not found within timeout.
    """
    end_time = time.time() + max(0, timeout)
    while time.time() < end_time:
        for i in range(8, 0, -1):  # 8 -> 1 for robustness
            xp = f'/html/body/div[{i}]/div[3]/div/div/div[2]/div/div/main/section[1]/div[2]/div[3]/div/button/span'
            elems = driver.find_elements(By.XPATH, xp)
            if elems:
                return elems[0]
        time.sleep(0.3)  # small poll interval
    return None


def click_parent_button_of_span(span_el) -> None:
    # span -> button is the parent
    try:
        button_el = span_el.find_element(By.XPATH, "..")
    except Exception:
        # Fallback: click the span itself
        span_el.click()
        return
    button_el.click()


def process_profile(driver, profile: Dict[str, Any]) -> Tuple[str, str]:
    """Process one profile.

    Returns (status, message)
    status in {'sent', 'pending', 'already', 'skipped_error'}
    - 'sent': connection sent
    - 'pending': found Pending button, marked sent_request=true
    - 'already': no button or other state implying already connected, marked sent_request=true
    - 'skipped_error': some error occurred, marked sent_request=true
    """
    url = profile.get('profile_url')
    if not url:
        return 'skipped_error', 'Missing profile_url'

    driver.get(url)
    wait = WebDriverWait(driver, 10)

    # Small wait for page to settle
    time.sleep(1.0)

    try:
        span_el = find_connect_span(driver)
        if not span_el:
            # XPath not present -> treat as already connected
            return 'already', 'No connect/pending button found'

        label = (span_el.text or '').strip()
        if label.lower() == 'connect':
            # Click Connect button (parent of span)
            click_parent_button_of_span(span_el)
            # Wait for modal and confirm button then click it
            try:
                wait.until(EC.presence_of_element_located((By.XPATH, X_SEND_INVITE_MODAL)))
            except Exception:
                # Even if modal wait fails, try clicking confirm as per spec
                pass

            try:
                confirm_span = wait.until(EC.element_to_be_clickable((By.XPATH, X_SEND_INVITE_CONFIRM_SPAN)))
                # Click the parent button of the confirm span
                click_parent_button_of_span(confirm_span)
            except Exception:
                # As a fallback, try clicking the span directly if not done
                try:
                    confirm_span = driver.find_element(By.XPATH, X_SEND_INVITE_CONFIRM_SPAN)
                    confirm_span.click()
                except Exception as inner_exc:
                    return 'skipped_error', f'Failed to confirm invite: {inner_exc}'

            return 'sent', 'Connection request sent'

        elif label.lower() == 'pending':
            return 'pending', 'Request is already pending'
        else:
            # Different primary action (e.g., Message) -> treat as already connected / cannot connect
            return 'already', f'Primary action is {label!r}'

    except Exception as exc:
        return 'skipped_error', f'Error processing profile: {exc}'


def main() -> int:
    # Get verified choice from constant instead of interactive prompt or CLI
    verified_choice = parse_verified_choice(VERIFIED_FILTER)

    # Load config and data
    try:
        config = load_config(CONFIG_PATH)
    except Exception as e:
        log('ERR', f"Unable to read config.json: {e}")
        return 1

    try:
        profiles: List[Dict[str, Any]] = load_json_file(SCRAPED_PATH)
        if not isinstance(profiles, list):
            raise ValueError('scraped_connections.json must be a list of profiles')
    except Exception as e:
        log('ERR', f"Unable to read scraped_connections.json: {e}")
        return 1

    send_max = int(config.get('send_max_connection', 5))
    min_delay = float(config.get('send_connection_minimum_delay', 60))
    max_delay = float(config.get('send_connection_maximum_delay', 180))

    if max_delay < min_delay:
        min_delay, max_delay = max_delay, min_delay

    # Early exit if no eligible profiles (respecting verified filter) remain
    eligible_unsent = [p for p in profiles if not bool(p.get('sent_request')) and verified_matches(p.get('verified'), verified_choice)]
    if not eligible_unsent:
        log('INFO', 'No profiles to connect that match the current verified filter and are not already attempted (sent_request=true).')
        return 0

    # Apply headless preference via environment for login.py
    os.environ["HEADLESS"] = "1" if headless else "0"

    # Prepare driver (login)
    try:
        log('INFO', f"Launching browser (headless={headless}) and logging in...")
        driver = login_and_get_driver()
        log('INFO', "Logged in successfully.")
    except Exception as e:
        log('ERR', f"Login failed: {e}")
        return 1

    sent_count = 0
    processed = 0

    try:
        for idx, profile in enumerate(profiles):
            # Respect max connections sent
            if sent_count >= send_max:
                break

            # Skip if already marked sent_request
            if bool(profile.get('sent_request')):
                continue

            # Filter by verified choice
            if not verified_matches(profile.get('verified'), verified_choice):
                continue

            processed += 1

            status, message = process_profile(driver, profile)

            timestamp_now = datetime.now().isoformat(timespec='seconds')

            # Identify network-related errors that should NOT mark sent_request as true
            is_network_error = (
                status == 'skipped_error'
                and isinstance(message, str)
                and ('Connection aborted' in message or 'ConnectionResetError' in message)
            )

            # Identify specific 'Failed to confirm invite' error
            is_specific_confirm_error = (
                status == 'skipped_error'
                and isinstance(message, str)
                and 'Failed to confirm invite' in message
                and 'Unable to locate element' in message
                and ('/html/body/div[4]/div/div/div[3]/button[2]/span' in message or X_SEND_INVITE_CONFIRM_SPAN in message)
            )

            if is_network_error or is_specific_confirm_error:
                # For network errors or specific confirmation failures, do not mark as sent
                profile['sent_request'] = False
                profile['sent_request_timestamp'] = timestamp_now
                if is_specific_confirm_error:
                    # Sanitize the message for logging if it's the specific confirm error
                    message = 'Failed to confirm invite'
            else:
                # For successful sends, already connected, pending, and other errors, mark as sent
                profile['sent_request'] = True
                profile['sent_request_timestamp'] = timestamp_now

            # Persist after each profile to save progress
            try:
                save_json_file(SCRAPED_PATH, profiles)
            except Exception as e:
                log('WARN', f"Failed to persist update for profile index {idx}: {e}")

            # Map status to log kind
            kind_map = {
                'sent': 'SENT',
                'pending': 'PENDING',
                'already': 'ALREADY',
                'skipped_error': 'ERR',
            }
            kind = kind_map.get(status, 'INFO')
            log(kind, f"{profile.get('name', 'Unknown')} -> {message}")

            if status == 'sent':
                sent_count += 1
                # Delay only between sending actual requests
                if sent_count < send_max:
                    delay = random.uniform(min_delay, max_delay)
                    log('SLEEP', f"Sleeping for {delay:.1f}s before next connection...")
                    time.sleep(delay)

        log('INFO', f"Done. Sent: {sent_count} (max {send_max}). Profiles processed under filter: {processed}.")
        log('SLEEP', 'Waiting 15 seconds before closing the browser...')
        time.sleep(15)
        return 0
    finally:
        try:
            driver.quit()
            log('INFO', 'Browser closed.')
        except Exception:
            pass


if __name__ == '__main__':
    raise SystemExit(main())
