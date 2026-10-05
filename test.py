#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CHATGPT ACCOUNT CREATOR - API EDITION (MULTI-SESSION + CF BYPASS + MANUAL OTP FALLBACK)
Drives samemailread.onrender.com to get OTP via REST API
Prompts for Mailbox API key at runtime
Browsers stay open after completion
"""

import sys
import os
import time
import random
import re
import logging
import subprocess
import codecs
from datetime import datetime, timedelta
from typing import Optional, List
from urllib.parse import quote, unquote

# Force UTF-8 on Windows
if sys.platform == 'win32':
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')


# ==================== FIX DISTUTILS ====================
def fix_distutils():
    try:
        import distutils
        return True
    except ModuleNotFoundError:
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "setuptools"],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except:
            import types
            distutils = types.ModuleType('distutils')
            sys.modules['distutils'] = distutils
            distutils.version = types.ModuleType('distutils.version')
            sys.modules['distutils.version'] = distutils.version

            class LooseVersion:
                def __init__(self, vstring): self.vstring = vstring

                def __lt__(self, other): return True

                def __le__(self, other): return True

                def __eq__(self, other): return False

                def __ne__(self, other): return True

                def __gt__(self, other): return False

                def __ge__(self, other): return False

                def parse(self): return [0]

            distutils.version.LooseVersion = LooseVersion
            return True


fix_distutils()

# ==================== IMPORTS ====================
try:
    import undetected_chromedriver as uc

    UC_AVAILABLE = True
except ImportError:
    UC_AVAILABLE = False

try:
    import requests
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    import requests

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# ==================== LOGGING ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    handlers=[
        logging.FileHandler('chatgpt_creator.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


# ==================== CONFIG ====================
class Config:
    SIGNUP_URL = "https://chatgpt.com/signup"
    API_BASE_URL = "https://samemailread.onrender.com"
    HEADLESS = False
    KEEP_BROWSER_OPEN = True

    NAMES = ["James", "Maria", "David", "Sarah", "Michael", "Emma", "John", "Lisa",
             "Robert", "Anna", "William", "Olivia", "Christopher", "Amanda", "Daniel",
             "Jessica", "Matthew", "Ashley", "Anthony", "Jennifer", "Elizabeth"]

    LAST_NAMES = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
                  "Davis", "Rodriguez", "Martinez", "Wilson", "Taylor", "Anderson",
                  "Thomas", "Jackson", "White", "Harris", "Martin", "Thompson", "Moore"]

    @staticmethod
    def random_name():
        return f"{random.choice(Config.NAMES)} {random.choice(Config.LAST_NAMES)}"

    @staticmethod
    def random_age():
        return random.randint(18, 65)

    @staticmethod
    def random_dob():
        age = Config.random_age()
        today = datetime.now()
        dob = today - timedelta(days=age * 365 + random.randint(0, 364))
        return dob.strftime("%Y-%m-%d")

    @staticmethod
    def random_password():
        chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*"
        return ''.join(random.choice(chars) for _ in range(12))

    @staticmethod
    def generate_aliases(email: str, count: int) -> List[str]:
        email = unquote(email).strip()
        if '@' not in email:
            raise ValueError(f"Invalid email address provided: {email}")

        aliases = []
        username = email.split('@')[0]
        domain = email.split('@')[1]
        suffixes = ["shop", "news", "work", "personal", "social", "bills",
                    "travel", "health", "fitness", "learning", "tech", "finance",
                    "family", "friends", "projects", "work2", "extra1", "extra2", "extra3", "extra4"]
        for i in range(min(count, len(suffixes))):
            aliases.append(f"{username}+{suffixes[i]}@{domain}")
        return aliases


# ==================== ROBUST CLICK & CLOUDFLARE HELPERS ====================
def _click_any(driver, element):
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
        time.sleep(0.3)
    except Exception:
        pass
    try:
        element.click()
        return True
    except Exception:
        pass
    try:
        driver.execute_script("arguments[0].click();", element)
        return True
    except Exception:
        pass
    try:
        driver.execute_script("""
            var el = arguments[0];
            ['mousedown','mouseup','click'].forEach(function(t){
                el.dispatchEvent(new MouseEvent(t, {bubbles:true, cancelable:true, view:window}));
            });
        """, element)
        return True
    except Exception:
        return False


def handle_cloudflare_turnstile(driver, timeout=10):
    """Detects and attempts to click Cloudflare Turnstile checkboxes inside iframes."""
    logger.info("Checking for Cloudflare / Turnstile challenge...")
    start_time = time.time()

    while time.time() - start_time < timeout:
        try:
            driver.switch_to.default_content()
            frames = driver.find_elements(By.TAG_NAME, "iframe")
            for frame in frames:
                try:
                    driver.switch_to.frame(frame)
                    checkbox_selectors = [
                        "input[type='checkbox']",
                        ".mark",
                        "#challenge-stage input",
                        "iframe"
                    ]
                    for selector in checkbox_selectors:
                        elements = driver.find_elements(By.CSS_SELECTOR, selector)
                        for el in elements:
                            if el.is_displayed():
                                logger.info("🛡️ Cloudflare challenge widget found. Interacting human-like...")
                                time.sleep(random.uniform(0.8, 1.5))
                                actions = ActionChains(driver)
                                actions.move_to_element(el).pause(0.4).click().perform()
                                logger.info("✓ Clicked Cloudflare verification element")
                                driver.switch_to.default_content()
                                time.sleep(2)
                                return True
                except Exception:
                    pass
                finally:
                    driver.switch_to.default_content()

            main_checkbox = driver.find_elements(By.XPATH, "//input[@type='checkbox' or contains(@class, 'turnstile')]")
            for cb in main_checkbox:
                if cb.is_displayed():
                    time.sleep(random.uniform(0.8, 1.5))
                    cb.click()
                    driver.switch_to.default_content()
                    return True
        except Exception as e:
            logger.debug(f"CF check loop error: {e}")

        time.sleep(1)

    driver.switch_to.default_content()
    return False


def find_signup_button(driver):
    xpaths = [
        "//button[contains(normalize-space(.), 'Sign up for free')]",
        "//a[contains(normalize-space(.), 'Sign up for free')]",
        "//*[@role='button' and contains(normalize-space(.), 'Sign up for free')]",
        "//button[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'sign up')]",
        "//a[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'sign up')]",
        "//*[@role='button' and contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'sign up')]",
        "//*[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'free') and (self::button or self::a or @role='button')]",
    ]

    def _search(context):
        for xp in xpaths:
            try:
                els = context.find_elements(By.XPATH, xp)
                for el in els:
                    if el.is_displayed():
                        return el
            except Exception:
                continue
        return None

    el = _search(driver)
    if el:
        return el

    try:
        frames = driver.find_elements(By.TAG_NAME, "iframe")
        for frame in frames:
            try:
                driver.switch_to.frame(frame)
                el = _search(driver)
                if el:
                    driver.switch_to.default_content()
                    return el
            except Exception:
                pass
            finally:
                try:
                    driver.switch_to.default_content()
                except Exception:
                    pass
    except Exception:
        pass

    return None


def click_signup_button(driver, timeout=15):
    logger.info("Looking for 'Sign up for free' button...")
    time.sleep(2)

    el = find_signup_button(driver)
    if el:
        if _click_any(driver, el):
            logger.info("✓ Signup button clicked")
            time.sleep(2)
            return True
        logger.warning("Found button but couldn't click")
    return False


def wait_and_find(driver, by, value, timeout=10):
    try:
        return WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((by, value))
        )
    except Exception:
        return None


def wait_and_click(driver, by, value, timeout=10):
    try:
        el = WebDriverWait(driver, timeout).until(
            EC.element_to_be_clickable((by, value))
        )
        return _click_any(driver, el)
    except Exception:
        return False


# ==================== SAMEMAILREAD API CLIENT ====================
class SamemailreadClient:
    """Client for samemailread.onrender.com API to fetch OTPs programmatically."""

    def __init__(self, api_key: str, base_url: str = Config.API_BASE_URL, timeout: int = 30):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    @property
    def headers(self) -> dict[str, str]:
        return {"X-API-Key": self.api_key, "Accept": "application/json"}

    def fetch_otp(self, email: str, timeout: int = 45) -> Optional[str]:
        logger.info(f"Polling API for OTP for {email}...")
        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                encoded_email = quote(email, safe="")
                response = requests.get(
                    f"{self.base_url}/read/{encoded_email}",
                    headers=self.headers,
                    params={"limit": 10, "new_only": "true"},
                    timeout=self.timeout,
                )

                if response.ok:
                    data = response.json()
                    messages = data.get("messages", []) if isinstance(data, dict) else data
                    if not messages and isinstance(data, list):
                        messages = data

                    for msg in messages:
                        body = str(msg.get("body", "")) + str(msg.get("snippet", "")) + str(msg.get("subject", ""))
                        match = re.search(r'\b(\d{6})\b', body)
                        if match:
                            otp = match.group(1)
                            if otp not in ("2023", "2024", "2025", "2026"):
                                logger.info(f"✅ OTP found via API: {otp}")
                                self.mark_seen(email)
                                return otp
            except Exception as e:
                logger.debug(f"API poll error: {e}")

            time.sleep(5)

        logger.warning(f"⚠️ API polling timed out for {email}")
        return None

    def mark_seen(self, email: str):
        try:
            encoded_email = quote(email, safe="")
            requests.post(
                f"{self.base_url}/v1/read/{encoded_email}/mark-seen",
                headers=self.headers,
                timeout=self.timeout,
            )
        except Exception:
            pass


# ==================== CHATGPT CREATOR ====================
class ChatGPTCreator:
    def __init__(self, api_key: str):
        self.driver = None
        self.successful = 0
        self.failed = 0
        self.total = 0
        self.api_key = api_key
        self.api_client = SamemailreadClient(api_key)

    def setup_driver(self):
        logger.info("Starting a new ChatGPT browser session...")

        if UC_AVAILABLE:
            try:
                options = uc.ChromeOptions()
                if Config.HEADLESS:
                    options.add_argument('--headless')
                options.add_argument('--disable-blink-features=AutomationControlled')
                options.add_argument('--disable-gpu')
                options.add_argument('--no-sandbox')
                options.add_argument('--disable-dev-shm-usage')
                options.add_argument('--window-size=1200,800')

                self.driver = uc.Chrome(options=options, version_main=154, headless=Config.HEADLESS)
                self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
                logger.info("✓ Browser ready (undetected)")
                return True
            except Exception as e:
                logger.warning(f"Undetected failed: {e}")

        try:
            options = Options()
            if Config.HEADLESS:
                options.add_argument('--headless')
            options.add_argument('--disable-blink-features=AutomationControlled')
            options.add_argument('--disable-gpu')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_experimental_option('useAutomationExtension', False)

            self.driver = webdriver.Chrome(options=options)
            self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
            logger.info("✓ Browser ready (standard)")
            return True
        except Exception as e:
            logger.error(f"Driver failed: {e}")
            return False

    def create_account(self, email: str) -> bool:
        try:
            name = Config.random_name()
            age = Config.random_age()
            password = Config.random_password()

            logger.info(f"Creating account for: {email}")

            # 1) Open signup & handle initial Cloudflare
            self.driver.get(Config.SIGNUP_URL)
            time.sleep(3)
            handle_cloudflare_turnstile(self.driver, timeout=8)

            # 2) Click Sign up for free
            click_signup_button(self.driver)
            time.sleep(2)
            handle_cloudflare_turnstile(self.driver, timeout=6)

            # 3) Enter email
            email_input = None
            for selector in [
                (By.CSS_SELECTOR, "input[type='email']"),
                (By.CSS_SELECTOR, "input[name='email']"),
                (By.XPATH, "//input[@type='email']"),
                (By.XPATH, "//input[@name='email']"),
                (By.XPATH, "//input[contains(@placeholder,'email')]"),
            ]:
                email_input = wait_and_find(self.driver, *selector, timeout=5)
                if email_input:
                    break

            if not email_input:
                logger.error("✗ Email input not found")
                return False

            email_input.clear()
            email_input.send_keys(email)
            time.sleep(1)

            handle_cloudflare_turnstile(self.driver, timeout=5)

            if not wait_and_click(self.driver, By.XPATH, "//button[contains(text(),'Continue')]", timeout=3):
                email_input.send_keys(Keys.RETURN)
            time.sleep(3)

            # 4) Password (optional)
            password_input = wait_and_find(self.driver, By.CSS_SELECTOR, "input[type='password']", timeout=3)
            if password_input:
                logger.info("🔑 Password field detected")
                password_input.clear()
                password_input.send_keys(password)
                time.sleep(1)
                if not wait_and_click(self.driver, By.XPATH, "//button[contains(text(),'Continue')]", timeout=3):
                    password_input.send_keys(Keys.RETURN)
                time.sleep(2)

            # 5) Fetch OTP via samemailread API with Fallback Prompt
            logger.info("📱 Fetching OTP via API...")
            otp = self.api_client.fetch_otp(email, timeout=45)

            if not otp:
                print(f"\n⚠️ API didn't pick up the OTP automatically for {email}.")
                print("👉 Please check your email inbox/dashboard manually and enter the 6-digit code.")
                otp = input("Enter OTP manually: ").strip()
                if not otp or len(otp) != 6:
                    logger.error("✗ Invalid or missing manual OTP")
                    return False

            logger.info(f"✅ OTP: {otp}")

            # 6) Enter OTP
            otp_input = None
            for selector in [
                (By.CSS_SELECTOR, "input[autocomplete='one-time-code']"),
                (By.CSS_SELECTOR, "input[name='code']"),
                (By.XPATH, "//input[contains(@placeholder,'code')]"),
                (By.XPATH, "//input[contains(@placeholder,'verification')]"),
            ]:
                otp_input = wait_and_find(self.driver, *selector, timeout=5)
                if otp_input:
                    break

            if not otp_input:
                logger.error("✗ OTP input not found")
                return False

            for digit in otp:
                otp_input.send_keys(digit)
                time.sleep(0.1)
            time.sleep(1)

            if not wait_and_click(self.driver, By.XPATH, "//button[contains(text(),'Continue')]", timeout=3):
                otp_input.send_keys(Keys.RETURN)
            time.sleep(3)

            # 7) Name and Age
            name_input = None
            for selector in [
                (By.CSS_SELECTOR, "input[name='name']"),
                (By.XPATH, "//input[contains(@placeholder,'Name')]"),
                (By.CSS_SELECTOR, "input[autocomplete='name']"),
            ]:
                name_input = wait_and_find(self.driver, *selector, timeout=3)
                if name_input:
                    break

            if name_input:
                name_input.clear()
                name_input.send_keys(name)
                time.sleep(0.5)

            age_input = None
            for selector in [
                (By.CSS_SELECTOR, "input[name='age']"),
                (By.XPATH, "//input[contains(@placeholder,'Age')]"),
                (By.CSS_SELECTOR, "input[type='number']"),
            ]:
                age_input = wait_and_find(self.driver, *selector, timeout=3)
                if age_input:
                    break

            if age_input:
                age_input.clear()
                age_input.send_keys(str(age))
                time.sleep(0.5)

            if not wait_and_click(self.driver, By.XPATH, "//button[contains(text(),'Continue')]", timeout=3):
                try:
                    self.driver.find_element(By.TAG_NAME, "form").submit()
                except Exception:
                    pass
            time.sleep(3)

            # 8) Onboarding Continue
            logger.info("🔄 Clicking onboarding Continue...")
            for text in ['Continue', 'Next', 'Get started', "Let's go", 'All set']:
                if wait_and_click(self.driver, By.XPATH, f"//button[contains(text(),'{text}')]", timeout=2):
                    logger.info(f"✓ Clicked: {text}")
                    time.sleep(1)
                    break

            # 9) Send Hello
            logger.info("💬 Sending hello...")
            response = None
            try:
                chat_input = None
                for selector in [
                    (By.CSS_SELECTOR, "textarea[placeholder*='message']"),
                    (By.CSS_SELECTOR, "textarea#prompt-textarea"),
                    (By.CSS_SELECTOR, "div[contenteditable='true']"),
                ]:
                    chat_input = wait_and_find(self.driver, *selector, timeout=5)
                    if chat_input:
                        break

                if chat_input:
                    _click_any(self.driver, chat_input)
                    time.sleep(0.5)
                    try:
                        chat_input.clear()
                    except Exception:
                        pass
                    chat_input.send_keys("hello")
                    time.sleep(0.5)
                    chat_input.send_keys(Keys.RETURN)
                    logger.info("✓ Hello sent")
                    time.sleep(3)

                    try:
                        for elem in self.driver.find_elements(By.CSS_SELECTOR, ".markdown, .prose"):
                            if elem.is_displayed() and len(elem.text) > 10:
                                response = elem.text
                                break
                    except Exception:
                        pass
            except Exception:
                logger.warning("Could not send hello")

            with open('accounts_verified.txt', 'a', encoding='utf-8') as f:
                if response:
                    f.write(f"{email}|{password}|{name}|{age}|{otp}|VERIFIED|RESPONSE:{response[:500]}\n")
                else:
                    f.write(f"{email}|{password}|{name}|{age}|{otp}|VERIFIED\n")

            self.successful += 1
            print(f"\n✅ {email} - SUCCESS")
            return True

        except Exception as e:
            logger.error(f"Error: {e}")
            self.failed += 1
            return False

    def run(self):
        print("\n" + "=" * 60)
        print("🤖 CHATGPT ACCOUNT CREATOR (MULTI-SESSION + CF BYPASS)")
        print("=" * 60)

        print("\n📧 Enter base Outlook email:")
        base_email = input("Email: ").strip()
        if not base_email:
            return

        try:
            count = int(input("How many accounts? (e.g., 2, 3, 5...): ").strip() or "2")
        except Exception:
            count = 2

        try:
            aliases = Config.generate_aliases(base_email, count)
        except Exception as e:
            print(f"❌ Error generating aliases: {e}")
            return

        print(f"\n✅ Generated {len(aliases)} aliases:")
        for i, alias in enumerate(aliases):
            print(f"  {i + 1}. {alias}")

        print("\n" + "=" * 60)
        print("🚀 STARTING BATCH CREATION")
        print("=" * 60)

        for i, email in enumerate(aliases):
            self.total = i + 1
            print(f"\n──────────────────────────────────────────────")
            print(f"📱 Processing Account {self.total}/{len(aliases)}: {email}")
            print(f"──────────────────────────────────────────────")

            if not self.setup_driver():
                print(f"❌ ChatGPT driver setup failed for {email}")
                self.failed += 1
                continue

            self.create_account(email)

            print(f"\n🟢 Browser window for {email} is held open.")
            if i < len(aliases) - 1:
                print("⏳ Preparing next browser instance for the next account...")
                time.sleep(2)

        print("\n" + "=" * 60)
        print("📊 SUMMARY")
        print("=" * 60)
        print(f"Total Attempted: {self.total}")
        print(f"✅ Successful: {self.successful}")
        print(f"❌ Failed: {self.failed}")
        print(f"📁 Saved to: accounts_verified.txt")
        print("=" * 60)

        if Config.KEEP_BROWSER_OPEN:
            print("\n🟢 All browser windows stay open. Close them manually when done.")
            try:
                while True:
                    time.sleep(10)
            except KeyboardInterrupt:
                print("\n🔴 Closing application...")


# ==================== MAIN ====================
def main():
    print("""
    ╔═══════════════════════════════════════════╗
    ║     CHATGPT ACCOUNT CREATOR               ║
    ║     API EDITION + CLOUDFLARE BYPASS       ║
    ╚═══════════════════════════════════════════╝
    """)

    api_key = input("🔑 Enter your Mailbox API Key: ").strip()
    if not api_key:
        print("❌ API key is required to fetch OTPs. Exiting.", file=sys.stderr)
        return

    creator = ChatGPTCreator(api_key=api_key)
    creator.run()


if __name__ == "__main__":
    main()