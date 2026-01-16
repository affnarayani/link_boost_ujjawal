import os
import time
import json
import random
import re

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

from login import login_and_get_driver

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

def main() -> int:
    banner("LinkedIn Text Extractor")

    os.environ["HEADLESS"] = "1" if HEADLESS else "0"

    driver = None

    try:
        step(1, "Logging in and launching browser")
        driver = login_and_get_driver()
        success("Driver ready")

        step(2, "Opening LinkedIn feed")
        driver.get(FEED_URL)

        wait = WebDriverWait(driver, 25)
        try:
            wait.until(EC.presence_of_element_located((By.TAG_NAME, "main")))
            success("Feed loaded")
        except Exception:
            time.sleep(2)
            warn("Main element not found quickly, proceeding after small delay.")

        step(3, "Waiting 15 seconds for dynamic content to load")
        time.sleep(15)
        success("Dynamic content wait complete.")

        time.sleep(2)

        step(4, "Refocusing website with TAB key presses")
        actions = ActionChains(driver)
        for i in range(13):
            actions.send_keys(Keys.TAB)
            actions.perform()
            time.sleep(1)
            info(f"Pressed TAB {i+1}/13 times.")
        success("Website refocused.")

        step(5, "Performing scrolling with Page Down key")
        actions = ActionChains(driver)
        for _ in range(5):
            actions.send_keys(Keys.PAGE_DOWN).pause(1)
        actions.perform()
        success("Scrolling with Page Down complete.")

        step(6, "Locating and printing text from specified xpath")
        # Load existing links
        liked_file_path = os.path.join(os.path.dirname(__file__), "liked_commented.json")
        existing_links = set()
        try:
            if os.path.exists(liked_file_path):
                with open(liked_file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        for item in data:
                            if isinstance(item, dict) and item.get("post_link"):
                                existing_links.add(item["post_link"])
        except Exception as e:
            warn(f"Failed to load liked_commented.json: {e}")

        short_content_xpath_template = "/html/body/div[1]/div[2]/div[2]/div[2]/div/main/div/div/div[2]/div/div[{i}]/div/div/div/div[1]/div/p/span"
        promoted_xpath_template = "/html/body/div[1]/div[2]/div[2]/div[2]/div/main/div/div/div[2]/div/div[{i}]/div/div/div/div[1]/div/div[2]/a[2]/div/div[3]/p"
        for i in range(4, 10):
            promoted_xpath = promoted_xpath_template.format(i=i)
            is_promoted = False
            try:
                promoted_element = driver.find_element(By.XPATH, promoted_xpath)
                if "Promoted" in promoted_element.text:
                    is_promoted = True
            except Exception:
                pass  # Not found or error, assume not promoted

            if not is_promoted:
                # Try to click more button first
                more_button_xpath = f"/html/body/div[1]/div[2]/div[2]/div[2]/div/main/div/div/div[2]/div/div[{i}]/div/div/div/div[1]/div/p/span/button/span/span/span[2]"
                clicked_more = False
                try:
                    more_button = driver.find_element(By.XPATH, more_button_xpath)
                    more_button.click()
                    info(f"Clicked more button for i={i}")
                    time.sleep(0.5)  # Wait for expansion
                    clicked_more = True
                except Exception as e:
                    warn(f"Failed to find or click more button for i={i}: {e}")

                # Now read the content
                short_content_xpath = short_content_xpath_template.format(i=i)
                try:
                    element = driver.find_element(By.XPATH, short_content_xpath)
                    text = element.text
                    info(f"Text for i={i}: {text}")

                    # Extract and print the post link
                    three_dot_xpath = f"/html/body/div[1]/div[2]/div[2]/div[2]/div/main/div/div/div[2]/div/div[{i}]/div/div/div/div[1]/div/div[1]/button[1]/span"
                    try:
                        three_dot_button = driver.find_element(By.XPATH, three_dot_xpath)
                        three_dot_button.click()
                        info(f"Clicked three dot button for i={i}")
                        time.sleep(3)  # Wait for dropdown

                        embed_post_xpath = "/html/body/div[2]/div/div/div/div/div/div/a[1]/div/div/p"
                        embed_button = driver.find_element(By.XPATH, embed_post_xpath)
                        embed_button.click()
                        info(f"Clicked embed post button for i={i}")
                        time.sleep(15)  # Wait for popup to open

                        host_element = driver.find_element(By.XPATH, "/html/body/div[1]/div[4]")
                        shadow_root = driver.execute_script('return arguments[0].shadowRoot', host_element)
                        input_element = shadow_root.find_element(By.CSS_SELECTOR, "#feed-components-shared-embed-modal__snippet")
                        full_link = input_element.get_attribute("value")
                        # Extract src from iframe tag if present
                        src_match = re.search(r'src="([^"]+)"', full_link)
                        if src_match:
                            link = src_match.group(1).replace('/embed/', '/')
                        else:
                            link = full_link
                        link = link.split('?')[0]
                        info(f"Post link: {link}")

                        time.sleep(5)  # Wait before exiting
                        exit_button = shadow_root.find_element(By.CSS_SELECTOR, ".artdeco-button.artdeco-button--circle.artdeco-button--muted.artdeco-button--2.artdeco-button--tertiary.ember-view.artdeco-modal__dismiss")
                        exit_button.click()
                        time.sleep(5)  # Wait after exiting
                        if link not in existing_links:
                            info("New link found.")
                            info(f"Text for i={i}: {text}")

                            # Generate AI comment
                            api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or os.getenv("GENAI_API_KEY")
                            if not api_key:
                                warn("Gemini API key not found. Skipping comment generation.")
                            else:
                                client = genai.Client(api_key=api_key)
                                post_text = text
                                prompt = (
                                    "You are writing a short, thoughtful LinkedIn comment (1–2 sentences) in response to the post below.\n"
                                    "Read the post carefully and understand its message, mood, and context before responding.\n"
                                    "Your comment should:\n"
                                    "- Sound natural, human, and emotionally intelligent.\n"
                                    "- Match the tone and sentiment of the post (e.g., inspiring, reflective, proud, grateful, etc.).\n"
                                    "- Add a genuine personal insight, appreciation, or perspective that feels relevant to the post.\n"
                                    "- Avoid generic praise or repetition of the post’s content.\n"
                                    "- Do not use any special characters like asterisks (*) or Markdown-style formatting.\n"
                                    "Output only the comment text — no labels, explanations, or formatting.\n\n"
                                    f"Post:\n{post_text}\n"
                                )
                                try:
                                    response = client.models.generate_content(
                                        model="gemini-3-flash-preview",
                                        contents=prompt,
                                    )
                                    raw_comment = (response.text or "").strip()
                                    comment_text = clean_model_comment(raw_comment)
                                    info(f"AI Comment: {comment_text}")

                                    # Now comment on the post
                                    comment_button_xpath = f"/html/body/div[1]/div[2]/div[2]/div[2]/div/main/div/div/div[2]/div/div[{i}]/div/div/div/div[1]/div/div[5]/button[1]/span"
                                    try:
                                        comment_button = driver.find_element(By.XPATH, comment_button_xpath)
                                        comment_button.click()
                                        info("Clicked comment button")
                                        time.sleep(5)
                                    except Exception as e:
                                        warn(f"Failed to click comment button: {e}")

                                    comment_box_xpath = f"/html/body/div[1]/div[2]/div[2]/div[2]/div/main/div/div/div[2]/div/div[{i}]/div/div/div/div[3]/div/div/div/div/div[1]/div[1]/div/div/div[1]/div/p"
                                    try:
                                        comment_box = driver.find_element(By.XPATH, comment_box_xpath)
                                        comment_box.click()
                                        info("Clicked comment box")
                                        time.sleep(5)

                                        # Type comment human-like
                                        for char in comment_text:
                                            comment_box.send_keys(char)
                                            time.sleep(random.uniform(0.01, 0.05))
                                        info("Typed comment")
                                        time.sleep(5)
                                    except Exception as e:
                                        warn(f"Failed to type comment: {e}")

                                    post_comment_xpath = f"/html/body/div[1]/div[2]/div[2]/div[2]/div/main/div/div/div[2]/div/div[{i}]/div/div/div/div[3]/div/div/div/div/div[3]/div[2]/button/span"
                                    try:
                                        post_button = driver.find_element(By.XPATH, post_comment_xpath)
                                        post_button.click()
                                        info("Posted comment")
                                        time.sleep(5)
                                        like_button_xpath = f"/html/body/div[1]/div[2]/div[2]/div[2]/div/main/div/div/div[2]/div/div[{i}]/div/div/div/div[1]/div/div[5]/div/div/div/div/button/span"
                                        try:
                                            like_button = driver.find_element(By.XPATH, like_button_xpath)
                                            like_button.click()
                                            info("Clicked like button")
                                            # Now save to file
                                            try:
                                                with open(liked_file_path, "r", encoding="utf-8") as f:
                                                    data = json.load(f)
                                                data.insert(0, {"post_link": link})
                                                with open(liked_file_path, "w", encoding="utf-8") as f:
                                                    json.dump(data, f, indent=4)
                                                info("Saved post link to liked_commented.json")
                                            except Exception as e:
                                                warn(f"Failed to save to liked_commented.json: {e}")
                                        except Exception as e:
                                            warn(f"Failed to click like button: {e}")
                                    except Exception as e:
                                        warn(f"Failed to post comment: {e}")

                                except Exception as e:
                                    warn(f"Failed to generate AI comment: {e}")

                            break  # Found new link, stop
                        else:
                            info(f"Link already exists for i={i}, skipping. Link: {link}")
                    except Exception as e:
                        warn(f"Failed to extract link for i={i}: {e}")
                except Exception as e:
                    warn(f"Failed to find or get text for i={i}: {e}")
        success("Finished locating and printing text.")

        return 0

    except KeyboardInterrupt:
        info("Interrupted by user. Exiting gracefully…")
        return 0
    except Exception as exc:
        error(f"Unhandled error: {exc}")
        return 1

    finally:
        try:
            if driver:
                time.sleep(15)  # Wait 15 seconds before closing
                info("Closing browser…")
                driver.quit()
                success("Browser closed.")
        except Exception as e:
            warn(f"Failed to close browser: {e}")


if __name__ == "__main__":
    raise SystemExit(main())
