# post_comments.py
# Logs into LinkedIn using login.py, opens the feed page,
# parses posts that have a Comment button, prints them in the same style as get_info.py,
# and leaves the browser open (testing).

import os
import sys
import time
import re
import json
import random
import shutil
from typing import List, Optional, Any
from google import genai

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains

try:
    from colorama import init as colorama_init, Fore, Style
    colorama_init(autoreset=True)
except Exception:
    class Fore:
        GREEN = ""; YELLOW = ""; RED = ""; CYAN = ""; MAGENTA = ""; BLUE = ""
    class Style:
        BRIGHT = ""; RESET_ALL = ""

# Reuse login from login.py
from login import login_and_get_driver

# Developer toggles: set to True/False to enable/disable features
like = True      # Toggle to enable/disable liking
comment = True   # Toggle to enable/disable commenting

# Browser mode toggle (default: headful)
HEADLESS = True

FEED_URL = "https://www.linkedin.com/feed/"

def banner(msg: str) -> None:
    print(f"{Style.BRIGHT}{Fore.CYAN}=== {msg} ==={Style.RESET_ALL}")

def step(n: int, msg: str) -> None:
    print(f"{Fore.BLUE}{Style.BRIGHT}[STEP {n}] {msg}{Style.RESET_ALL}")

def info(msg: str) -> None:
    print(f"{Fore.CYAN}ℹ {msg}{Style.RESET_ALL}")

def success(msg: str) -> None:
    print(f"{Fore.GREEN}✔ {msg}{Style.RESET_ALL}")

def warn(msg: str) -> None:
    print(f"{Fore.YELLOW}⚠ {msg}{Style.RESET_ALL}")

def error(msg: str) -> None:
    print(f"{Fore.RED}✖ {msg}{Style.RESET_ALL}")

def load_config(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        cfg = {}
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    cfg.update(item)
        elif isinstance(data, dict):
            cfg = data
        return cfg
    except Exception:
        return {}


def clean_model_comment(text: str) -> str:
    s = (text or "").strip()
    # Remove common headings/labels and markdown
    s = re.sub(r"^\s*Gemini\s*Comment\s*:\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"^\s*Here.*?comment.*?:\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"^\s*Task\s*\d+\s*:\s*.*?\n+", "", s, flags=re.IGNORECASE)
    s = re.sub(r"^\s*\*\*(.*?)\*\*\s*", "", s)  # drop leading bold heading
    # Strip surrounding quotes/backticks
    s = s.strip().strip("\"'`").strip()
    # Collapse whitespace
    s = re.sub(r"\s+", " ", s).strip()
    return s


def pretty_print_posts_with_comments(posts: List[tuple[str, Optional[str], Optional[str]]], start_index: int = 1, show_link: bool = True):
    # Production-friendly structured logging for post/comment output
    if not posts:
        info("No posts with a Comment button found in the current view.")
        return
    for idx, (post, comment, link) in enumerate(posts, start_index):
        info(f"Post {idx}:")
        info(post)
        info("Gemini Comment:")
        info(comment if comment else "")
        if show_link:
            info(f"Link: {link or ''}")
        info("------------------------------------------------------------------------")


# Processed posts tracking helpers

def _load_liked_commented(path: str) -> list:
    try:
        if not os.path.exists(path):
            return []
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
            if not content.strip():
                return []
            data = json.loads(content)
            if isinstance(data, list):
                return data
            return []
    except Exception:
        return []


def _prepend_post_link(path: str, link: str) -> bool:
    """Prepend a post link to the JSON list at the top. Returns True if added, False if skipped."""
    try:
        if not link:
            return False
        # Validate post_link format
        if not re.match(r"^https://www\.linkedin\.com/feed/update/urn:li:activity:\d+$", link):
            warn(f"Skipping invalid post link format: {link}")
            return False
        arr = _load_liked_commented(path)
        # Skip if already present
        for item in arr:
            if isinstance(item, dict) and item.get("post_link") == link:
                return False
        new_arr = [{"post_link": link}] + arr
        with open(path, "w", encoding="utf-8") as f:
            json.dump(new_arr, f, ensure_ascii=False, indent=4)
        return True
    except Exception:
        return False


def main() -> int:
    banner("LinkedIn Like and Comment Bot")

    # Honor HEADLESS variable by setting the env var used by login.py
    os.environ["HEADLESS"] = "1" if HEADLESS else "0"

    driver = None

    # Resolve repo root and temp directory early
    repo_root = os.path.dirname(__file__)
    temp_dir = os.path.join(repo_root, "temp")

    # 1) Clear temp folder at start
    step(1, "Clearing temp folder")
    try:
        if os.path.isdir(temp_dir):
            for name in os.listdir(temp_dir):
                path = os.path.join(temp_dir, name)
                try:
                    if os.path.isfile(path) or os.path.islink(path):
                        os.remove(path)
                    elif os.path.isdir(path):
                        shutil.rmtree(path, ignore_errors=True)
                except Exception:
                    pass
        else:
            os.makedirs(temp_dir, exist_ok=True)
        success("Temp folder cleared.")
    except Exception as e:
        error(f"Failed to clear temp folder: {e}")
        return 1 # Exit on critical error

    try:
        # 2) Login and launch browser
        step(2, "Logging in and launching browser")
        driver = login_and_get_driver()
        success("Driver ready")

        # 3) Open LinkedIn feed
        step(3, "Opening LinkedIn feed")
        driver.get(FEED_URL)

        # Wait for <main> to be present as a generic ready signal
        wait = WebDriverWait(driver, 25)
        try:
            wait.until(EC.presence_of_element_located((By.TAG_NAME, "main")))
            success("Feed loaded")
        except Exception:
            time.sleep(2)
            warn("Main element not found quickly, proceeding after small delay.")

        # Wait for 15 seconds for dynamic content to load
        step(4, "Waiting 15 seconds for dynamic content to load")
        time.sleep(15)
        success("Dynamic content wait complete.")

        # Optional: small delay to allow first posts to render
        time.sleep(2)

        # Refocus the website by pressing TAB 13 times with a 3-second interval
        step(5, "Refocusing website with TAB key presses")
        actions = ActionChains(driver)
        for i in range(13):
            actions.send_keys(Keys.TAB).pause(3)
            info(f"Pressed TAB {i+1}/13 times.")
        actions.perform()
        success("Website refocused.")

        # Perform scrolling using Page Down action keys
        step(6, "Performing scrolling with Page Down key")
        actions = ActionChains(driver)
        # Scroll down a few times to load more content
        for _ in range(5): # Scroll down 5 times as an example
            actions.send_keys(Keys.PAGE_DOWN).pause(1)
        actions.perform()
        success("Scrolling with Page Down complete.")

        # Prefer analyzing live DOM (more reliable than static HTML)
        def collect_posts_via_dom(max_posts: int = 25, existing_links: set = None) -> list[dict[str, Any]]:
            results: list[dict[str, Any]] = []
            if existing_links is None:
                existing_links = set()
            if existing_links is None:
                existing_links = set()

            def norm_text(s: str) -> str:
                return re.sub(r"\s+", " ", (s or "").strip())

            # Attempt a few scrolls to load posts
            for _ in range(3):
                try:
                    driver.execute_script("window.scrollBy(0, document.body.scrollHeight/3);")
                except Exception:
                    pass
                time.sleep(1.2)

            # Iterate through potential post indices (1 to 15)
            for i in range(1, 16):
                try:
                    # Base XPath for the post container
                    post_xpath = f"/html[1]/body[1]/div[1]/div[2]/div[2]/div[2]/div[1]/main[1]/div[1]/div[1]/div[2]/div[1]/div[{i}]"
                    post = driver.find_element(By.XPATH, post_xpath)

                    # Check for sponsored/promoted content
                    sponsored_promoted_xpath = f"/html[1]/body[1]/div[1]/div[2]/div[2]/div[2]/div[1]/main[1]/div[1]/div[1]/div[2]/div[1]/div[{i}]/div[1]/div[1]/div[1]/div[1]/div[1]/div[1]/div[1]"
                    try:
                        sponsored_promoted_text_el = driver.find_element(By.XPATH, sponsored_promoted_xpath)
                        if re.search(r"(?i)\b(Promoted|Sponsored)\b", sponsored_promoted_text_el.text):
                            warn(f"Skipping sponsored/promoted post at index {i}.")
                            continue
                    except Exception:
                        pass # Not sponsored/promoted, continue

                    # Check for comment button
                    comment_btn_xpath = f"/html[1]/body[1]/div[1]/div[2]/div[2]/div[2]/div[1]/main[1]/div[1]/div[1]/div[2]/div[1]/div[{i}]/div[1]/div[1]/div[1]/div[1]/div[1]/div[5]/button[1]/span[1]"
                    try:
                        comment_btn = driver.find_element(By.XPATH, comment_btn_xpath)
                        if not comment_btn.is_displayed() or not comment_btn.is_enabled():
                            warn(f"Skipping post at index {i} due to unavailable comment button.")
                            continue
                    except Exception:
                        warn(f"Skipping post at index {i} as comment button not found.")
                        continue

                    # Extract post content
                    text_val: Optional[str] = None
                    try:
                        # First try the initial span for content
                        initial_content_xpath = f"/html[1]/body[1]/div[1]/div[2]/div[2]/div[2]/div[1]/main[1]/div[1]/div[1]/div[2]/div[1]/div[{i}]/div[1]/div[1]/div[1]/div[1]/div[1]/p[1]/span[1]"
                        initial_content_el = driver.find_element(By.XPATH, initial_content_xpath)
                        text_val = norm_text(initial_content_el.text)

                        # Check for "more" button and click if present
                        more_button_xpath = f"/html[1]/body[1]/div[1]/div[2]/div[2]/div[2]/div[1]/main[1]/div[1]/div[1]/div[2]/div[1]/div[{i}]/div[1]/div[1]/div[1]/div[1]/div[1]/p[1]/span[1]/button[1]/span[1]"
                        try:
                            more_button = driver.find_element(By.XPATH, more_button_xpath)
                            if more_button.is_displayed() and more_button.is_enabled():
                                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", more_button)
                                more_button.click()
                                time.sleep(0.5) # Give time for content to expand
                                # Re-read content after expansion
                                expanded_content_xpath = f"/html[1]/body[1]/div[1]/div[2]/div[2]/div[2]/div[1]/main[1]/div[1]/div[1]/div[2]/div[1]/div[{i}]/div[1]/div[1]/div[1]/div[1]/div[1]/p[1]/span[1]/span[2]"
                                expanded_content_el = driver.find_element(By.XPATH, expanded_content_xpath)
                                text_val = norm_text(expanded_content_el.text)
                        except Exception:
                            pass # No "more" button or failed to click

                    except Exception as e:
                        warn(f"Could not extract post content for post at index {i}: {e}")
                        continue

                    if not text_val or len(text_val) < 20:
                        warn(f"Post content too short or empty for post at index {i}.")
                        continue

                    # Try to extract a permalink from the post element (using data-urn as before)
                    link_val: Optional[str] = None
                    try:
                        # Use the new XPath provided by the user to find the element with componentkey
                        component_key_xpath = f"/html/body/div[1]/div[2]/div[2]/div[2]/div/main/div/div/div[2]/div/div[{i}]/div/div/div/div[1]/div"
                        component_el = driver.find_element(By.XPATH, component_key_xpath)
                        urn_val = component_el.get_attribute("componentkey") or ""

                        if urn_val and ("urn:li:activity:" in urn_val or "urn:li:ugcPost:" in urn_val):
                            link_val = f"https://www.linkedin.com/feed/update/{urn_val}"
                    except Exception as e:
                        warn(f"Failed to extract link_val for post at index {i} using new XPath: {e}")
                        pass

                    # Check if post link already exists in processed links
                    if link_val and link_val in existing_links:
                        info(f"Skipping already processed post at index {i}: {link_val}")
                        continue

                    # Deduplicate and keep element for actions
                    if text_val not in [r.get("text") for r in results]:
                        results.append({
                            "text": text_val,
                            "element": post,
                            "link": link_val,
                            "index": i # Store the index for later XPath construction
                        })
                    if len(results) >= max_posts:
                        break
                except Exception as e:
                    warn(f"Failed to process post at index {i}: {e}")
                    continue

            return results

        # 5) Load config for limits and delays
        step(5, "Loading configuration for limits and delays")
        cfg = load_config(os.path.join(repo_root, "config.json"))
        max_like_comment = int(cfg.get("max_like_comment", 5))
        like_comment_min_delay = float(cfg.get("like_comment_minimum_delay", 60))
        like_comment_max_delay = float(cfg.get("like_comment_maximum_delay", 180))
        success("Configuration loaded.")

        # Load already processed post links (do not clear/overwrite)
        liked_file_path = os.path.join(repo_root, "liked_commented.json")
        existing_items = _load_liked_commented(liked_file_path)
        existing_links_set = {str(item.get("post_link")) for item in existing_items if isinstance(item, dict) and item.get("post_link")}

        # 6) Analyze live DOM for posts with Comment button
        step(6, "Analyzing live DOM for posts with Comment button")
        posts = collect_posts_via_dom(max_posts=max_like_comment, existing_links=existing_links_set)
        if not posts:
            warn("DOM scan found no posts. Exiting.")
            return 0

        success(f"Found {len(posts)} posts with comment buttons via DOM scan.")

        # Filtering is now done inside collect_posts_via_dom, so step 7 is removed.
        processed_posts: list[dict[str, Any]] = posts
        success(f"Found {len(processed_posts)} new posts to process.")

        # 8) Process posts
        step(7, "Processing posts") # Renumbered to step 7
        from dotenv import load_dotenv
        load_dotenv()
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or os.getenv("GENAI_API_KEY")

        if not api_key:
            warn("Gemini API key not found in .env (GEMINI_API_KEY/GOOGLE_API_KEY/GENAI_API_KEY). Skipping AI comments.")
            for idx, item in enumerate(processed_posts, 1):
                info(f"Processing post {idx}/{len(processed_posts)}")
                # No AI comment when API key missing
                ai_comment = None
                pretty_print_posts_with_comments([(item["text"], ai_comment, item.get("link"))], start_index=idx, show_link=True)

                # Append printed link to liked_commented.json (at top) if available
                link_val = item.get("link")

                like_succeeded = False

                # Interact with live post if available (skip actions if already processed)
                post_el = item.get("element")
                post_index = item.get("index") # Get the stored index
                if post_el is not None and like and link_val and (link_val not in existing_links_set) and post_index is not None:
                    info("Liking post (no AI comment available)")
                    # Like only (since no AI comment available)
                    try:
                        like_btn_xpath = f"/html[1]/body[1]/div[1]/div[2]/div[2]/div[2]/div[1]/main[1]/div[1]/div[1]/div[2]/div[1]/div[{post_index}]/div[1]/div[1]/div[1]/div[1]/div[1]/div[5]/div[1]/div[1]/div[1]/div[1]/button[1]/span[1]"
                        like_btn = driver.find_element(By.XPATH, like_btn_xpath)
                        try:
                            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", like_btn)
                        except Exception:
                            pass
                        try:
                            like_btn.click()
                            success("Post liked.")
                            like_succeeded = True
                        except Exception:
                            driver.execute_script("arguments[0].click();", like_btn)
                            success("Post liked (via JS).")
                            like_succeeded = True
                        time.sleep(5) # Wait for 5 seconds after clicking "Like" button.
                    except Exception as e:
                        warn(f"Failed to like post: {e}")

                    if like_succeeded and link_val:
                        if _prepend_post_link(liked_file_path, link_val):
                            existing_links_set.add(link_val)
                            success(f"Recorded post link: {link_val}")
                        else:
                            warn(f"Failed to record post link: {link_val}")
                else:
                    info("Skipping interaction for this post (element not found or link missing).")

                # Wait random delay between posts
                if idx < len(processed_posts):
                    delay = random.uniform(like_comment_min_delay, like_comment_max_delay)
                    info(f"Waiting {delay:.1f} seconds before next post…")
                    time.sleep(delay)
            success("All new posts processed (without AI comments).")
        else:
            client = genai.Client(api_key=api_key)
            for idx, item in enumerate(processed_posts, 1):
                info(f"Processing post {idx}/{len(processed_posts)}")
                post_text = item["text"]
                post_el = item.get("element")
                post_index = item.get("index") # Get the stored index
                # Generate comment only if commenting is enabled
                comment_text = None
                if comment:
                    info("Generating AI comment…")
                    try:
                        prompt = (
                            "You are writing a short, thoughtful LinkedIn comment (1–2 sentences) in response to the post below.\n"
                            "Read the post carefully and understand its message, mood, and context before responding.\n"
                            "Your comment should:\n"
                            "- Sound natural, human, and emotionally intelligent.\n"
                            "- Match the tone and sentiment of the post (e.g., inspiring, reflective, proud, grateful, etc.).\n"
                            "- Add a genuine personal insight, appreciation, or perspective that feels relevant to the post.\n"
                            "- Avoid generic praise or repetition of the post’s content.\n"
                            "Output only the comment text — no labels, explanations, or formatting.\n\n"
                            f"Post:\n{post_text}\n"
                        )
                        resp = client.models.generate_content(
                            model="gemini-2.5-flash",
                            contents=prompt,
                        )
                        raw_comment = (resp.text or "").strip()
                        comment_text = clean_model_comment(raw_comment)
                        success("AI comment generated.")
                    except Exception as e:
                        warn(f"Failed to generate AI comment: {e}")
                        comment_text = None

                # Print post and comment
                pretty_print_posts_with_comments([(post_text, comment_text, item.get("link"))], start_index=idx, show_link=True)

                # Append printed link to liked_commented.json (at top) if available
                link_val = item.get("link")

                comment_succeeded = False
                like_succeeded = False

                # Try to comment and like on the live post element if available (only when link exists)
                # Ensure post_index is available for XPath construction
                # Re-find the post element to ensure it's still valid in the DOM
                current_post_el = None
                if post_index is not None:
                    try:
                        re_find_post_xpath = f"/html[1]/body[1]/div[1]/div[2]/div[2]/div[2]/div[1]/main[1]/div[1]/div[1]/div[2]/div[1]/div[{post_index}]"
                        current_post_el = driver.find_element(By.XPATH, re_find_post_xpath)
                        info(f"Re-found post element for index {post_index}.")
                    except Exception as e:
                        warn(f"Failed to re-find post element for index {post_index}: {e}")

                if current_post_el is not None and link_val and post_index is not None:
                    # 1) Open comment box (only when commenting enabled and we have text)
                    if comment and comment_text:
                        info("Opening comment box…")
                        try:
                            comment_btn_xpath = f"/html[1]/body[1]/div[1]/div[2]/div[2]/div[2]/div[1]/main[1]/div[1]/div[1]/div[2]/div[1]/div[{post_index}]/div[1]/div[1]/div[1]/div[1]/div[1]/div[5]/button[1]/span[1]"
                            comment_btn = driver.find_element(By.XPATH, comment_btn_xpath)
                        except Exception:
                            comment_btn = None
                        if comment_btn:
                            try:
                                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", comment_btn)
                            except Exception:
                                pass
                            try:
                                comment_btn.click()
                                success("Comment box opened.")
                            except Exception:
                                try:
                                    driver.execute_script("arguments[0].click();", comment_btn)
                                    success("Comment box opened (via JS).")
                                except Exception as e:
                                    warn(f"Failed to open comment box: {e}")
                            time.sleep(5) # Wait for 5 seconds after opening comment box before typing.

                        # 2) Type the comment and submit (more robust headless handling)
                        if comment_text:
                            info("Typing and submitting comment…")
                            try:
                                # Wait for the inline comment editor to render after clicking the button
                                editor = None
                                is_headless = os.getenv("HEADLESS", "").strip().lower() in {"1", "true", "yes", "y"}
                                deadline = time.time() + (6.0 if is_headless else 3.0)

                                # Use the provided XPath for the comment box input
                                editor_xpath = f"/html/body/div[1]/div[2]/div[2]/div[2]/div/main/div/div/div[2]/div/div[{post_index}]/div/div/div/div[3]/div/div/div/div[1]/div[1]/div/div/div[1]/div/p"

                                while editor is None and time.time() < deadline:
                                    try:
                                        cand = driver.find_element(By.XPATH, editor_xpath)
                                        if cand and cand.is_displayed():
                                            editor = cand
                                            break
                                    except Exception:
                                        pass
                                    time.sleep(0.15)

                                if editor:
                                    try:
                                        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", editor)
                                    except Exception:
                                        pass
                                    # Focus editor using multiple strategies
                                    focused = False
                                    try:
                                        editor.click()
                                        focused = True
                                    except Exception:
                                        try:
                                            driver.execute_script("arguments[0].click();", editor)
                                            focused = True
                                        except Exception:
                                            pass
                                    if not focused:
                                        try:
                                            ActionChains(driver).move_to_element(editor).click().perform()
                                            focused = True
                                        except Exception:
                                            pass
                                    if not focused:
                                        try:
                                            driver.execute_script("arguments[0].focus();", editor)
                                            focused = True
                                        except Exception:
                                            pass
                                    # Type/paste the comment; try send_keys first then JS injection
                                    typed = False
                                    try:
                                        editor.clear()
                                    except Exception:
                                        pass
                                    # Simulate human typing
                                    for char in comment_text:
                                        editor.send_keys(char)
                                        time.sleep(random.uniform(0.05, 0.15)) # Small random delay between characters
                                    typed = True
                                    
                                    time.sleep(2) # Wait 2 seconds after typing.

                                    # Press TAB 2 times with 2-second interval, then ENTER
                                    try:
                                        ActionChains(driver).send_keys(Keys.TAB).pause(2).send_keys(Keys.TAB).pause(2).send_keys(Keys.ENTER).perform()
                                        time.sleep(5) # Wait for 5 seconds after pressing ENTER.
                                        success("Comment submitted (via keyboard sequence).")
                                        comment_succeeded = True
                                    except Exception as e:
                                        warn(f"Failed to submit comment via keyboard sequence: {e}")
                            except Exception as e:
                                warn(f"Failed to type comment: {e}")

                    # 3) Like the post (only if enabled)
                    if like:
                        info("Liking post…")
                        try:
                            like_btn_xpath = f"/html[1]/body[1]/div[1]/div[2]/div[2]/div[2]/div[1]/main[1]/div[1]/div[1]/div[2]/div[1]/div[{post_index}]/div[1]/div[1]/div[1]/div[1]/div[1]/div[5]/div[1]/div[1]/div[1]/div[1]/button[1]/span[1]"
                            like_btn = driver.find_element(By.XPATH, like_btn_xpath)
                            try:
                                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", like_btn)
                            except Exception:
                                pass
                            try:
                                like_btn.click()
                                success("Post liked.")
                                like_succeeded = True
                            except Exception:
                                driver.execute_script("arguments[0].click();", like_btn)
                                success("Post liked (via JS).")
                                like_succeeded = True
                            time.sleep(5) # Wait for 5 seconds after clicking "Like" button.
                        except Exception as e:
                            warn(f"Failed to like post: {e}")
                else:
                    info("Skipping interaction for this post (element not found or link missing).")

                # Record link only if both comment and like were successful (or only like if comment was not attempted/enabled)
                should_record_link = False
                if comment and like:
                    should_record_link = comment_succeeded and like_succeeded
                elif comment and not like: # Only commenting enabled
                    should_record_link = comment_succeeded
                elif not comment and like: # Only liking enabled
                    should_record_link = like_succeeded
                # If neither is enabled, should_record_link remains False, which is correct.

                if should_record_link and link_val:
                    if _prepend_post_link(liked_file_path, link_val):
                        existing_links_set.add(link_val)
                        success(f"Recorded post link: {link_val}")
                    else:
                        warn(f"Failed to record post link: {link_val}")

                # Wait random delay between posts
                if idx < len(processed_posts):
                    delay = random.uniform(like_comment_min_delay, like_comment_max_delay)
                    info(f"Waiting {delay:.1f} seconds before next post…")
                    time.sleep(delay)
            success("All new posts processed.")

        return 0

    except KeyboardInterrupt:
        info("Interrupted by user. Exiting gracefully…")
        return 0
    except Exception as exc:
        error(f"Unhandled error: {exc}")
        return 1

    finally:
        # Close the browser after program completion
        try:
            if driver:
                info("Closing browser…")
                driver.quit()
                success("Browser closed.")
        except Exception as e:
            warn(f"Failed to close browser: {e}")


if __name__ == "__main__":
    raise SystemExit(main())
