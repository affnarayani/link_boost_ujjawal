# withdraw_connections.py
# Withdraws LinkedIn connection requests based on timing and state rules.
# - Reads withdraw_connection_days_after_sending from config.json
# - For each profile in scraped_connections.json where sent_request==true AND no 'withdraw' key yet,
#   if now - sent_request_timestamp >= configured days, then attempt to withdraw.
# - Checks the provided XPaths and behaviors exactly as requested.
# - Respects withdraw_connection_minimum_delay / withdraw_connection_maximum_delay (if present)
#   and withdraw_max_connection (if present) from scraped_connections.json (top-level settings if dict).
# - Writes "withdraw": true/false (boolean) directly under "sent_request_timestamp" in each profile.
# - Prints logs in the same [INFO] style used in get_info.py and closes the browser at the end.

from __future__ import annotations

# Headless mode toggle: set True for headless, False for visible (maximized)
headless = True

import json
import os
import random
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

# Console output styling similar to get_info.py
try:
    from colorama import init as colorama_init, Fore, Style
    colorama_init(autoreset=True)
    USE_COLOR = True
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
    USE_COLOR = False


def info(msg: str):
    print(f"{Style.BRIGHT}{Fore.MAGENTA}[INFO]{Style.RESET_ALL} {msg}", flush=True)


# Selenium imports
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# Login helper from login.py
try:
    from login import login_and_get_driver  # type: ignore
except Exception as e:
    print("ERROR: Unable to import login.login_and_get_driver. Ensure login.py exists and is valid.", file=sys.stderr)
    raise

# Absolute XPaths provided in spec
X_WITHDRAW_DIALOG = '//*[@id="dialog-label-st8"]'
X_WITHDRAW_CONFIRM_SPAN = '/html/body/div[4]/div/div/div[3]/button[2]/span'

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
    os.replace(tmp_path, path)


def load_config(path: str) -> Dict[str, Any]:
    """Merge list of dicts or accept dict, similar to make_connections.py"""
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


def parse_iso_timestamp(ts: str) -> datetime:
    # Accept timestamps like 2025-09-18T12:18:12
    # Treat as naive local time; compare in naive datetime for simplicity
    return datetime.fromisoformat(ts)


def days_since(ts: str) -> float:
    try:
        dt = parse_iso_timestamp(ts)
    except Exception:
        return float('inf')  # if invalid, treat as very old to avoid blocking withdrawals
    now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
    delta = now - dt
    return delta.total_seconds() / 86400.0


def add_key_after(original: Dict[str, Any], after_key: str, new_key: str, new_value: Any) -> Dict[str, Any]:
    """Return a new dict preserving order, inserting new_key immediately after 'after_key'."""
    out: Dict[str, Any] = {}
    inserted = False
    for k, v in original.items():
        out[k] = v
        if k == after_key and not inserted:
            out[new_key] = new_value
            inserted = True
    if not inserted:
        out[new_key] = new_value
    return out


def get_withdraw_settings_from_scraped(scraped: Any) -> Tuple[float, float, int]:
    """Attempt to read withdraw delays and max from scraped_connections.json if present.
    Returns (min_delay_sec, max_delay_sec, max_count).
    If not present, returns defaults: (60.0, 180.0, 5).

    Expected placement: top-level dict with keys, or special entry with those keys.
    Current file is a list of profiles, so typically not present; we gracefully default.
    """
    min_delay = 60.0
    max_delay = 180.0
    max_count = 5

    # If scraped is a dict, try top-level keys
    if isinstance(scraped, dict):
        try:
            if 'withdraw_connection_minimum_delay' in scraped:
                min_delay = float(scraped.get('withdraw_connection_minimum_delay', min_delay))
            if 'withdraw_connection_maximum_delay' in scraped:
                max_delay = float(scraped.get('withdraw_connection_maximum_delay', max_delay))
            if 'withdraw_max_connection' in scraped:
                max_count = int(scraped.get('withdraw_max_connection', max_count))
        except Exception:
            pass
        return min_delay, max_delay, max_count

    # If list, some users may include a trailing dict with settings; scan for it
    if isinstance(scraped, list):
        for item in scraped:
            if isinstance(item, dict) and (
                'withdraw_connection_minimum_delay' in item or
                'withdraw_connection_maximum_delay' in item or
                'withdraw_max_connection' in item
            ):
                try:
                    if 'withdraw_connection_minimum_delay' in item:
                        min_delay = float(item.get('withdraw_connection_minimum_delay', min_delay))
                    if 'withdraw_connection_maximum_delay' in item:
                        max_delay = float(item.get('withdraw_connection_maximum_delay', max_delay))
                    if 'withdraw_max_connection' in item:
                        max_count = int(item.get('withdraw_max_connection', max_count))
                except Exception:
                    pass
                break

    # Ensure min<=max
    if max_delay < min_delay:
        min_delay, max_delay = max_delay, min_delay

    return min_delay, max_delay, max_count


def find_pending_span_exact(driver, timeout: int = 10):
    """Find the exact Pending span using XPaths with div[i] where i from 1 to 9.
    Returns the element or None if not found within timeout.
    """
    end_time = time.time() + max(0, timeout)
    while time.time() < end_time:
        for i in range(1, 10):
            xpath = f'/html/body/div[{i}]/div[3]/div/div/div[2]/div/div/main/section[1]/div[2]/div[3]/div/button/span'
            elems = driver.find_elements(By.XPATH, xpath)
            if elems:
                return elems[0]
        time.sleep(0.3)
    return None


def find_more_button(driver, timeout: int = 10):
    """Find the More button span using XPaths with div[i] where i from 1 to 9.
    Returns True if found with text 'More', else False.
    """
    end_time = time.time() + max(0, timeout)
    while time.time() < end_time:
        for i in range(1, 10):
            xpath = f'/html/body/div[{i}]/div[3]/div/div/div[2]/div/div/main/section[1]/div[2]/div[3]/div/div[2]/button/span'
            elems = driver.find_elements(By.XPATH, xpath)
            for elem in elems:
                if (elem.text or '').strip().lower() == 'more':
                    return True
        time.sleep(0.3)
    return False


def click_parent_button_of_span(span_el) -> None:
    try:
        button_el = span_el.find_element(By.XPATH, "..")
        button_el.click()
    except Exception:
        span_el.click()


def process_withdraw(driver, profile: Dict[str, Any]) -> Tuple[bool, str]:
    """Attempt to withdraw one profile.
    Returns (did_withdraw, message).
    If Pending span not found or different text, returns (False, reason) and caller will mark withdraw=False.
    """
    url = profile.get('profile_url')
    if not url:
        return False, 'Missing profile_url'

    driver.get(url)
    # Wait 5 seconds after page load before starting to search for xpath
    time.sleep(5.0)
    wait = WebDriverWait(driver, 12)

    # Try to find the exact Pending span
    span_el = find_pending_span_exact(driver, timeout=10)
    if not span_el or not (span_el.text or '').strip():
        return False, 'Pending span not found or no text in it'

    label = (span_el.text or '').strip()
    if label.lower() != 'pending':
        return False, f"Primary action is {label!r} (not 'Pending')"

    # Click the Pending button (parent)
    try:
        click_parent_button_of_span(span_el)
    except Exception as e:
        return False, f'Failed to click Pending button: {e}'

    # Wait for withdraw dialog
    try:
        wait.until(EC.presence_of_element_located((By.XPATH, X_WITHDRAW_DIALOG)))
        # Wait random 5-15 seconds before clicking confirm
        time.sleep(random.uniform(5, 15))
    except Exception:
        # Even if not found, attempt to click confirm per spec (it might still be present)
        pass

    # Click the confirm withdraw button
    try:
        confirm_span = wait.until(EC.element_to_be_clickable((By.XPATH, X_WITHDRAW_CONFIRM_SPAN)))
        click_parent_button_of_span(confirm_span)
    except Exception:
        try:
            confirm_span = driver.find_element(By.XPATH, X_WITHDRAW_CONFIRM_SPAN)
            confirm_span.click()
        except Exception as inner_exc:
            return False, f'Failed to confirm withdraw: {inner_exc}'

    return True, 'Withdrawn successfully'


def main() -> int:
    # Load config and data
    try:
        config = load_config(CONFIG_PATH)
    except Exception as e:
        info(f"Unable to read config.json: {e}")
        return 1

    try:
        scraped_data = load_json_file(SCRAPED_PATH)
    except Exception as e:
        info(f"Unable to read scraped_connections.json: {e}")
        return 1

    if not isinstance(scraped_data, list):
        info("scraped_connections.json must be a list of profiles")
        return 1

    # Threshold days from config
    withdraw_after_days = int(config.get('withdraw_connection_days_after_sending', 7))

    # Delays and max from scraped (if present); otherwise defaults
    min_delay, max_delay, withdraw_max = get_withdraw_settings_from_scraped(scraped_data)
    # Override withdraw_max_connection from config if present (must respect this value)
    try:
        withdraw_max = int(config.get('withdraw_max_connection', withdraw_max))
    except Exception:
        pass

    # Compute eligible profiles
    eligible_indices: List[int] = []
    for idx, profile in enumerate(scraped_data):
        if not isinstance(profile, dict):
            continue
        # Must have sent_request true
        if not bool(profile.get('sent_request')):
            continue
        # Skip if withdraw key already set (true or false)
        if 'withdraw' in profile:
            continue
        # Must have timestamp
        ts = profile.get('sent_request_timestamp')
        if not ts:
            continue
        # Check elapsed days
        try:
            elapsed_days = days_since(ts)
        except Exception:
            elapsed_days = float('inf')
        if elapsed_days < withdraw_after_days:
            continue
        eligible_indices.append(idx)

    if not eligible_indices:
        info('No more profiles left to withdraw connection.')
        return 0

    # Apply headless preference via environment for login.py using the toggle above
    os.environ["HEADLESS"] = "1" if headless else "0"

    # Prepare driver (login)
    try:
        info("Launching browser and logging in...")
        driver = login_and_get_driver()
        # Ensure browser is maximized when running headful
        if not headless:
            try:
                driver.maximize_window()
            except Exception:
                pass
        info("Logged in successfully.")
    except Exception as e:
        info(f"Login failed: {e}")
        return 1

    withdrawn_count = 0

    try:
        for idx in eligible_indices:
            if withdrawn_count >= withdraw_max:
                break

            profile = scraped_data[idx]
            name = profile.get('name', 'Unknown')

            did_withdraw, message = process_withdraw(driver, profile)

            if not did_withdraw and message == 'Pending span not found or no text in it':
                # Check for More button before exiting
                if find_more_button(driver, timeout=10):
                    info(f"{name} -> Pending span not found, but More button found. Marked withdraw = false and skipped.")
                else:
                    info(f"{name} -> Pending span not found and no More button. Exiting.")
                    return 1
            elif not did_withdraw:
                info(f"{name} -> {message}. Marked withdraw = false and skipped.")
            else:
                withdrawn_count += 1
                info(f"{name} -> {message}")
                # Delay between successful withdrawals if more remaining
                if withdrawn_count < withdraw_max:
                    delay = random.uniform(min_delay, max_delay)
                    info(f"Sleeping for {delay:.1f}s before next withdraw...")
                    time.sleep(delay)

            # Insert withdraw key immediately after sent_request_timestamp
            withdraw_value = True if did_withdraw else False
            profile_updated = add_key_after(profile, 'sent_request_timestamp', 'withdraw', withdraw_value)
            scraped_data[idx] = profile_updated

            # Persist after each profile
            try:
                save_json_file(SCRAPED_PATH, scraped_data)
            except Exception as e:
                info(f"Warning: failed to persist update for {name}: {e}")

        info(f"Done. Withdrawn: {withdrawn_count} (max {withdraw_max}).")
        return 0
    finally:
        try:
            # Keep a 15s delay between last task and closing the browser
            time.sleep(15.0)
            driver.quit()
            info('Browser closed.')
        except Exception:
            pass


if __name__ == '__main__':
    raise SystemExit(main())
