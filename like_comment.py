# post_comments.py
# Logs into LinkedIn using login.py, opens the feed page, saves the HTML to temp,
# parses posts that have a Comment button, prints them in the same style as get_info.py,
# keeps the saved HTML file, and leaves the browser open (testing).

import os
import sys
import time
import re
import json
import random
import html as _html
import logging
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
    # Fallback if colorama is not installed
    class _Fore:
        CYAN = ""
        GREEN = ""
        YELLOW = ""
        MAGENTA = ""
    class _Style:
        BRIGHT = ""
        RESET_ALL = ""
    Fore = _Fore()
    Style = _Style()

# Reuse login from login.py
from login import login_and_get_driver

# Developer toggles: set to True/False to enable/disable features
like = True      # Toggle to enable/disable liking
comment = True   # Toggle to enable/disable commenting

# Browser mode toggle (default: headful)
HEADLESS = True

FEED_URL = "https://www.linkedin.com/feed/"


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


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def info(msg: str):
    logging.info(msg)


def warn(msg: str):
    logging.warning(msg)


def err(msg: str):
    logging.error(msg)


def ensure_temp_dir(temp_dir: str) -> None:
    if not os.path.isdir(temp_dir):
        os.makedirs(temp_dir, exist_ok=True)


def strip_tags(html: str) -> str:
    # Remove script/style then tags, unescape, and normalize whitespace
    no_script = re.sub(r"(?is)<(script|style)[^>]*>.*?</\\1>", " ", html)
    no_tags = re.sub(r"(?s)<[^>]+>", " ", no_script)
    text = _html.unescape(no_tags)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def extract_post_text_from_segment(seg_html: str) -> Optional[str]:
    # Try common LinkedIn feed content containers first
    patterns = [
        r'(?is)<div[^>]+class="[^"]*(?:update-components-text|feed-shared-update-v2__description-wrapper)[^"]*"[^>]*>(.*?)</div>',
        r'(?is)<span[^>]+dir="ltr"[^>]*>(.*?)</span>',
    ]
    for pat in patterns:
        m = re.search(pat, seg_html)
        if m:
            txt = strip_tags(m.group(1))
            if txt:
                return txt
    # Fallback: strip the whole segment and take a reasonable slice
    txt = strip_tags(seg_html)
    # Heuristic: ignore extremely short or boilerplate-only segments
    if txt and len(txt) > 20:
        return txt
    return None


def extract_posts_with_comment(html_text: str, max_posts: int = 10) -> List[dict]:
    # Split by <article> blocks which commonly wrap feed posts
    segments = re.split(r'(?i)(?=<article[^>]*>)', html_text)
    results: List[dict] = []

    # A post is considered valid if it has a recognizable Comment button
    comment_markers = [
        r'aria-label="\s*comment\s*"',
        r'data-control-name="\s*comment\s*"',
        r'>\s*comment\s*<',
    ]
    comment_re = re.compile("|".join(comment_markers), re.IGNORECASE)

    # Exclude promoted/sponsored posts (commonly labeled "Promoted" on LinkedIn)
    promoted_markers = [
        r'aria-label\s*=\s*"\s*Promoted\s*"',
        r'>\s*Promoted\s*<',
        r'aria-label\s*=\s*"\s*Sponsored\s*"',
        r'>\s*Sponsored\s*<'
    ]
    promoted_re = re.compile("|".join(promoted_markers), re.IGNORECASE)

    # Helper to find a plausible permalink from the segment
    permalink_re = re.compile(r'(https?://www\.linkedin\.com/(?:feed/update|posts|pulse|in/.+?/detail|feed/update/urn:li:activity:[0-9]+)[^"\s<>]*)')

    for seg in segments:
        if not seg:
            continue
        if promoted_re.search(seg):
            # Skip ads/promoted content
            continue
        if not comment_re.search(seg):
            continue
        text = extract_post_text_from_segment(seg)
        if not text:
            continue

        link: Optional[str] = None
        m = permalink_re.search(seg)
        if m:
            link = _html.unescape(m.group(1))

        # Deduplicate only (do not truncate)
        text_norm = re.sub(r"\s+", " ", text).strip()
        if text_norm and all(text_norm != r.get("text") for r in results):
            results.append({"text": text_norm, "link": link})
        if len(results) >= max_posts:
            break

    return results


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

        # Validate post link format
        # Expected format: https://www.linkedin.com/feed/update/urn:li:activity:{some number}
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
    # Honor HEADLESS variable by setting the env var used by login.py
    os.environ["HEADLESS"] = "1" if HEADLESS else "0"

    # Setup logging
    setup_logging()

    driver = None
    html_path = None

    # Resolve repo root and temp directory early
    repo_root = os.path.dirname(__file__)
    temp_dir = os.path.join(repo_root, "temp")

    # Clear temp folder at start
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
        info("Temp folder cleared.")
    except Exception as e:
        warn(f"Failed to clear temp folder: {e}")

    try:
        info("Logging in and launching browser…")
        driver = login_and_get_driver()

        info("Opening LinkedIn feed…")
        driver.get(FEED_URL)

        # Wait for <main> to be present as a generic ready signal
        wait = WebDriverWait(driver, 25)
        try:
            wait.until(EC.presence_of_element_located((By.TAG_NAME, "main")))
        except Exception:
            time.sleep(2)

        # Optional: small delay to allow first posts to render
        time.sleep(2)

        # Save page HTML to temp folder (path prepared earlier)
        ensure_temp_dir(temp_dir)
        html_path = os.path.join(temp_dir, f"feed_{int(time.time())}.html")

        info(f"Saving feed HTML to: {html_path}")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(driver.page_source)

        # Prefer analyzing live DOM (more reliable than static HTML), then fall back to saved HTML
        def collect_posts_via_dom(max_posts: int = 25) -> list[dict[str, Any]]:
            results: list[dict[str, Any]] = []

            def norm_text(s: str) -> str:
                return re.sub(r"\s+", " ", (s or "").strip())

            # Attempt a few scrolls to load posts
            for _ in range(3):
                try:
                    driver.execute_script("window.scrollBy(0, document.body.scrollHeight/3);")
                except Exception:
                    pass
                time.sleep(1.2)

            # Find likely post containers by data-urn (activity or ugcPost) or role=article
            post_candidates = driver.find_elements(
                By.XPATH,
                "//div[starts-with(@data-urn,'urn:li:activity:') or starts-with(@data-urn,'urn:li:ugcPost:')] | //div[@role='article']"
            )

            for post in post_candidates:
                try:
                    seg_text = post.get_attribute("innerHTML") or ""
                    # Exclude promoted/sponsored markers inside the post container
                    if re.search(r"(?i)\b(Promoted|Sponsored)\b", seg_text):
                        continue

                    # Verify required actions are available: Comment, Repost, and Send
                    def has_action(xpath: str) -> bool:
                        try:
                            elems = post.find_elements(By.XPATH, xpath)
                            return len(elems) > 0
                        except Exception:
                            return False

                    has_comment = has_action(
                        ".//button[contains(translate(., 'COMMENT', 'comment'),'comment') or contains(translate(@aria-label, 'COMMENT','comment'),'comment')] | .//a[contains(translate(., 'COMMENT', 'comment'),'comment')]"
                    )
                    if not has_comment:
                        continue

                    has_repost = has_action(
                        ".//button[contains(translate(., 'REPOST', 'repost'),'repost') or contains(translate(@aria-label, 'REPOST','repost'),'repost')] | .//a[contains(translate(., 'REPOST', 'repost'),'repost')]"
                    )
                    has_send = has_action(
                        ".//button[contains(translate(., 'SEND', 'send'),'send') or contains(translate(@aria-label, 'SEND','send'),'send')] | .//a[contains(translate(., 'SEND', 'send'),'send')]"
                    )

                    # Exclude achievement-style posts that typically only have Like and Comment
                    if not (has_repost and has_send):
                        continue

                    # Expand truncated content within this post (See more/Show more) before extracting
                    try:
                        expand_xpath = (
                            ".//button[contains(translate(., 'SEE MORE','see more'),'see more') or "
                            "contains(translate(., 'SHOW MORE','show more'),'show more') or "
                            "contains(translate(@aria-label,'SEE MORE','see more'),'see more') or "
                            "contains(@data-control-name,'text_truncation_show_more') or "
                            "contains(@class,'see-more') or contains(@class,'lt-line-clamp__more')] | "
                            ".//a[contains(translate(., 'SEE MORE','see more'),'see more') or "
                            "contains(translate(., 'SHOW MORE','show more'),'show more') or "
                            "contains(translate(@aria-label,'SEE MORE','see more'),'see more')]")
                        more_elems = post.find_elements(By.XPATH, expand_xpath)
                        for m in more_elems[:3]:  # click up to 3 expanders within a post
                            try:
                                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", m)
                            except Exception:
                                pass
                            try:
                                m.click()
                            except Exception:
                                try:
                                    driver.execute_script("arguments[0].click();", m)
                                except Exception:
                                    pass
                            time.sleep(0.2)
                    except Exception:
                        pass

                    # Extract the post content from commentary/description containers, avoiding actor header
                    text_val: Optional[str] = None

                    # Priority 1: commentary container (single block)
                    commentary_xpath = (
                        ".//div[(contains(@class,'feed-shared-update-v2__commentary') or "
                        "contains(@data-test-id,'feed-shared-update-v2__commentary')) and "
                        "not(ancestor::*[contains(@class,'feed-shared-actor') or contains(@class,'update-components-actor')])]"
                    )
                    # Priority 2: general update text/description container
                    general_text_xpath = (
                        ".//div[(contains(@class,'update-components-text') or "
                        "contains(@class,'feed-shared-update-v2__description-wrapper')) and "
                        "not(ancestor::*[contains(@class,'feed-shared-actor') or contains(@class,'update-components-actor')])]"
                    )

                    def try_collect(xpath: str) -> Optional[str]:
                        try:
                            els = post.find_elements(By.XPATH, xpath)
                        except Exception:
                            els = []
                        for el in els:
                            try:
                                raw = el.get_attribute("innerText") or el.text or ""
                                candidate = norm_text(raw)
                                if candidate and len(candidate) > 20:
                                    return candidate
                            except Exception:
                                continue
                        return None

                    text_val = try_collect(commentary_xpath)
                    if not text_val:
                        text_val = try_collect(general_text_xpath)

                    # Fallback: try other generic text locations (less reliable)
                    if not text_val:
                        try:
                            raw = post.get_attribute("innerText") or post.text or ""
                            candidate = norm_text(raw)
                            if candidate and len(candidate) > 20:
                                text_val = candidate
                        except Exception:
                            pass

                    if not text_val:
                        continue

                    # Try to extract a permalink from the post element
                    link_val: Optional[str] = None
                    try:
                        # Look for anchor tags with URNs or post routes
                        link_candidates = post.find_elements(
                            By.XPATH,
                            ".//a[contains(@href,'/feed/update/') or contains(@href,'posts/') or contains(@href,'/detail/') or contains(@href,'urn:li:activity:') or contains(@href,'urn:li:ugcPost:')]"
                        )
                        for a in link_candidates:
                            href = a.get_attribute("href") or ""
                            if href and href.startswith("http") and "linkedin.com" in href:
                                link_val = href
                                break

                        # Fallback: construct from data-urn if present (immediate, no clipboard needed)
                        if not link_val:
                            try:
                                urn_val = post.get_attribute("data-urn") or ""
                                if not urn_val:
                                    # try to find nearest descendant/ancestor with data-urn
                                    try:
                                        urn_el = post.find_element(By.XPATH, ".//*[@data-urn]")
                                        urn_val = urn_el.get_attribute("data-urn") or ""
                                    except Exception:
                                        urn_val = ""
                                if urn_val and ("urn:li:activity:" in urn_val or "urn:li:ugcPost:" in urn_val):
                                    link_val = f"https://www.linkedin.com/feed/update/{urn_val}"
                            except Exception:
                                pass
                    except Exception:
                        pass

                    # Deduplicate and keep element for actions
                    if text_val not in [r.get("text") for r in results]:
                        results.append({
                            "text": text_val,
                            "element": post,
                            "link": link_val,
                        })
                    if len(results) >= max_posts:
                        break
                except Exception:
                    continue

            return results

        # Load config for limits and delays
        cfg = load_config(os.path.join(repo_root, "config.json"))
        max_like_comment = int(cfg.get("max_like_comment", 5))
        like_comment_min_delay = float(cfg.get("like_comment_minimum_delay", 60))
        like_comment_max_delay = float(cfg.get("like_comment_maximum_delay", 180))

        # Load already processed post links (do not clear/overwrite)
        liked_file_path = os.path.join(repo_root, "liked_commented.json")
        existing_items = _load_liked_commented(liked_file_path)
        existing_links_set = {str(item.get("post_link")) for item in existing_items if isinstance(item, dict) and item.get("post_link")}

        info("Analyzing live DOM for posts with Comment button…")
        posts = collect_posts_via_dom(max_posts=max_like_comment)

        # Fallback: static HTML parsing if DOM-based extraction found nothing
        if not posts:
            info("DOM scan found no posts. Falling back to saved HTML analysis…")
            with open(html_path, "r", encoding="utf-8") as f:
                html_text = f.read()
            posts = extract_posts_with_comment(
                html_text,
                max_posts=max_like_comment,
            )
            # Normalize into dicts with link for static HTML path
            if posts and isinstance(posts, list) and posts and not isinstance(posts[0], dict):
                posts = [{"text": p, "element": None, "link": None} for p in posts]

        # Analyze and interact sequentially per post with randomized wait
        from dotenv import load_dotenv
        load_dotenv()
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or os.getenv("GENAI_API_KEY")

        # Normalize posts list to a unified structure with text and optional element
        normalized_posts: list[dict[str, Any]] = []
        if posts and isinstance(posts[0], dict):
            normalized_posts = posts  # from DOM path
        else:
            # from HTML path (no elements available)
            normalized_posts = [{"text": p, "element": None} for p in posts]

        # Filter out posts whose links were already processed
        processed_posts: list[dict[str, Any]] = []
        for it in normalized_posts:
            lk = it.get("link")
            if lk and lk in existing_links_set:
                continue
            processed_posts.append(it)

        if not api_key:
            info("Gemini API key not found in .env (GEMINI_API_KEY/GOOGLE_API_KEY/GENAI_API_KEY). Skipping AI comments.")
            for idx, item in enumerate(processed_posts, 1):
                # No AI comment when API key missing
                ai_comment = None
                pretty_print_posts_with_comments([(item["text"], ai_comment, item.get("link"))], start_index=idx, show_link=True)

                # Append printed link to liked_commented.json (at top) if available
                link_val = item.get("link")
                if link_val:
                    if _prepend_post_link(liked_file_path, link_val):
                        existing_links_set.add(link_val)

                # Interact with live post if available (skip actions if already processed)
                post_el = item.get("element")
                if post_el is not None and like and link_val and (link_val not in existing_links_set):
                    # Like only (since no AI comment available)
                    try:
                        like_btn = post_el.find_element(
                            By.XPATH,
                            ".//button[contains(translate(., 'LIKE', 'like'),'like') or contains(translate(@aria-label, 'LIKE','like'),'like')] | .//span[contains(translate(., 'LIKE', 'like'),'like')]/ancestor::button[1]",
                        )
                        try:
                            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", like_btn)
                        except Exception:
                            pass
                        try:
                            like_btn.click()
                        except Exception:
                            driver.execute_script("arguments[0].click();", like_btn)
                        time.sleep(0.3)
                    except Exception:
                        pass

                # Wait random delay between posts
                if idx < len(normalized_posts):
                    delay = random.uniform(like_comment_min_delay, like_comment_max_delay)
                    info(f"Waiting {delay:.1f} seconds before next post…")
                    time.sleep(delay)
        else:
            client = genai.Client(api_key=api_key)
            for idx, item in enumerate(processed_posts, 1):
                post_text = item["text"]
                post_el = item.get("element")
                # Generate comment only if commenting is enabled
                comment_text = None
                if comment:
                    try:
                        prompt = (
                            "Write a concise, professional, production-ready LinkedIn comment (1-2 sentences) responding to the post below.\n"
                            "Do not include any headings, labels, or prefaces. Output only the comment text.\n\n"
                            f"Post:\n{post_text}\n"
                        )
                        resp = client.models.generate_content(
                            model="gemini-2.5-flash",
                            contents=prompt,
                        )
                        raw_comment = (resp.text or "").strip()
                        comment_text = clean_model_comment(raw_comment)
                    except Exception:
                        comment_text = None

                # Print post and comment
                pretty_print_posts_with_comments([(post_text, comment_text, item.get("link"))], start_index=idx, show_link=True)

                # Append printed link to liked_commented.json (at top) if available
                link_val = item.get("link")
                if link_val:
                    if _prepend_post_link(liked_file_path, link_val):
                        existing_links_set.add(link_val)

                # Try to comment and like on the live post element if available (only when link exists)
                if post_el is not None and link_val:
                    try:
                        # 1) Open comment box (only when commenting enabled and we have text)
                        if comment and comment_text:
                            try:
                                comment_btn = post_el.find_element(
                                    By.XPATH,
                                    ".//button[contains(translate(., 'COMMENT', 'comment'),'comment') or contains(translate(@aria-label, 'COMMENT','comment'),'comment')] | .//a[contains(translate(., 'COMMENT', 'comment'),'comment')]",
                                )
                            except Exception:
                                comment_btn = None
                            if comment_btn:
                                try:
                                    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", comment_btn)
                                except Exception:
                                    pass
                                try:
                                    comment_btn.click()
                                except Exception:
                                    try:
                                        driver.execute_script("arguments[0].click();", comment_btn)
                                    except Exception:
                                        pass
                                time.sleep(0.3)

                            # 2) Type the comment and submit (more robust headless handling)
                            try:
                                # Wait for the inline comment editor to render after clicking the button
                                editor = None
                                is_headless = os.getenv("HEADLESS", "").strip().lower() in {"1", "true", "yes", "y"}
                                deadline = time.time() + (6.0 if is_headless else 3.0)

                                # Common editor patterns in LinkedIn feed
                                editor_xpaths = [
                                    ".//div[contains(@role,'textbox') and contains(@class,'comments-comment-box__editor')]",
                                    ".//div[contains(@role,'textbox') and contains(@class,'ql-editor')]",
                                    ".//div[@contenteditable='true']",
                                    ".//textarea",
                                ]

                                while editor is None and time.time() < deadline:
                                    for xp in editor_xpaths:
                                        try:
                                            cand = post_el.find_element(By.XPATH, xp)
                                            if cand and cand.is_displayed():
                                                editor = cand
                                                break
                                        except Exception:
                                            continue
                                    if editor is None:
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
                                    try:
                                        editor.send_keys(comment_text)
                                        typed = True
                                    except Exception:
                                        pass
                                    if not typed:
                                        try:
                                            # For Quill-like editors, update textContent and dispatch input/keyup
                                            driver.execute_script(
                                                "if(arguments[0]){arguments[0].textContent = arguments[1]; arguments[0].dispatchEvent(new Event('input', {bubbles:true})); arguments[0].dispatchEvent(new KeyboardEvent('keyup', {bubbles:true, key:'a'}));}",
                                                editor,
                                                comment_text,
                                            )
                                            typed = True
                                        except Exception:
                                            pass
                                    if not typed:
                                        try:
                                            ActionChains(driver).send_keys(comment_text).perform()
                                            typed = True
                                        except Exception:
                                            pass

                                    # Try keyboard submit first: TAB → TAB → TAB → ENTER (as required)
                                    try:
                                        ActionChains(driver).send_keys(Keys.TAB).pause(0.2).send_keys(Keys.TAB).pause(0.2).send_keys(Keys.TAB).pause(0.2).send_keys(Keys.ENTER).perform()
                                        time.sleep(0.8 if is_headless else 0.6)
                                    except Exception:
                                        pass

                                    # Fallback: click an enabled Post/Comment/Send button with a short wait
                                    try:
                                        submit_xpaths = [
                                            ".//div[contains(@class,'comments-comment-box') or contains(@class,'comments-comment-box__form') or contains(@class,'comments-comments-list') or contains(@class,'comments-comment-box__container')]/descendant::button[not(@disabled) and (contains(translate(., 'POST','post'),'post') or contains(translate(., 'COMMENT','comment'),'comment') or contains(translate(., 'SEND','send'),'send') or contains(@data-control-name,'comment_post'))]",
                                            ".//button[not(@disabled) and (contains(translate(., 'POST','post'),'post') or contains(translate(., 'SEND','send'),'send') or contains(translate(., 'COMMENT','comment'),'comment'))]",
                                        ]
                                        submit_btn = None
                                        for sx in submit_xpaths:
                                            try:
                                                submit_btn = post_el.find_element(By.XPATH, sx)
                                                if submit_btn:
                                                    break
                                            except Exception:
                                                continue
                                        if not submit_btn:
                                            try:
                                                container = editor.find_element(
                                                    By.XPATH,
                                                    "./ancestor::*[contains(@class,'comments-comment-box') or contains(@class,'comments-container') or contains(@class,'comments-comment-box__container')][1]"
                                                )
                                                for sx in submit_xpaths:
                                                    try:
                                                        submit_btn = container.find_element(By.XPATH, sx)
                                                        if submit_btn:
                                                            break
                                                    except Exception:
                                                        continue
                                            except Exception:
                                                pass

                                        # Wait briefly for button to become clickable/displayed
                                        end_time = time.time() + (4.0 if is_headless else 2.0)
                                        while (submit_btn is None or (not submit_btn.is_displayed() or not submit_btn.is_enabled())) and time.time() < end_time:
                                            try:
                                                for sx in submit_xpaths:
                                                    try:
                                                        scope = container if 'container' in locals() and container is not None else post_el
                                                        candidate = scope.find_element(By.XPATH, sx)
                                                        if candidate and candidate.is_displayed() and candidate.is_enabled():
                                                            submit_btn = candidate
                                                            break
                                                    except Exception:
                                                        continue
                                            except Exception:
                                                pass
                                            time.sleep(0.12)

                                        if submit_btn and submit_btn.is_displayed():
                                            try:
                                                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", submit_btn)
                                            except Exception:
                                                pass
                                            try:
                                                submit_btn.click()
                                            except Exception:
                                                driver.execute_script("arguments[0].click();", submit_btn)
                                            time.sleep(0.8 if is_headless else 0.6)
                                        else:
                                            # Last resort: Ctrl+Enter (often works for LinkedIn comment box)
                                            try:
                                                editor.send_keys(Keys.CONTROL, Keys.ENTER)
                                                time.sleep(0.5 if is_headless else 0.4)
                                            except Exception:
                                                pass
                                    except Exception:
                                        pass
                            except Exception:
                                pass

                        # 3) Like the post (only if enabled)
                        if like:
                            try:
                                like_btn = post_el.find_element(
                                    By.XPATH,
                                    ".//button[contains(translate(., 'LIKE', 'like'),'like') or contains(translate(@aria-label, 'LIKE','like'),'like')] | .//span[contains(translate(., 'LIKE', 'like'),'like')]/ancestor::button[1]",
                                )
                                try:
                                    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", like_btn)
                                except Exception:
                                    pass
                                try:
                                    like_btn.click()
                                except Exception:
                                    driver.execute_script("arguments[0].click();", like_btn)
                                time.sleep(0.3)
                            except Exception:
                                pass
                    except Exception:
                        pass

                # Wait random delay between posts
                if idx < len(normalized_posts):
                    delay = random.uniform(like_comment_min_delay, like_comment_max_delay)
                    info(f"Waiting {delay:.1f} seconds before next post…")
                    time.sleep(delay)

        return 0

    except KeyboardInterrupt:
        info("Interrupted by user. Exiting gracefully…")
        return 0
    except Exception as exc:
        err(f"Unhandled error: {exc}")
        return 1

    finally:
        # Delete the saved HTML before closing the browser
        try:
            if html_path and os.path.exists(html_path):
                os.remove(html_path)
                info(f"Deleted temp HTML: {html_path}")
        except Exception as e:
            warn(f"Failed to delete temp HTML: {e}")

        # Close the browser after program completion
        try:
            if driver:
                info("Closing browser…")
                driver.quit()
        except Exception as e:
            warn(f"Failed to close browser: {e}")


if __name__ == "__main__":
    raise SystemExit(main())
