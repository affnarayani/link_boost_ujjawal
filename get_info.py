# get_info.py
# Log in using the reusable function from login.py, then scrape LinkedIn data
# from multiple pages using the provided XPaths. The browser remains open.
# Results are printed with colors (if colorama is installed) and saved as JSON
# to the repository root.

import json
import sys
import time
from datetime import datetime
from typing import Optional, Dict, Any

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

try:
    from colorama import init as colorama_init, Fore, Style
    colorama_init(autoreset=True)
    USE_COLOR = True
except Exception:
    # Fallback if colorama is not installed
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
    # Progress prints with flushing
    print(f"{Style.BRIGHT}{Fore.MAGENTA}[INFO]{Style.RESET_ALL} {msg}", flush=True)

# Toggle headless vs headful mode here
headless = True

from login import login_and_get_driver, LOGIN_URL, X_USERNAME, X_PASSWORD, X_REMEMBER_ME_LABEL, X_SIGN_IN_BUTTON

# Additional imports for headless driver and env handling
import os
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager


def _build_driver(headless_mode: bool) -> webdriver.Chrome:
    """Create a Chrome WebDriver. If headless_mode is True, run headless; else headful and maximized."""
    chrome_options = Options()

    if headless_mode:
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--disable-gpu")
    else:
        chrome_options.add_argument("--start-maximized")
        chrome_options.add_experimental_option("detach", True)

    chrome_options.add_argument("--log-level=3")  # Suppress verbose Chrome logs
    chrome_options.add_experimental_option("excludeSwitches", ["enable-logging"])  # Reduce console noise on Windows
    chrome_options.page_load_strategy = "eager"
    chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)

    if not headless_mode:
        try:
            driver.maximize_window()
        except Exception:
            pass

    return driver


def login_and_get_driver_respecting_cookie() -> webdriver.Chrome:
    """Login leveraging login.py's cookie/session logic, honoring headless/headful toggle.
    Returns a WebDriver session; caller must quit it.
    """
    # If headless: we can reuse login.py's logic by setting env var and calling its function
    # Else: same, but window will open maximized due to login.py behavior
    os.environ["HEADLESS"] = "1" if headless else "0"
    # Delegate to login.py to reuse cookies.json session if available
    return login_and_get_driver()


def get_text_safe(wait: WebDriverWait, xpath: str, timeout: int = 20) -> Optional[str]:
    """Wait for an element by XPath and return its visible text.
    Returns None if not found within timeout or on any error.
    """
    try:
        local_wait = WebDriverWait(wait._driver, timeout)
        el = local_wait.until(EC.presence_of_element_located((By.XPATH, xpath)))
        # innerText sometimes gives more stable text than .text
        txt = (el.get_attribute("innerText") or el.text or "").strip()
        return " ".join(txt.split()) if txt else None
    except Exception:
        return None


def open_and_wait(driver, url: str, ready_xpath: Optional[str] = None, timeout: int = 25):
    info(f"Opening: {url}")
    driver.get(url)
    wait = WebDriverWait(driver, timeout)
    if ready_xpath:
        try:
            wait.until(EC.presence_of_element_located((By.XPATH, ready_xpath)))
        except Exception:
            # Fallback: small delay in case the page is slow but renders slightly later
            time.sleep(2)
    else:
        time.sleep(1)
    return wait


def scrape_mynetwork(driver) -> Dict[str, Any]:
    info("Scraping: My Network")
    url = "https://www.linkedin.com/mynetwork/"
    wait = open_and_wait(driver, url)

    # Click the expand button to reveal additional My Network stats (if present)
    try:
        expand_xpath = '/html/body/div[1]/div[2]/div[2]/div[2]/div/main/div/div/div[1]/div/div/div/section[1]/div/div/section/div/div[2]/button/span'
        local_wait = WebDriverWait(driver, 8)
        expand_el = local_wait.until(EC.presence_of_element_located((By.XPATH, expand_xpath)))
        driver.execute_script("arguments[0].scrollIntoView({behavior:'instant', block:'center'});", expand_el)
        try:
            expand_el.click()
        except Exception:
            driver.execute_script("arguments[0].click();", expand_el)
        time.sleep(0.5)
    except Exception:
        # If not found or already expanded, continue scraping
        pass

    xpaths = {
        "invites_sent": '/html/body/div[1]/div[2]/div[2]/div[2]/div/main/div/div/div[1]/div/div/div/section[1]/div/div/section/div/div[1]/div/div/p[1]',
        "connections": '/html/body/div[1]/div[2]/div[2]/div[2]/div/main/div/div/div[1]/div/div/div/section[1]/div/div/section/div/div[1]/div/a[1]/div/p[1]',
        "following": '/html/body/div[1]/div[2]/div[2]/div[2]/div/main/div/div/div[1]/div/div/div/section[1]/div/div/section/div/div[1]/div/a[2]/div/p[1]',
        "groups": '/html/body/div[1]/div[2]/div[2]/div[2]/div/main/div/div/div[1]/div/div/div/section[1]/div/div/section/div/div[2]/div/a[1]/div/p[2]',
        "events": '/html/body/div[1]/div[2]/div[2]/div[2]/div/main/div/div/div[1]/div/div/div/section[1]/div/div/section/div/div[2]/div/a[2]/div/p[2]',
        "pages": '/html/body/div[1]/div[2]/div[2]/div[2]/div/main/div/div/div[1]/div/div/div/section[1]/div/div/section/div/div[2]/div/a[3]/div/p[2]',
        "newsletters": '/html/body/div[1]/div[2]/div[2]/div[2]/div/main/div/div/div[1]/div/div/div/section[1]/div/div/section/div/div[2]/div/a[4]/div/p[2]',
    }

    data = {}
    for key, xp in xpaths.items():
        data[key] = get_text_safe(wait, xp)

    return data


def scrape_invitations(driver) -> Dict[str, Any]:
    info("Scraping: Invitations")
    data = {}

    # Received invitations
    url_received = "https://www.linkedin.com/mynetwork/invitation-manager/received/"
    wait = open_and_wait(driver, url_received)
    raw_received = get_text_safe(
        wait,
        '/html/body/div[1]/div[2]/div[2]/div[2]/main/div/div/div[1]/section/div/div[2]/div/nav/ul/li/button/span/span',
    )
    # Only keep the numeric value from texts like "All (0)"
    try:
        import re as _re
        m = _re.search(r"\((\d+)\)", raw_received or "")
        if m:
            data["received_invitations"] = m.group(1)
        else:
            m2 = _re.search(r"\d+", raw_received or "")
            data["received_invitations"] = m2.group(0) if m2 else raw_received
    except Exception:
        data["received_invitations"] = raw_received

    # Sent invitations
    url_sent = "https://www.linkedin.com/mynetwork/invitation-manager/sent/"
    wait = open_and_wait(driver, url_sent)
    raw_sent = get_text_safe(
        wait,
        '/html/body/div[1]/div[2]/div[2]/div[2]/main/div/div/div[1]/section/div/div[2]/div/nav/ul/li/button/span/span',
    )
    # Default to "0" if the element is missing or empty
    if not raw_sent:
        data["sent_invitations"] = "0"
    else:
        # Only keep the numeric value from texts like "People (6)"
        try:
            import re as _re
            m = _re.search(r"\((\d+)\)", raw_sent or "")
            if m:
                data["sent_invitations"] = m.group(1)
            else:
                m2 = _re.search(r"\d+", raw_sent or "")
                data["sent_invitations"] = m2.group(0) if m2 else "0"
        except Exception:
            data["sent_invitations"] = "0"

    return data


def scrape_dashboard(driver) -> Dict[str, Any]:
    """Scrape dashboard metrics using label-based lookup to avoid brittle absolute XPaths.
    If metrics are missing, save the HTML for debugging and try a fallback URL.
    """
    import re

    info("Scraping: Dashboard")

    def _open(url: str):
        # Wait for <main> to be present as a generic ready signal
        return open_and_wait(driver, url, ready_xpath='//main')

    def _extract_number_from_container(container) -> Optional[str]:
        """Extract a numeric metric text from a nearby element, avoiding date-like strings.
        Preference order:
        1) Texts that are purely numbers (with optional separators/suffixes like k/M/%),
        2) Texts containing numbers but without date words,
        3) Any text containing numbers (fallback).
        """
        import re as _re  # local alias to be explicit inside nested scope

        # Day and month names to filter out date-like strings
        date_words = {
            "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
            "january", "february", "march", "april", "may", "june", "july", "august",
            "september", "october", "november", "december",
            "today", "yesterday", "week", "month", "year"
        }

        # A "pure metric" looks like a number possibly with separators and a suffix
        metric_full_re = _re.compile(r"^\s*(\d[\d,.]*\s*[kKmM%]?)\s*$")
        metric_any_re = _re.compile(r"(\d[\d,.]*\s*[kKmM%]?)")

        candidates = container.find_elements(
            By.XPATH,
            ".//*[self::p or self::span or self::strong or self::h1 or self::h2 or self::h3]"
        )

        texts: list[str] = []
        for c in candidates:
            try:
                raw = (c.get_attribute("innerText") or c.text or "").strip()
                if not raw or not _re.search(r"\d", raw):
                    continue
                norm = " ".join(raw.split())
                texts.append(norm)
            except Exception:
                continue

        # 1) Exact metric-only first
        for t in texts:
            m = metric_full_re.match(t)
            if m:
                return m.group(1)

        # 2) Filter out anything with date words; prefer densest digits / shortest text
        no_date = [t for t in texts if not any(w in t.lower() for w in date_words)]
        if no_date:
            def score(s: str) -> tuple[int, int]:
                digits = sum(ch.isdigit() for ch in s)
                return (-digits, len(s))  # more digits, then shorter text

            no_date.sort(key=score)
            m = metric_any_re.search(no_date[0])
            return m.group(1) if m else no_date[0]

        # 3) No valid metric without date words found — avoid pulling day number from dates
        return None

    def _find_metric_by_labels(keywords) -> Optional[str]:
        # Search for any element under <main> containing the keyword text, then read a number from the closest nearby element
        # Heuristic: number is usually a sibling just above the label; if not, fall back to the enclosing card/container.
        def _extract_metric_near_label(label_el) -> Optional[str]:
            # 1) Immediate preceding sibling (most common layout: number above label)
            try_paths = [
                "./preceding-sibling::*[self::p or self::span or self::strong][1]",
                "./following-sibling::*[self::p or self::span or self::strong][1]",
            ]
            for xp in try_paths:
                try:
                    els = label_el.find_elements(By.XPATH, xp)
                    if els:
                        num = _extract_number_from_container(els[0])
                        if num:
                            return num
                except Exception:
                    pass

            # 2) Consider parent's preceding sibling block (e.g., wrapper div then label)
            try:
                parent = label_el.find_element(By.XPATH, "./parent::*")
                sibs = parent.find_elements(By.XPATH, "preceding-sibling::*[self::div or self::section][1]")
                if sibs:
                    num = _extract_number_from_container(sibs[0])
                    if num:
                        return num
            except Exception:
                pass

            return None

        for kw in keywords:
            try:
                els = driver.find_elements(
                    By.XPATH,
                    f"//main//*[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{kw.lower()}')]"
                )
                for el in els:
                    # 1) Try to extract from the immediate neighborhood
                    try:
                        near_num = _extract_metric_near_label(el)
                        if near_num:
                            return near_num
                    except Exception:
                        pass

                    # 2) Fallback: use the closest container (a/section/div)
                    try:
                        container = el.find_element(By.XPATH, "./ancestor::*[self::a or self::section or self::div][1]")
                        num = _extract_number_from_container(container)
                        if num:
                            return num
                    except Exception:
                        continue
            except Exception:
                continue
        return None

    def _scrape_current_page() -> Dict[str, Any]:
        # Nudge page to trigger lazy loading
        try:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(0.8)
            driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(0.4)
        except Exception:
            pass

        # Desired labels
        labels_map = {
            "post_impressions": ["post impressions", "impressions"],
            "followers": ["followers"],
            "profile_viewers": ["profile viewers", "profile views"],
            "search_appearances": ["search appearances", "search appearance"],
            "posts": ["posts"],
            "comments": ["comments"],
        }

        data_local: Dict[str, Any] = {k: None for k in labels_map.keys()}

        # 1) Try to parse embedded JSON blocks (<code> tags) that contain dashboard data
        try:
            html = driver.page_source
            import re as _re, json as _json
            # Extract JSON objects from <code> ... </code>
            code_blocks = _re.findall(r"<code[^>]*>(\s*\{.*?\})\s*</code>", html, flags=_re.DOTALL)
            for blk in code_blocks:
                try:
                    obj = _json.loads(blk)
                except Exception:
                    continue
                data = (obj.get("data", {}) or {}).get("data", {})
                dash = data.get("feedDashCreatorExperienceDashboard")
                if not dash:
                    continue

                sections = dash.get("section", [])
                for sec in sections:
                    analytics = sec.get("analyticsSection")
                    if analytics:
                        for p in analytics.get("analyticsPreviews", []):
                            label = ((p.get("description", {}) or {}).get("text", "") or "").strip().lower()
                            val = ((p.get("analyticsTitle", {}) or {}).get("text", "") or "").strip()
                            if not val:
                                continue
                            if "post impressions" in label or "impressions" in label:
                                data_local["post_impressions"] = val
                            elif "followers" in label:
                                data_local["followers"] = val
                            elif "profile viewers" in label or "profile views" in label:
                                data_local["profile_viewers"] = val
                            elif "search appearances" in label or "search appearance" in label:
                                data_local["search_appearances"] = val

                    weekly = sec.get("weeklySharingGoalSection")
                    if weekly:
                        for wm in weekly.get("weeklyActivityMetrics", []):
                            wtype = wm.get("weeklyActivityType")
                            wval = wm.get("value")
                            if wtype == "POSTS":
                                data_local["posts"] = str(wval)
                            elif wtype == "COMMENTS":
                                data_local["comments"] = str(wval)

                # If we extracted anything, we can stop scanning further blocks
                if any(v is not None for v in data_local.values()):
                    break
        except Exception:
            pass

        # 2) Fill any missing slots with the heuristic label-based DOM approach
        for key, labels in labels_map.items():
            if not data_local.get(key):
                data_local[key] = _find_metric_by_labels(labels)

        return data_local

    # 1) Try the original dashboard URL
    _open("https://www.linkedin.com/dashboard/")
    data = _scrape_current_page()

    # 2) If most values are missing, try an alternative analytics URL
    missing = [k for k, v in data.items() if not v]
    if len(missing) >= 4:
        _open("https://www.linkedin.com/analytics/creator/")
        data = _scrape_current_page()
        missing = [k for k, v in data.items() if not v]

    # 3) Skipping HTML dump per request — do not create debug_dashboard.html
    if missing:
        info("Dashboard metrics missing; HTML dump skipped.")

    return data


def _parse_growth(container) -> dict:
    """Extract numeric growth value and infer direction from container.
    Returns dict with keys: raw, value, direction, signed.
    """
    # Locate the number element inside the metric card
    try:
        num_el = container.find_element(By.XPATH, ".//span/strong")
    except Exception:
        return {"raw": None, "value": None, "direction": None, "signed": None}

    raw = (num_el.get_attribute("innerText") or num_el.text or "").strip()

    # 1) Check explicit sign in the raw text
    direction = None
    if raw.startswith(("+", "＋")):
        direction = "up"
    elif raw.startswith(("-", "−", "—", "–")):
        direction = "down"

    # 2) Check nearby attributes/text/icons for hints
    if not direction:
        nearby = " ".join(filter(None, [
            container.get_attribute("aria-label") or "",
            container.get_attribute("title") or "",
            container.get_attribute("innerText") or "",
        ])).lower()
        if any(w in nearby for w in ("increase", "increased", "up")):
            direction = "up"
        elif any(w in nearby for w in ("decrease", "decreased", "down")):
            direction = "down"
        elif any(sym in nearby for sym in ("▲", "▴", "↑", "↗")):
            direction = "up"
        elif any(sym in nearby for sym in ("▼", "▾", "↓", "↘")):
            direction = "down"

    # 3) Fallback: color heuristic (theme-dependent; best effort)
    if not direction:
        try:
            import re
            color = num_el.value_of_css_property("color")  # e.g., rgba(0, 128, 0, 1)
            m = re.search(r"rgba?\((\d+),\s*(\d+),\s*(\d+)", color)
            if m:
                r, g, b = map(int, m.groups())
                if g > r + 20:
                    direction = "up"
                elif r > g + 20:
                    direction = "down"
        except Exception:
            pass

    # Normalize numeric value (strip sign, keep %)
    import re as _re
    num_only = None
    m = _re.search(r"[+\-−]?\s*(\d[\d,\.]*\s*%?)", raw)
    if m:
        num_only = m.group(1).replace(" ", "")

    # Build signed representation
    signed = None
    if num_only:
        if direction == "up" and not raw.strip().startswith("-"):
            signed = f"+{num_only}"
        elif direction == "down" and not raw.strip().startswith("+"):
            signed = f"-{num_only}"
        else:
            if raw.strip().startswith(("+", "-", "−")):
                signed = raw.strip()
            else:
                signed = num_only

    return {"raw": raw, "value": num_only, "direction": direction, "signed": signed}


def scrape_growth(driver) -> Dict[str, Any]:
    info("Scraping: Growth")
    url = "https://www.linkedin.com/dashboard/"

    # Use the container cards for each metric
    containers = {
        "post_impression": "/html/body/div[6]/div[3]/div[2]/div/div/main/div/section[1]/div/a[1]/section",
        "followers": "/html/body/div[6]/div[3]/div[2]/div/div/main/div/section[1]/div/a[2]/section",
    }

    max_retries = 15  # Retry up to 10 times if growth is N/A
    for attempt in range(max_retries):
        if attempt > 0:
            info(f"Retrying growth scrape (attempt {attempt + 1}/{max_retries})")
            # Refresh the page
            driver.refresh()
            time.sleep(3)  # Wait for page to reload
            wait = WebDriverWait(driver, 25)
            try:
                wait.until(EC.presence_of_element_located((By.XPATH, '//main')))
            except Exception:
                pass  # Continue even if main not found
        else:
            wait = open_and_wait(driver, url, ready_xpath='//main')

        time.sleep(5)  # Wait 5 seconds after page load before finding growth analytics data
        data: Dict[str, Any] = {}
        all_na = True  # Flag to check if all growth values are N/A
        for key, xp in containers.items():
            try:
                container = WebDriverWait(wait._driver, 15).until(
                    EC.presence_of_element_located((By.XPATH, xp))
                )
                parsed = _parse_growth(container)
                # Extended keys
                data[f"{key}_growth_value"] = parsed["value"]
                data[f"{key}_growth_direction"] = parsed["direction"]
                data[f"{key}_growth_signed"] = parsed["signed"]
                # Backward-compatible keys used by pretty_print
                if key == "post_impression":
                    data["post_impression_growth"] = parsed["signed"] or parsed["value"] or parsed["raw"]
                elif key == "followers":
                    data["followers_growth"] = parsed["signed"] or parsed["value"] or parsed["raw"]
                # Check if this is actual data (not N/A)
                if parsed["raw"] and parsed["raw"] != "N/A" and parsed["value"]:
                    all_na = False
            except Exception:
                if key == "post_impression":
                    data["post_impression_growth"] = None
                elif key == "followers":
                    data["followers_growth"] = None
                data[f"{key}_growth_value"] = None
                data[f"{key}_growth_direction"] = None
                data[f"{key}_growth_signed"] = None

        # If we have actual data (not all N/A), return it
        if not all_na:
            return data

        # If all are N/A and this is not the last attempt, continue to retry
        if attempt < max_retries - 1:
            time.sleep(5)  # Short delay before retry

    # After all retries, return the last data (which is N/A)
    return data


def pretty_print(data: Dict[str, Any]):
    def section(title: str):
        print(f"{Style.BRIGHT}{Fore.CYAN}\n=== {title} ==={Style.RESET_ALL}")

    def kv(label: str, value: Any):
        v = value if value is not None else "N/A"
        print(f"{Fore.GREEN}{label}: {Fore.YELLOW}{v}{Style.RESET_ALL}")

    section("My Network")
    for k in ["invites_sent", "connections", "following", "groups", "events", "pages", "newsletters"]:
        kv(k.replace("_", " ").title(), data.get("mynetwork", {}).get(k))

    section("Invitations")
    kv("Received Invitations", data.get("invitations", {}).get("received_invitations"))
    kv("Sent Invitations", data.get("invitations", {}).get("sent_invitations"))

    section("Dashboard")
    for k in ["post_impressions", "followers", "profile_viewers", "search_appearances", "posts", "comments"]:
        kv(k.replace("_", " ").title(), data.get("dashboard", {}).get(k))

    section("Growth")
    kv("Post Impression Growth", data.get("growth", {}).get("post_impression_growth"))
    kv("Followers Growth", data.get("growth", {}).get("followers_growth"))


def save_json(data: Dict[str, Any], path: str):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main() -> int:
    driver = None
    try:
        mode_txt = "headless" if headless else "headful"
        info(f"Launching {mode_txt} browser and logging in…")
        driver = login_and_get_driver_respecting_cookie()  # Respects cookies.json and headless toggle
        info("Logged in. Starting scraping…")

        # Scrape all sections
        mynetwork = scrape_mynetwork(driver)
        info("My Network scraped.")
        invitations = scrape_invitations(driver)
        info("Invitations scraped.")
        dashboard = scrape_dashboard(driver)
        info("Dashboard scraped.")
        growth = scrape_growth(driver)
        info("Growth scraped.")

        result = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "mynetwork": mynetwork,
            "invitations": invitations,
            "dashboard": dashboard,
            "growth": growth,
        }

        # Pretty print with colors
        pretty_print(result)

        # Save JSON to repo root (relative path)
        out_path = os.path.join(os.path.dirname(__file__), "linkedin_info.json")
        save_json(result, out_path)
        print(f"\n{Fore.MAGENTA}{Style.BRIGHT}Saved JSON to: {out_path}{Style.RESET_ALL}", flush=True)

        return 0

    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        return 1
    finally:
        # Ensure the browser is closed after task completion
        try:
            if driver:
                driver.quit()
                info("Browser closed.")
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())