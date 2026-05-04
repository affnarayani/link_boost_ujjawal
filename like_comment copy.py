import time
import random
import re
import json
import os
import subprocess
import sys
from playwright.sync_api import expect
from login import login_and_get_context
from huggingface_hub import InferenceClient

# --- HF Client Setup (NO HARDCODE TOKEN) ---
HF_TOKEN = os.getenv("HF_TOKEN")

if not HF_TOKEN:
    raise ValueError("HF_TOKEN not found in environment variables")

client = InferenceClient(
    model="meta-llama/Meta-Llama-3-8B-Instruct",
    token=HF_TOKEN
)

MAX_RETRIES = 3

def get_posted_links():
    file_path = 'liked_commented.json'
    if not os.path.exists(file_path):
        return []
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return [item['post_link'] for item in data if 'post_link' in item]
    except Exception as e:
        print(f"[ERROR] JSON read failed: {e}", flush=True)
        return []

def save_to_json_top(new_link):
    file_path = 'liked_commented.json'
    data = []
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except:
            data = []
    
    data.insert(0, {"post_link": new_link})
    
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)
    print(f"[SUCCESS] Saved to JSON: {new_link}", flush=True)

# --- HF COMMENT GENERATION ---
def generate_ai_comment(content):
    try:
        prompt = (
            f"Read and analyze the content, then write a 30-word viral LinkedIn-style comment that reflects deep understanding and adds a sharp, thought-provoking opinion that encourages engagement."
            f"Comment only, no quotes, no asterisks, no prefix.\nContent: {content}"
        )

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = client.chat.completions.create(
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=80,
                    temperature=0.7
                )

                result = response.choices[0].message.content
                clean_comment = result.replace('*', '').replace('"', '').strip()
                return clean_comment

            except Exception as e:
                err = str(e)
                print("[ERROR]", err, flush=True)

                if "429" in err.lower():
                    print("[WAIT] 10 sec...", flush=True)
                    time.sleep(10)
                    continue

                if attempt < MAX_RETRIES:
                    time.sleep(5)
                else:
                    break

        raise Exception("HF comment generation failed")

    except Exception as e:
        print(f"[ERROR] HF Generation failed: {e}", flush=True)
        raise Exception("HF comment generation failed")


def extract_single_new_share_link():
    pw, browser, context, page = login_and_get_context()

    try:
        already_posted = get_posted_links()
        print(f"[INFO] Loaded {len(already_posted)} links from JSON.", flush=True)

        print("[INFO] Waiting for LinkedIn Feed to settle...", flush=True)
        time.sleep(random.uniform(8, 12))

        workspace = page.locator('#workspace')
        menu_pattern = re.compile(r"Open control menu for post by .*", re.IGNORECASE)
        control_menu_locator = page.get_by_role('button', name=menu_pattern)

        target_link = None 

        for i in range(6):
            if target_link: break 

            workspace.focus()
            page.keyboard.press("PageDown")
            page.evaluate("document.querySelector('#workspace').scrollBy(0, 1000)")
            print(f"[ACTION] Scroll {i+1}/6...", flush=True)
            time.sleep(5)

            menus = control_menu_locator.all()
            for menu in menus:
                if target_link: break 
                
                try:
                    if menu.is_visible():
                        menu.scroll_into_view_if_needed()
                        menu.click()
                        time.sleep(2)

                        embed_item = page.get_by_role('menuitem', name='Embed this post')
                        
                        if embed_item.count() > 0:
                            embed_item.click()

                            modal_heading = page.get_by_role('heading', name='Embed this post')
                            expect(modal_heading).to_be_visible(timeout=15000)
                            
                            embed_textbox = page.locator("#feed-components-shared-embed-modal__snippet")
                            expect(embed_textbox).to_be_visible(timeout=10000)
                            
                            raw_embed = None
                            for _ in range(20):
                                val = embed_textbox.input_value()
                                if val and "iframe" in val.lower():
                                    raw_embed = val
                                    break
                                time.sleep(0.5)

                            if raw_embed:
                                match = re.search(r'src="([^"]+)"', raw_embed)
                                if match:
                                    full_url = match.group(1)
                                    base_url = full_url.split('?')[0]
                                    final_link = base_url.replace('/embed/', '/')
                                    
                                    if "urn:li:share:" in final_link:
                                        if final_link not in already_posted:
                                            print(f"\n[NEW POST FOUND]: {final_link}", flush=True)
                                            
                                            page.get_by_text('Embed full post').click()
                                            time.sleep(15)

                                            embed_iframe = page.frame_locator('iframe[title="Embed a post iframe"]')
                                            commentary_loc = embed_iframe.locator('[data-test-id="main-feed-activity-embed-card__commentary"]')
                                            content = commentary_loc.inner_text() if commentary_loc.count() > 0 else ""
                                            
                                            if len(re.findall(r'[A-Za-z]', content)) < 60:
                                                print("[SKIP] Content too short. Closing modal...", flush=True)
                                                page.keyboard.press("Escape")
                                                time.sleep(2)
                                                continue

                                            more_btn = embed_iframe.get_by_text('…more')
                                            if more_btn.count() > 0:
                                                expect(more_btn).to_be_hidden(timeout=30000)

                                            ai_comment = generate_ai_comment(content)
                                            print(f"[AI COMMENT]: {ai_comment}", flush=True)

                                            with context.expect_page() as new_page_info:
                                                embed_iframe.get_by_role('link', name='Comment', exact=True).click()
                                            new_tab = new_page_info.value
                                            new_tab.bring_to_front()
                                            
                                            print("[ACTION] Waiting for page load...", flush=True)
                                            new_tab.wait_for_load_state("networkidle")
                                            time.sleep(15)

                                            print("[ACTION] Attempting to Like...", flush=True)
                                            like_btn = new_tab.get_by_role('button', name='React Like', exact=True)
                                            if like_btn.is_visible():
                                                like_btn.click()
                                                print("[SUCCESS] Post Liked.", flush=True)
                                                time.sleep(5)
                                            else:
                                                print("[WARNING] Like button not found or already liked.", flush=True)

                                            comment_box = new_tab.get_by_role('textbox', name='Text editor for creating').get_by_role('paragraph')
                                            comment_box.click()
                                            comment_box.fill(ai_comment)
                                            time.sleep(2)

                                            for _ in range(3):
                                                new_tab.keyboard.press("Tab")
                                                time.sleep(2)

                                            new_tab.keyboard.press("Enter")
                                            time.sleep(15)
                                            new_tab.close()

                                            save_to_json_top(final_link)
                                            target_link = final_link
                                            page.keyboard.press("Escape")
                                            break 
                                        else:
                                            print(f"[SKIP] Already posted: {final_link[-20:]}", flush=True)
                                    else:
                                        print(f"[IGNORE] Not a 'share' link.", flush=True)
                            
                            if not target_link:
                                page.keyboard.press("Escape")
                                time.sleep(2)
                        else:
                            page.keyboard.press("Escape")
                
                except Exception as e:
                    page.keyboard.press("Escape")
                    continue

        print("\n" + "="*70, flush=True)
        if target_link:
            print(f"RESULT: {target_link}", flush=True)
        else:
            print("RESULT: No new eligible share links found in 6 scrolls.", flush=True)
            sys.exit(1)
        print("="*70, flush=True)

    except Exception as e:
        print(f"[ERROR] Logic failed: {e}", flush=True)
        sys.exit(1)
    finally:
        browser.close()
        pw.stop()

if __name__ == "__main__":
    extract_single_new_share_link()