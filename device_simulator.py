"""
Android Pixel 10 Pro device simulator.

Each session gets unique identifiers (IMEI, Android ID, device fingerprint,
Chrome version patch) while the hardware identity remains "Pixel 10 Pro".

Generates realistic Client Hints, WebGL overrides, and navigator properties
so that Google's Pixel-benefit eligibility checks pass.
"""

import random
import string
import uuid

from dataclasses import dataclass, field
from typing import Optional

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
    # TAC prefix for Google Pixel devices
    tac = random.choice(["35847631", "35900012", "35250011", "86893003"])
    serial = "".join(random.choices(string.digits, k=15 - len(tac) - 1))
    partial = tac + serial
    check_digit = (10 - _luhn_checksum(partial + "0")) % 10
    return partial + str(check_digit)


def _generate_android_id() -> str:
    """Generate a 16-character hex Android ID."""
    return "".join(random.choices("0123456789abcdef", k=16))


def _generate_device_fingerprint(model: str, build_id: str,
                                  android: str) -> str:
    """Return a realistic Android build fingerprint."""
    return (
        f"google/{model.lower().replace(' ', '_')}/"
        f"{model.lower().replace(' ', '_')}:{android}/"
        f"{build_id}/eng.{random.randint(10000000, 99999999)}:user/release-keys"
    )


def _random_chrome_patch() -> str:
    """Return the actual installed Chrome version with slight patch variation.

    Uses the auto-detected version from config to avoid UA mismatch
    with the real browser binary.
    """
    actual = config.CHROME_VERSION  # e.g. "146.0.7680.80"
    parts = actual.split(".")
    if len(parts) == 4:
        # Only randomize the patch number slightly
        parts[3] = str(int(parts[3]) + random.randint(-5, 5))
        return ".".join(parts)
    return actual


def _random_build_id() -> str:
    """Pick a realistic BUILD_ID from a pool of known Pixel 10 Pro builds."""
    builds = [
        "AP4A.250405.002",
        "AP4A.250305.001",
        "AP4A.250205.004",
        "AP3A.250105.002",
        "AP3A.241205.015",
    ]
    return random.choice(builds)


# ── Pixel 10 Pro hardware constants ──────────────────────────────────────────
# These match the actual Pixel 10 Pro specs

PIXEL_10_PRO_SPECS = {
    # Screen
    "width": 412,            # CSS viewport width
    "height": 915,           # CSS viewport height
    "device_width": 1080,    # Physical resolution width
    "device_height": 2400,   # Physical resolution height
    "pixel_ratio": 2.625,    # Device pixel ratio

    # GPU (Tensor G5)
    "webgl_vendor": "Qualcomm",
    "webgl_renderer": "Adreno (TM) 750",

    # Platform
    "platform": "Linux armv8l",
    "vendor": "Google Inc.",

    # Connection
    "connection_type": "4g",
    "effective_type": "4g",
    "downlink": 10,

    # Touch
    "max_touch_points": 5,

    # Memory (GB exposed to JS)
    "device_memory": 12,
    "hardware_concurrency": 8,
}


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

    # Accept-Language for US English (most Pixel offers are US)
    accept_language: str = "en-US,en;q=0.9"

    # Locale
    locale: str = "en-US"

    def client_hints_headers(self) -> dict:
        """Return User-Agent Client Hints headers for this device.

        Google relies on Sec-CH-UA-* headers to verify the device brand,
        model and platform.  Without these, the server may treat the
        request as a generic desktop browser.
        """
        return {
            "Sec-CH-UA": (
                f'"Chromium";v="{config.CHROME_MAJOR_VERSION}", '
                f'"Google Chrome";v="{config.CHROME_MAJOR_VERSION}", '
                f'"Not:A-Brand";v="24"'
            ),
            "Sec-CH-UA-Mobile": "?1",
            "Sec-CH-UA-Platform": '"Android"',
            "Sec-CH-UA-Platform-Version": f'"{self.android_version}.0.0"',
            "Sec-CH-UA-Model": f'"{self.model}"',
            "Sec-CH-UA-Full-Version": f'"{self.chrome_version}"',
            "Sec-CH-UA-Full-Version-List": (
                f'"Chromium";v="{self.chrome_version}", '
                f'"Google Chrome";v="{self.chrome_version}", '
                f'"Not:A-Brand";v="24.0.0.0"'
            ),
            "Sec-CH-UA-Arch": '""',
            "Sec-CH-UA-Bitness": '"64"',
        }

    def as_headers(self) -> dict:
        """Return HTTP headers that identify this device."""
        headers = {
            "User-Agent": self.user_agent,
            "Accept-Language": self.accept_language,
            "Accept-Encoding": "gzip, deflate, br",
        }
        headers.update(self.client_hints_headers())
        return headers

    def navigator_overrides_js(self) -> str:
        """Return JavaScript to inject navigator/screen spoofs via CDP."""
        specs = PIXEL_10_PRO_SPECS
        return f"""
        // ── navigator overrides ──
        Object.defineProperty(navigator, 'platform', {{
            get: () => '{specs["platform"]}'
        }});
        Object.defineProperty(navigator, 'vendor', {{
            get: () => '{specs["vendor"]}'
        }});
        Object.defineProperty(navigator, 'maxTouchPoints', {{
            get: () => {specs["max_touch_points"]}
        }});
        Object.defineProperty(navigator, 'hardwareConcurrency', {{
            get: () => {specs["hardware_concurrency"]}
        }});
        Object.defineProperty(navigator, 'deviceMemory', {{
            get: () => {specs["device_memory"]}
        }});
        Object.defineProperty(navigator, 'language', {{
            get: () => '{self.locale}'
        }});
        Object.defineProperty(navigator, 'languages', {{
            get: () => ['{self.locale}', 'en']
        }});

        // ── navigator.userAgentData (critical for Google device checks) ──
        Object.defineProperty(navigator, 'userAgentData', {{
            get: () => ({{
                brands: [
                    {{ brand: "Chromium", version: "{config.CHROME_MAJOR_VERSION}" }},
                    {{ brand: "Google Chrome", version: "{config.CHROME_MAJOR_VERSION}" }},
                    {{ brand: "Not:A-Brand", version: "24" }},
                ],
                mobile: true,
                platform: "Android",
                getHighEntropyValues: (hints) => Promise.resolve({{
                    brands: [
                        {{ brand: "Chromium", version: "{config.CHROME_MAJOR_VERSION}" }},
                        {{ brand: "Google Chrome", version: "{config.CHROME_MAJOR_VERSION}" }},
                        {{ brand: "Not:A-Brand", version: "24" }},
                    ],
                    mobile: true,
                    platform: "Android",
                    platformVersion: "{self.android_version}.0.0",
                    architecture: "",
                    bitness: "64",
                    model: "{self.model}",
                    uaFullVersion: "{self.chrome_version}",
                    fullVersionList: [
                        {{ brand: "Chromium", version: "{self.chrome_version}" }},
                        {{ brand: "Google Chrome", version: "{self.chrome_version}" }},
                        {{ brand: "Not:A-Brand", version: "24.0.0.0" }},
                    ],
                }}),
                toJSON: () => ({{
                    brands: [
                        {{ brand: "Chromium", version: "{config.CHROME_MAJOR_VERSION}" }},
                        {{ brand: "Google Chrome", version: "{config.CHROME_MAJOR_VERSION}" }},
                        {{ brand: "Not:A-Brand", version: "24" }},
                    ],
                    mobile: true,
                    platform: "Android",
                }}),
            }})
        }});

        // ── Screen orientation (mobile = portrait) ──
        Object.defineProperty(screen, 'orientation', {{
            get: () => ({{
                type: 'portrait-primary',
                angle: 0,
                addEventListener: () => {{}},
                removeEventListener: () => {{}},
                dispatchEvent: () => true,
                onchange: null,
                lock: () => Promise.resolve(),
                unlock: () => {{}},
            }})
        }});

        // ── Vibration API (mobile-only) ──
        navigator.vibrate = () => true;

        // ── MediaDevices (camera + mic = real phone) ──
        if (navigator.mediaDevices) {{
            const origEnum = navigator.mediaDevices.enumerateDevices;
            navigator.mediaDevices.enumerateDevices = () => Promise.resolve([
                {{ deviceId: 'default', groupId: 'g1', kind: 'audioinput', label: '' }},
                {{ deviceId: 'cam0', groupId: 'g2', kind: 'videoinput', label: '' }},
                {{ deviceId: 'cam1', groupId: 'g3', kind: 'videoinput', label: '' }},
                {{ deviceId: 'default', groupId: 'g4', kind: 'audiooutput', label: '' }},
            ]);
        }}

        // ── connection API ──
        if (navigator.connection) {{
            Object.defineProperty(navigator.connection, 'effectiveType', {{
                get: () => '{specs["effective_type"]}'
            }});
            Object.defineProperty(navigator.connection, 'type', {{
                get: () => 'cellular'
            }});
            Object.defineProperty(navigator.connection, 'downlink', {{
                get: () => {specs["downlink"]}
            }});
        }}

        // ── screen overrides ──
        Object.defineProperty(screen, 'width', {{
            get: () => {specs["device_width"]}
        }});
        Object.defineProperty(screen, 'height', {{
            get: () => {specs["device_height"]}
        }});
        Object.defineProperty(screen, 'availWidth', {{
            get: () => {specs["device_width"]}
        }});
        Object.defineProperty(screen, 'availHeight', {{
            get: () => {specs["device_height"]}
        }});
        Object.defineProperty(screen, 'colorDepth', {{
            get: () => 24
        }});

        // ── WebGL renderer (Tensor G5 GPU) ──
        const getParameterOrig = WebGLRenderingContext.prototype.getParameter;
        WebGLRenderingContext.prototype.getParameter = function(param) {{
            if (param === 0x9245) return '{specs["webgl_vendor"]}';
            if (param === 0x9246) return '{specs["webgl_renderer"]}';
            return getParameterOrig.call(this, param);
        }};
        if (typeof WebGL2RenderingContext !== 'undefined') {{
            const getParam2Orig = WebGL2RenderingContext.prototype.getParameter;
            WebGL2RenderingContext.prototype.getParameter = function(param) {{
                if (param === 0x9245) return '{specs["webgl_vendor"]}';
                if (param === 0x9246) return '{specs["webgl_renderer"]}';
                return getParam2Orig.call(this, param);
            }};
        }}

        // ── hide automation ──
        Object.defineProperty(navigator, 'webdriver', {{
            get: () => undefined
        }});

        // ── Battery API ──
        if (navigator.getBattery) {{
            const origGetBattery = navigator.getBattery.bind(navigator);
            navigator.getBattery = () => Promise.resolve({{
                charging: true,
                chargingTime: Infinity,
                dischargingTime: Infinity,
                level: 0.87,
                addEventListener: () => {{}},
                removeEventListener: () => {{}},
                dispatchEvent: () => true,
                onchargingchange: null,
                onchargingtimechange: null,
                ondischargingtimechange: null,
                onlevelchange: null,
            }});
        }}

        // ── Timezone override ──
        const origDateTimeFormat = Intl.DateTimeFormat;
        Intl.DateTimeFormat = function(locale, options) {{
            options = options || {{}};
            options.timeZone = options.timeZone || 'America/Los_Angeles';
            return new origDateTimeFormat(locale, options);
        }};
        Intl.DateTimeFormat.prototype = origDateTimeFormat.prototype;
        Object.defineProperty(Intl.DateTimeFormat, 'supportedLocalesOf', {{
            value: origDateTimeFormat.supportedLocalesOf
        }});

        // ── Canvas fingerprint noise ──
        const origToDataURL = HTMLCanvasElement.prototype.toDataURL;
        HTMLCanvasElement.prototype.toDataURL = function(type) {{
            const ctx = this.getContext('2d');
            if (ctx) {{
                const style = ctx.fillStyle;
                ctx.fillStyle = 'rgba(0,0,{random.randint(1,3)},0.01)';
                ctx.fillRect(0, 0, 1, 1);
                ctx.fillStyle = style;
            }}
            return origToDataURL.apply(this, arguments);
        }};
        """

    def summary(self) -> str:
        """Human-readable summary for Telegram messages."""
        return (
            f"📱 <b>Device Profile</b>\n"
            f"Model: {self.model}\n"
            f"Android: {self.android_version}\n"
            f"Build: {self.build_id}\n"
            f"Chrome: {self.chrome_version}\n"
            f"Session: <code>{self.session_id[:8]}…</code>"
        )


# ── Public factory ────────────────────────────────────────────────────────────

def create_device_profile() -> DeviceProfile:
    """
    Create a fresh Pixel 10 Pro device profile with unique per-session
    identifiers and a randomised build ID.
    """
    build_id = _random_build_id()
    chrome_version = _random_chrome_patch()
    template = random.choice(config.USER_AGENT_TEMPLATES)
    user_agent = template.format(
        android=config.ANDROID_VERSION,
        model=config.DEVICE_MODEL,
        build=build_id,
        chrome=chrome_version,
    )
    fingerprint = _generate_device_fingerprint(
        config.DEVICE_MODEL,
        build_id,
        config.ANDROID_VERSION,
    )
    return DeviceProfile(
        imei=_generate_imei(),
        android_id=_generate_android_id(),
        device_fingerprint=fingerprint,
        user_agent=user_agent,
        chrome_version=chrome_version,
        build_id=build_id,
    )
