"""
Google One automation using Selenium.

Logs into a Google account (Gmail or Google Workspace), navigates to
Google One, detects the 12-month free Gemini Pro offer, and returns
the activation / payment link.
"""

import logging
import os
import time
import re
from urllib.parse import urlparse
from typing import Optional

from selenium import webdriver
from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support.ui import WebDriverWait

import config
from device_simulator import DeviceProfile

logger = logging.getLogger(__name__)


# ── Driver factory ────────────────────────────────────────────────────────────

def _find_nix_binary(name: str) -> Optional[str]:
    """Search /nix/store for a binary by *name* (e.g. 'chromium', 'chromedriver')."""
    import glob
    for path in glob.glob(f"/nix/store/*/bin/{name}"):
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    # Also check ~/.nix-profile
    profile_path = os.path.expanduser(f"~/.nix-profile/bin/{name}")
    if os.path.isfile(profile_path) and os.access(profile_path, os.X_OK):
        return profile_path
    return None


def _ensure_chromium_installed() -> tuple[Optional[str], Optional[str]]:
    """Find or install Chromium and chromedriver.  Returns (chrome_bin, chromedriver_path)."""
    import shutil
    import subprocess

    # 1. Check environment variables
    chrome_bin = os.environ.get("CHROME_BIN")
    chromedriver_path = os.environ.get("CHROMEDRIVER_PATH")

    # 2. Check PATH
    if not chrome_bin:
        chrome_bin = (shutil.which("chromium") or shutil.which("chromium-browser")
                      or shutil.which("google-chrome"))
    if not chromedriver_path:
        chromedriver_path = shutil.which("chromedriver")

    # 3. Search Nix store
    if not chrome_bin:
        chrome_bin = _find_nix_binary("chromium")
    if not chromedriver_path:
        chromedriver_path = _find_nix_binary("chromedriver")

    # 4. Auto-install via nix-env as last resort
    if not chrome_bin or not chromedriver_path:
        logger.info("Chrome/chromedriver not found. Attempting nix-env install...")
        try:
            subprocess.run(
                ["nix-env", "-iA", "nixpkgs.chromium", "nixpkgs.chromedriver"],
                check=True, capture_output=True, timeout=120,
            )
            # Re-check after install
            if not chrome_bin:
                chrome_bin = (shutil.which("chromium")
                              or _find_nix_binary("chromium"))
            if not chromedriver_path:
                chromedriver_path = (shutil.which("chromedriver")
                                     or _find_nix_binary("chromedriver"))
            logger.info("nix-env install completed.")
        except Exception as exc:
            logger.warning("nix-env install failed: %s", exc)

    return chrome_bin, chromedriver_path


def _build_driver(profile: DeviceProfile) -> webdriver.Chrome:
    """Return a headless Chrome WebDriver configured for the device profile."""
    options = Options()

    if config.HEADLESS:
        options.add_argument("--headless=new")

    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-notifications")
    options.add_argument("--window-size=390,844")  # Pixel 10 Pro screen size
    options.add_argument(f"--user-agent={profile.user_agent}")

    # ── Locate Chrome/Chromium and chromedriver ───────────────────────────
    chrome_bin, chromedriver_path = _ensure_chromium_installed()

    if chrome_bin:
        options.binary_location = chrome_bin
        logger.info("Using Chrome binary: %s", chrome_bin)
    else:
        logger.warning("No Chrome/Chromium found – driver may fail to start.")

    # Mobile emulation – Pixel 10 Pro viewport
    mobile_emulation = {
        "deviceMetrics": {"width": 390, "height": 844, "pixelRatio": 3.0},
        "userAgent": profile.user_agent,
    }
    options.add_experimental_option("mobileEmulation", mobile_emulation)

    # Suppress automation flags
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument("--disable-blink-features=AutomationControlled")

    # ── Create driver ─────────────────────────────────────────────────────
    if chromedriver_path:
        logger.info("Using chromedriver: %s", chromedriver_path)
        service = Service(chromedriver_path)
        driver = webdriver.Chrome(service=service, options=options)
    else:
        logger.warning("No chromedriver found – using Selenium manager fallback.")
        driver = webdriver.Chrome(options=options)

    driver.implicitly_wait(config.IMPLICIT_WAIT)
    driver.set_page_load_timeout(config.PAGE_LOAD_TIMEOUT)
    return driver


# ── Login helper ──────────────────────────────────────────────────────────────

def _wait_for(driver: webdriver.Chrome, by: str, value: str,
               timeout: int = config.WEBDRIVER_TIMEOUT) -> WebElement:
    """Return element after waiting for it to be clickable."""
    return WebDriverWait(driver, timeout).until(
        EC.element_to_be_clickable((by, value))
    )


def _gmail_login(driver: webdriver.Chrome, email: str, password: str) -> bool:
    """
    Perform Gmail / Google account login.

    Returns True on apparent success, False on detectable failure.
    """
    try:
        driver.get(config.GMAIL_LOGIN_URL)
        time.sleep(2)

        # ── Email step ────────────────────────────────────────────────────────
        email_field = _wait_for(driver, By.CSS_SELECTOR,
                                'input[type="email"]')
        email_field.clear()
        email_field.send_keys(email)

        next_btn = _wait_for(driver, By.ID, "identifierNext")
        next_btn.click()
        time.sleep(2)

        # ── Password step ─────────────────────────────────────────────────────
        password_field = _wait_for(driver, By.CSS_SELECTOR,
                                   'input[type="password"]')
        password_field.clear()
        password_field.send_keys(password)

        pw_next = _wait_for(driver, By.ID, "passwordNext")
        pw_next.click()
        time.sleep(3)

        # ── Detect 2FA / verification challenges ─────────────────────────────
        current_url = driver.current_url
        parsed = urlparse(current_url)
        hostname = parsed.hostname or ""
        path = parsed.path or ""

        # Known 2FA challenge URL patterns
        _2fa_path_patterns = (
            "/signin/v2/challenge",   # general challenge page
            "/signin/challenge",      # alternate challenge path
            "/v2/challenge",          # short variant
        )

        if hostname == "accounts.google.com" and any(
            p in path for p in _2fa_path_patterns
        ):
            # Try to detect the specific 2FA type for a better message
            challenge_type = "two-step verification"
            page_text = driver.page_source.lower()

            if "authenticator" in page_text or "verification code" in page_text:
                challenge_type = "Authenticator app / verification code"
            elif "security key" in page_text or "usb" in page_text:
                challenge_type = "security key"
            elif "phone" in page_text or "sms" in page_text:
                challenge_type = "SMS / phone verification"
            elif "tap yes" in page_text or "google prompt" in page_text:
                challenge_type = "Google prompt (tap Yes on your phone)"

            logger.warning(
                "2FA challenge detected for %s: %s (URL: %s)",
                email, challenge_type, current_url,
            )
            raise GoogleAutomationError(
                f"Your account requires {challenge_type}. "
                f"This bot cannot handle two-step verification. "
                f"Please disable 2FA temporarily or use an App Password."
            )

        # ── Verify login ──────────────────────────────────────────────────────
        if (
            hostname == "myaccount.google.com"
            or (hostname.endswith(".google.com") and "/u/" in path)
        ):
            logger.info("Login succeeded for %s", email)
            return True

        # Check for error messages
        try:
            error_el = driver.find_element(
                By.CSS_SELECTOR, '[jsname="B34EJ"], [aria-live="assertive"]'
            )
            if error_el.text:
                logger.warning("Login error detected: %s", error_el.text)
                return False
        except NoSuchElementException:
            pass

        # If we're no longer on the login page, assume success
        if not (
            hostname == "accounts.google.com"
            and path.startswith("/signin")
        ):
            logger.info("Login appeared successful for %s (URL: %s)",
                        email, current_url)
            return True

        logger.warning("Unexpected URL after login: %s", current_url)
        return False

    except TimeoutException as exc:
        logger.error("Timeout during login: %s", exc)
        return False
    except WebDriverException as exc:
        logger.error("WebDriver error during login: %s", exc)
        return False


# ── Offer detection ───────────────────────────────────────────────────────────


def _is_valid_offer_url(href: str) -> bool:
    """Return True if *href* belongs to a whitelisted offer domain.

    When ``config.OFFER_DOMAIN_WHITELIST`` is empty every URL is accepted.
    """
    whitelist = config.OFFER_DOMAIN_WHITELIST
    if not whitelist:
        return bool(href)
    try:
        hostname = urlparse(href).hostname or ""
        return any(
            hostname == d or hostname.endswith("." + d)
            for d in whitelist
        )
    except Exception:
        return False


def _extract_payment_link(driver: webdriver.Chrome) -> Optional[str]:
    """
    Scan the current page for a Gemini Pro offer / activation link.

    Strategy:
    1. Look for anchor tags whose text or aria-label contains offer keywords.
    2. Fall back to scanning all links for 'gemini' or 'upgrade' patterns.
    3. Check button / CTA elements for offer text.

    All strategies filter links through ``_is_valid_offer_url`` to avoid
    false positives from generic keywords matching unrelated pages.
    """
    keywords = config.GEMINI_OFFER_KEYWORDS

    # -- Strategy 1: anchor text / aria-label match ---------------------------
    all_links = driver.find_elements(By.TAG_NAME, "a")
    for link in all_links:
        try:
            text = (link.text + " " + (link.get_attribute("aria-label") or "")).lower()
            href = link.get_attribute("href") or ""
            if any(kw in text for kw in keywords) and _is_valid_offer_url(href):
                logger.info("Found offer link via text match: %s", href)
                return href
        except Exception:
            continue

    # -- Strategy 2: URL pattern scan -----------------------------------------
    url_patterns = re.compile(
        r"(gemini|upgrade|activate|offer|redeem|trial|checkout)",
        re.IGNORECASE,
    )
    for link in all_links:
        try:
            href = link.get_attribute("href") or ""
            if url_patterns.search(href) and _is_valid_offer_url(href):
                logger.info("Found offer link via URL pattern: %s", href)
                return href
        except Exception:
            continue

    # -- Strategy 3: button / CTA elements ------------------------------------
    buttons = driver.find_elements(By.CSS_SELECTOR, "button, [role='button']")
    for btn in buttons:
        try:
            text = btn.text.lower()
            if any(kw in text for kw in keywords):
                # Try to find parent anchor
                try:
                    parent_link = btn.find_element(By.XPATH, "ancestor::a")
                    href = parent_link.get_attribute("href") or ""
                    if _is_valid_offer_url(href):
                        logger.info("Found offer link via button parent: %s", href)
                        return href
                except NoSuchElementException:
                    pass
                # Return current URL as fallback (user will land on offer page)
                current = driver.current_url
                if _is_valid_offer_url(current):
                    logger.info("Found offer CTA button on page: %s", current)
                    return current
        except Exception:
            continue

    return None


def _navigate_google_one(driver: webdriver.Chrome) -> Optional[str]:
    """
    Navigate to Google One and attempt to find the Gemini Pro offer link.

    Returns the payment/activation URL or None if not found.
    """
    for url in (config.GOOGLE_ONE_URL, config.GOOGLE_ONE_OFFERS_URL):
        try:
            logger.info("Navigating to %s", url)
            driver.get(url)
            time.sleep(3)

            # Dismiss cookie/consent banners if present
            for selector in (
                '[aria-label="Accept all"]',
                'button[jsname="higCR"]',
                '[data-action="accept"]',
            ):
                try:
                    btn = driver.find_element(By.CSS_SELECTOR, selector)
                    btn.click()
                    time.sleep(1)
                    break
                except NoSuchElementException:
                    pass

            link = _extract_payment_link(driver)
            if link:
                return link

        except (TimeoutException, WebDriverException) as exc:
            logger.warning("Error accessing %s: %s", url, exc)

    return None


# ── Public API ────────────────────────────────────────────────────────────────

class GoogleAutomationError(Exception):
    """Raised when automation encounters an unrecoverable error."""


def check_gemini_offer(email: str, password: str,
                       device: DeviceProfile) -> Optional[str]:
    """
    Main entry point.

    Logs into *email* / *password* using the supplied *device* profile,
    navigates to Google One, and returns the Gemini Pro offer link (or None).

    Raises :class:`GoogleAutomationError` if the driver cannot be started or
    the login step fails with an error.
    """
    driver: Optional[webdriver.Chrome] = None
    try:
        logger.info("Starting WebDriver for session %s", device.session_id)
        driver = _build_driver(device)

        logged_in = _gmail_login(driver, email, password)
        if not logged_in:
            raise GoogleAutomationError(
                "Login failed – please check your credentials."
            )

        offer_link = _navigate_google_one(driver)
        return offer_link

    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
