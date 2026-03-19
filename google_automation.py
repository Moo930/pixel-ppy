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

def _ensure_chromium_installed() -> tuple[str, str]:
    """Find Chromium and chromedriver.  Returns (chrome_bin, chromedriver_path).

    Raises GoogleAutomationError if either cannot be found.
    """
    import shutil

    # Check environment variables first, then system PATH
    chrome_bin = (os.environ.get("CHROME_BIN")
                  or shutil.which("chromium")
                  or shutil.which("chromium-browser")
                  or shutil.which("google-chrome"))

    chromedriver_path = (os.environ.get("CHROMEDRIVER_PATH")
                         or shutil.which("chromedriver"))

    if not chrome_bin:
        raise GoogleAutomationError(
            "Chromium is not installed. "
            "Set CHROME_BIN env var or install chromium."
        )
    if not chromedriver_path:
        raise GoogleAutomationError(
            "chromedriver is not installed. "
            "Set CHROMEDRIVER_PATH env var or install chromedriver."
        )

    return chrome_bin, chromedriver_path


def _build_driver(profile: DeviceProfile) -> webdriver.Chrome:
    """Return a headless Chrome WebDriver configured for the device profile."""
    options = Options()

    if config.HEADLESS:
        options.add_argument("--headless")  # Use old headless (less memory than --headless=new)

    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-notifications")
    options.add_argument("--window-size=390,844")  # Pixel 10 Pro screen size
    options.add_argument(f"--user-agent={profile.user_agent}")

    # ── Memory-saving flags for low-memory environments ─────────────────────
    options.add_argument("--single-process")
    options.add_argument("--disable-software-rasterizer")
    options.add_argument("--disable-features=VizDisplayCompositor")
    options.add_argument("--disable-crash-reporter")
    options.add_argument("--disable-background-networking")
    options.add_argument("--disable-default-apps")
    options.add_argument("--disable-translate")
    options.add_argument("--no-first-run")
    options.add_argument("--renderer-process-limit=1")
    options.add_argument("--js-flags=--max-old-space-size=256")

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


def _gmail_login(driver: webdriver.Chrome, email: str, password: str) -> str:
    """
    Perform Gmail / Google account login.

    Returns:
        "success"    – login completed
        "failed"     – credentials rejected or error
        "needs_totp" – TOTP / authenticator code required (driver stays on 2FA page)
    Raises GoogleAutomationError for unsupported 2FA types.
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
            page_text = driver.page_source.lower()

            # TOTP / Authenticator → can be handled interactively
            if "authenticator" in page_text or "verification code" in page_text \
                    or "enter the code" in page_text or "6-digit" in page_text:
                logger.info("TOTP 2FA detected for %s – awaiting code", email)
                return "needs_totp"

            # Other 2FA types → cannot handle, raise error
            if "security key" in page_text or "usb" in page_text:
                challenge_type = "security key"
            elif "phone" in page_text or "sms" in page_text:
                challenge_type = "SMS / phone verification"
            elif "tap yes" in page_text or "google prompt" in page_text:
                challenge_type = "Google prompt (tap Yes on your phone)"
            else:
                challenge_type = "two-step verification"

            logger.warning(
                "Unsupported 2FA for %s: %s (URL: %s)",
                email, challenge_type, current_url,
            )
            raise GoogleAutomationError(
                f"Your account requires {challenge_type}. "
                f"This bot cannot handle this type. "
                f"Please use an App Password instead."
            )

        # ── Verify login ──────────────────────────────────────────────────────
        if (
            hostname == "myaccount.google.com"
            or (hostname.endswith(".google.com") and "/u/" in path)
        ):
            logger.info("Login succeeded for %s", email)
            return "success"

        # Check for error messages
        try:
            error_el = driver.find_element(
                By.CSS_SELECTOR, '[jsname="B34EJ"], [aria-live="assertive"]'
            )
            if error_el.text:
                logger.warning("Login error detected: %s", error_el.text)
                return "failed"
        except NoSuchElementException:
            pass

        # If we're no longer on the login page, assume success
        if not (
            hostname == "accounts.google.com"
            and path.startswith("/signin")
        ):
            logger.info("Login appeared successful for %s (URL: %s)",
                        email, current_url)
            return "success"

        logger.warning("Unexpected URL after login: %s", current_url)
        return "failed"

    except TimeoutException as exc:
        logger.error("Timeout during login: %s", exc)
        return "failed"
    except WebDriverException as exc:
        logger.error("WebDriver error during login: %s", exc)
        return "failed"


def _submit_totp_code(driver: webdriver.Chrome, code: str) -> bool:
    """Enter a TOTP / authenticator code on the 2FA challenge page.

    Returns True if the code was accepted and login completed.
    """
    try:
        # Find the TOTP input field
        totp_field = None
        for selector in (
            'input[type="tel"]',           # Most common – numeric input
            'input[name="totpPin"]',       # Direct name
            'input[id="totpPin"]',         # Direct ID
            '#totpPin',
            'input[type="text"]',          # Fallback
        ):
            try:
                totp_field = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                )
                if totp_field:
                    break
            except TimeoutException:
                continue

        if not totp_field:
            logger.error("Could not find TOTP input field")
            return False

        totp_field.clear()
        totp_field.send_keys(code)
        time.sleep(1)

        # Click Next / Verify button
        for btn_selector in (
            '#totpNext',
            'button[jsname="LgbsSe"]',
            '[data-action="verify"]',
            'button[type="submit"]',
        ):
            try:
                btn = driver.find_element(By.CSS_SELECTOR, btn_selector)
                btn.click()
                break
            except NoSuchElementException:
                continue

        time.sleep(3)

        # Check if we left the challenge page
        current_url = driver.current_url
        parsed = urlparse(current_url)
        hostname = parsed.hostname or ""
        path = parsed.path or ""

        if hostname == "accounts.google.com" and "challenge" in path:
            logger.warning("Still on challenge page after TOTP – code may be wrong")
            return False

        logger.info("TOTP accepted, login completed")
        return True

    except Exception as exc:
        logger.error("Error submitting TOTP code: %s", exc)
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


def start_login(email: str, password: str,
                device: DeviceProfile) -> tuple:
    """
    Start the login process.

    Returns (driver, status) where status is:
        "success"    – login completed, ready for offer check
        "needs_totp" – TOTP code needed, driver is on 2FA page
        "failed"     – login failed

    The caller is responsible for calling driver.quit() when done.
    Raises GoogleAutomationError on startup or unsupported 2FA.
    """
    logger.info("Starting WebDriver for session %s", device.session_id)
    driver = _build_driver(device)

    try:
        status = _gmail_login(driver, email, password)
        if status == "failed":
            driver.quit()
            raise GoogleAutomationError(
                "Login failed – please check your credentials."
            )
        return driver, status
    except GoogleAutomationError:
        driver.quit()
        raise
    except Exception:
        driver.quit()
        raise


def submit_2fa_code(driver, code: str) -> bool:
    """Submit a TOTP code on a driver that is on the 2FA challenge page.

    Returns True if the code was accepted.
    """
    return _submit_totp_code(driver, code)


def check_offer_with_driver(driver) -> Optional[str]:
    """Navigate to Google One and find the Gemini Pro offer link.

    Returns the offer URL or None.
    """
    return _navigate_google_one(driver)


def close_driver(driver) -> None:
    """Safely close the WebDriver."""
    if driver:
        try:
            driver.quit()
        except Exception:
            pass

