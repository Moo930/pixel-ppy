"""
Android Pixel 10 Pro device simulator.

Each session gets unique identifiers (IMEI, Android ID, device fingerprint,
Chrome version patch) while the hardware identity remains "Pixel 10 Pro".
"""

import random
import string
import uuid

from dataclasses import dataclass, field

import config


# ── Helpers ───────────────────────────────────────────────────────────────────

def _luhn_checksum(number: str) -> int:
    """Return the Luhn check digit for a numeric string."""
    digits = [int(d) for d in number]
    odd_digits = digits[-1::-2]
    even_digits = digits[-2::-2]
    total = sum(odd_digits)
    for d in even_digits:
        total += sum(divmod(d * 2, 10))
    return total % 10


def _generate_imei() -> str:
    """Generate a syntactically valid IMEI (15 digits, Luhn-valid)."""
    # TAC prefix for a generic Android device
    tac = "35" + "".join(random.choices(string.digits, k=6))
    serial = "".join(random.choices(string.digits, k=6))
    partial = tac + serial
    check_digit = (10 - _luhn_checksum(partial + "0")) % 10
    return partial + str(check_digit)


def _generate_android_id() -> str:
    """Generate a 16-character hex Android ID."""
    return "".join(random.choices("0123456789abcdef", k=16))


def _generate_device_fingerprint(model: str, build_id: str, android: str) -> str:
    """Return a realistic Android build fingerprint."""
    return (
        f"google/{model.lower().replace(' ', '_')}/"
        f"{model.lower().replace(' ', '_')}:{android}/"
        f"{build_id}/eng.user.release-keys"
    )


def _random_chrome_patch() -> str:
    """Return a slightly randomised Chrome version string."""
    major = config.CHROME_MAJOR_VERSION
    minor = 0
    build = random.randint(6360, 6380)
    patch = random.randint(70, 100)
    return f"{major}.{minor}.{build}.{patch}"


# ── Device profile dataclass ──────────────────────────────────────────────────

@dataclass
class DeviceProfile:
    imei: str
    android_id: str
    device_fingerprint: str
    user_agent: str
    chrome_version: str
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    # Fixed Pixel 10 Pro hardware identity
    model: str = config.DEVICE_MODEL
    brand: str = config.DEVICE_BRAND
    manufacturer: str = config.DEVICE_MANUFACTURER
    android_version: str = config.ANDROID_VERSION
    android_sdk: str = config.ANDROID_SDK
    build_id: str = config.BUILD_ID

    def as_headers(self) -> dict:
        """Return HTTP headers that identify this device."""
        return {
            "User-Agent": self.user_agent,
            "X-Device-Model": self.model,
            "X-Android-ID": self.android_id,
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
        }

    def summary(self) -> str:
        """Human-readable summary for Telegram messages."""
        return (
            f"📱 *Device Profile*\n"
            f"Model: {self.model}\n"
            f"Android: {self.android_version}\n"
            f"IMEI: `{self.imei}`\n"
            f"Android ID: `{self.android_id}`\n"
            f"Session: `{self.session_id[:8]}…`"
        )


# ── Public factory ────────────────────────────────────────────────────────────

def create_device_profile() -> DeviceProfile:
    """
    Create a fresh Pixel 10 Pro device profile with unique per-session
    identifiers.
    """
    chrome_version = _random_chrome_patch()
    template = random.choice(config.USER_AGENT_TEMPLATES)
    user_agent = template.format(
        android=config.ANDROID_VERSION,
        model=config.DEVICE_MODEL,
        build=config.BUILD_ID,
        chrome=chrome_version,
    )
    fingerprint = _generate_device_fingerprint(
        config.DEVICE_MODEL,
        config.BUILD_ID,
        config.ANDROID_VERSION,
    )
    return DeviceProfile(
        imei=_generate_imei(),
        android_id=_generate_android_id(),
        device_fingerprint=fingerprint,
        user_agent=user_agent,
        chrome_version=chrome_version,
    )
