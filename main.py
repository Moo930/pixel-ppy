"""
Telegram Bot entry point for the Pixel 10 Pro Google One Gemini Bot.

Commands:
  /start        – Show welcome message and available commands
  /login        – Begin credential capture flow (email → password)
  /logout       – Clear stored credentials and session data
  /check_offer  – Run Google One automation and look for Gemini Pro offer
  /get_link     – Show the last captured offer link
  /status       – Show current session status and device profile

Supports both Gmail (user@gmail.com) and Google Workspace (user@company.com)
accounts.
"""

import asyncio
import logging
import os
import re
import sys
import time

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

import config
from device_simulator import create_device_profile
from google_automation import (
    GoogleAutomationError,
    start_login,
    submit_2fa_code,
    check_offer_with_driver,
    close_driver,
)

# ── Logging ───────────────────────────────────────────────────────────────────
from logging.handlers import RotatingFileHandler

_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(_LOG_DIR, exist_ok=True)

_formatter = logging.Formatter(config.LOG_FORMAT)

# Console handler
_console_handler = logging.StreamHandler()
_console_handler.setFormatter(_formatter)

# File handler (5 MB per file, keep 3 backups)
_file_handler = RotatingFileHandler(
    os.path.join(_LOG_DIR, "bot.log"),
    maxBytes=5 * 1024 * 1024,
    backupCount=3,
    encoding="utf-8",
)
_file_handler.setFormatter(_formatter)

logging.basicConfig(
    level=config.LOG_LEVEL,
    handlers=[_console_handler, _file_handler],
)
logger = logging.getLogger(__name__)

# ── Conversation states ───────────────────────────────────────────────────────
AWAIT_EMAIL, AWAIT_PASSWORD = range(2)
AWAIT_2FA_CODE = 10  # Separate state for 2FA code input

# ── Rate limiting & concurrency ───────────────────────────────────────────────
# Per-user cooldown: maps chat_id → last /check_offer timestamp
_LAST_CHECK_TIME: dict[int, float] = {}
CHECK_OFFER_COOLDOWN = 5 * 60  # 5 minutes between checks per user

# Limit the number of simultaneous Chrome instances (1 for ≤4GB RAM servers)
_CHROME_SEMAPHORE = asyncio.Semaphore(1)

# ── Session storage ───────────────────────────────────────────────────────────
# In-memory dict keyed by Telegram chat_id.
# Values: {"email": bytearray, "password": bytearray, "device": DeviceProfile,
#          "offer_link": str|None, "created_at": float}
SESSION_STORE: dict[int, dict] = {}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_session(chat_id: int) -> dict:
    """Return (creating if absent) the session dict for *chat_id*.

    Automatically purges the session if it has exceeded the TTL.
    """
    session = SESSION_STORE.get(chat_id)
    if session and _is_session_expired(session):
        logger.info("Session expired for chat %s – purging", chat_id)
        _clear_session(chat_id)
        session = None
    if session is None:
        SESSION_STORE[chat_id] = {}
    return SESSION_STORE[chat_id]


def _is_session_expired(session: dict) -> bool:
    """Return True if *session* has exceeded the configured TTL."""
    created = session.get("created_at")
    if created is None:
        return False
    return (time.time() - created) > config.SESSION_TTL_SECONDS


def _secure_wipe(data: bytearray) -> None:
    """Zero-fill a bytearray in-place so the original bytes are unrecoverable."""
    for i in range(len(data)):
        data[i] = 0


def _clear_session(chat_id: int) -> None:
    """Securely wipe credentials and remove the session for *chat_id*."""
    session = SESSION_STORE.pop(chat_id, None)
    if session is None:
        return
    # Securely overwrite bytearray credentials in-place
    for key in ("password", "email"):
        val = session.get(key)
        if isinstance(val, bytearray):
            _secure_wipe(val)
    session.clear()
    logger.debug("Session cleared for chat %s", chat_id)


def _purge_expired_sessions() -> int:
    """Remove all expired sessions.  Returns the number purged."""
    expired = [
        cid for cid, sess in SESSION_STORE.items()
        if _is_session_expired(sess)
    ]
    for cid in expired:
        _clear_session(cid)
    if expired:
        logger.info("Purged %d expired session(s)", len(expired))
    return len(expired)


# ── Handlers ──────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send welcome message with command menu."""
    await update.message.reply_text(
        "🤖 *Pixel 10 Pro Google One Bot*\n\n"
        "This bot simulates a Google Pixel 10 Pro (Android 16) device, "
        "logs into your Google account, and retrieves the *12-month free "
        "Gemini Pro* offer link from Google One.\n\n"
        "📋 *Available Commands:*\n"
        "• /login – Enter your Google account credentials\n"
        "• /logout – Clear stored credentials\n"
        "• /check\\_offer – Detect the Gemini Pro offer\n"
        "• /get\\_link – Show the last captured offer link\n"
        "• /status – View current session \u0026 device info\n\n"
        "💡 *Tip:* Both Gmail and Google Workspace accounts are supported.\n\n"
        "⚠️ *Privacy Note:* Credentials are held in memory only for the "
        "duration of the session and never stored persistently.",
        parse_mode="Markdown",
    )


# ── /login conversation ───────────────────────────────────────────────────────

async def login_start(update: Update,
                      context: ContextTypes.DEFAULT_TYPE) -> int:
    """Begin the login conversation – ask for email."""
    await update.message.reply_text(
        "📧 Please enter your Google account email "
        "(Gmail or Google Workspace):",
        reply_markup=ReplyKeyboardRemove(),
    )
    return AWAIT_EMAIL


async def login_email(update: Update,
                      context: ContextTypes.DEFAULT_TYPE) -> int:
    """Store the email and ask for password."""
    email = update.message.text.strip()

    # Basic email format validation (Gmail and Google Workspace accounts)
    if not re.match(r'^[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}$', email, re.IGNORECASE):
        await update.message.reply_text(
            "⚠️ Please enter a valid email address "
            "(e.g. user@gmail.com or user@company.com)."
        )
        return AWAIT_EMAIL

    # Optional domain restriction (empty list = accept any domain)
    allowed = config.ALLOWED_EMAIL_DOMAINS
    if allowed:
        domain = email.rsplit("@", 1)[1].lower()
        if domain not in [d.lower() for d in allowed]:
            domains_str = ", ".join(f"@{d}" for d in allowed)
            await update.message.reply_text(
                f"⚠️ Only the following email domains are accepted: "
                f"{domains_str}\n\nPlease try again."
            )
            return AWAIT_EMAIL

    context.user_data["pending_email"] = email
    await update.message.reply_text(
        f"✅ Email received: `{email}`\n\n🔒 Now enter your password:",
        parse_mode="Markdown",
    )
    return AWAIT_PASSWORD


async def login_password(update: Update,
                         context: ContextTypes.DEFAULT_TYPE) -> int:
    """Store credentials, generate a new device profile, and finish."""
    chat_id = update.effective_chat.id
    password = update.message.text.strip()
    email = context.user_data.pop("pending_email", "")

    session = _get_session(chat_id)
    # Store credentials as bytearray for secure in-place wiping
    session["email"] = bytearray(email.encode("utf-8"))
    session["password"] = bytearray(password.encode("utf-8"))
    session["device"] = create_device_profile()
    session["offer_link"] = None
    session["created_at"] = time.time()

    # Delete the message containing the password for security
    try:
        await update.message.delete()
    except Exception:
        pass

    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            "✅ *Credentials saved* and a new Pixel 10 Pro device profile has "
            "been created for this session.\n\n"
            + session["device"].summary()
            + "\n\nUse /check\\_offer to search for the Gemini Pro offer."
        ),
        parse_mode="Markdown",
    )
    return ConversationHandler.END


async def login_cancel(update: Update,
                       context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the login conversation."""
    context.user_data.pop("pending_email", None)
    await update.message.reply_text(
        "❌ Login cancelled.",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ConversationHandler.END


# ── /logout ───────────────────────────────────────────────────────────────────

async def logout(update: Update,
                 context: ContextTypes.DEFAULT_TYPE) -> None:
    """Clear stored credentials and destroy the session."""
    chat_id = update.effective_chat.id
    if chat_id in SESSION_STORE:
        _clear_session(chat_id)
        await update.message.reply_text(
            "🔒 Credentials and session data have been securely cleared."
        )
    else:
        await update.message.reply_text(
            "ℹ️ No active session to clear."
        )


# ── /check_offer ──────────────────────────────────────────────────────────────

async def _report_offer(update_or_chat_id, context, session, offer_link) -> None:
    """Send the offer result message."""
    chat_id = (update_or_chat_id if isinstance(update_or_chat_id, int)
               else update_or_chat_id.effective_chat.id)
    if offer_link:
        session["offer_link"] = offer_link
        text = (
            "🎉 <b>Gemini Pro Offer Found!</b>\n\n"
            "Click the link below to activate your 12-month free Gemini Pro:\n\n"
            f"🔗 {offer_link}\n\n"
            "Use /get_link to retrieve this link again."
        )
        try:
            await context.bot.send_message(
                chat_id=chat_id, text=text, parse_mode="HTML",
            )
        except Exception:
            # Fallback: send without formatting
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"🎉 Gemini Pro Offer Found!\n\n🔗 {offer_link}\n\nUse /get_link to retrieve this link again.",
            )
    else:
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "😔 No active Gemini Pro offer was detected on your Google One "
                "account at this time.\n\n"
                "The offer may not be available for your account region or may "
                "have already been activated. Try again later."
            ),
        )


async def check_offer(update: Update,
                      context: ContextTypes.DEFAULT_TYPE) -> int:
    """Run Google One automation and report the result."""
    chat_id = update.effective_chat.id
    session = _get_session(chat_id)

    if not session.get("email") or not session.get("password"):
        await update.message.reply_text(
            "⚠️ No credentials found. Please use /login first."
        )
        return ConversationHandler.END

    # ── Rate limit check ──────────────────────────────────────────────────
    last_check = _LAST_CHECK_TIME.get(chat_id, 0)
    elapsed = time.time() - last_check
    if elapsed < CHECK_OFFER_COOLDOWN:
        remaining = int(CHECK_OFFER_COOLDOWN - elapsed)
        mins, secs = divmod(remaining, 60)
        await update.message.reply_text(
            f"⏳ Please wait {mins}m {secs}s before checking again."
        )
        return ConversationHandler.END
    _LAST_CHECK_TIME[chat_id] = time.time()

    # ── Concurrency check ─────────────────────────────────────────────────
    if _CHROME_SEMAPHORE.locked():
        await update.message.reply_text(
            "🔄 The system is currently at maximum capacity. "
            "Please try again in a minute."
        )
        _LAST_CHECK_TIME.pop(chat_id, None)
        return ConversationHandler.END

    device = session.get("device")
    if not device:
        device = create_device_profile()
        session["device"] = device

    await update.message.reply_text(
        "⏳ Launching Pixel 10 Pro device simulator and logging in…\n"
        "This may take up to 60 seconds."
    )

    try:
        async with _CHROME_SEMAPHORE:
            # Decode bytearray credentials to str for Selenium
            email_str = bytes(session["email"]).decode("utf-8")
            pw_str = bytes(session["password"]).decode("utf-8")

            # Start login in a thread
            driver, status = await asyncio.to_thread(
                start_login, email_str, pw_str, device,
            )

            if status == "needs_totp":
                # Store driver in session for 2FA continuation
                session["_driver"] = driver
                await update.message.reply_text(
                    "🔐 *Two-Factor Authentication Required*\n\n"
                    "Please enter your 6-digit authenticator code:",
                    parse_mode="Markdown",
                )
                return AWAIT_2FA_CODE

            # Login succeeded – check offer
            try:
                offer_link = await asyncio.to_thread(
                    check_offer_with_driver, driver,
                )
            finally:
                close_driver(driver)

    except GoogleAutomationError as exc:
        await update.message.reply_text(f"❌ *Error:* {exc}", parse_mode="Markdown")
        return ConversationHandler.END
    except Exception as exc:
        logger.exception("Unexpected error in check_offer for chat %s", chat_id)
        await update.message.reply_text(
            f"❌ An unexpected error occurred: {exc}"
        )
        return ConversationHandler.END
    finally:
        # Securely wipe password after use
        pw = session.get("password")
        if isinstance(pw, bytearray):
            _secure_wipe(pw)
        session.pop("password", None)

    await _report_offer(update, context, session, offer_link)
    return ConversationHandler.END


async def handle_2fa_code(update: Update,
                          context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle the TOTP code submitted by the user during 2FA."""
    chat_id = update.effective_chat.id
    session = _get_session(chat_id)
    code = update.message.text.strip()

    # Delete the message containing the code for security
    try:
        await update.message.delete()
    except Exception:
        pass

    driver = session.pop("_driver", None)
    if not driver:
        await context.bot.send_message(
            chat_id=chat_id,
            text="⚠️ Session expired. Please run /check\_offer again.",
        )
        return ConversationHandler.END

    # Validate code format
    if not code.isdigit() or len(code) != 6:
        await context.bot.send_message(
            chat_id=chat_id,
            text="⚠️ Invalid code. Please enter a 6-digit number.",
        )
        session["_driver"] = driver  # Put driver back
        return AWAIT_2FA_CODE

    await context.bot.send_message(
        chat_id=chat_id,
        text="🔄 Verifying code…",
    )

    try:
        async with _CHROME_SEMAPHORE:
            accepted = await asyncio.to_thread(
                submit_2fa_code, driver, code,
            )

            if not accepted:
                close_driver(driver)
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="❌ Code rejected. Please run /check\_offer again.",
                )
                return ConversationHandler.END

            # 2FA passed – check offer
            try:
                offer_link = await asyncio.to_thread(
                    check_offer_with_driver, driver,
                )
            finally:
                close_driver(driver)

    except Exception as exc:
        logger.exception("Error in 2FA for chat %s", chat_id)
        close_driver(driver)
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"❌ Error: {exc}",
        )
        return ConversationHandler.END
    finally:
        pw = session.get("password")
        if isinstance(pw, bytearray):
            _secure_wipe(pw)
        session.pop("password", None)

    await _report_offer(chat_id, context, session, offer_link)
    return ConversationHandler.END


async def cancel_2fa(update: Update,
                     context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel 2FA input and close the driver."""
    chat_id = update.effective_chat.id
    session = _get_session(chat_id)
    driver = session.pop("_driver", None)
    close_driver(driver)
    await update.message.reply_text("❌ 2FA cancelled.")
    return ConversationHandler.END


# ── /get_link ─────────────────────────────────────────────────────────────────

async def get_link(update: Update,
                   context: ContextTypes.DEFAULT_TYPE) -> None:
    """Return the last captured offer link for this session."""
    chat_id = update.effective_chat.id
    session = _get_session(chat_id)
    link = session.get("offer_link")

    if link:
        await update.message.reply_text(
            f"🔗 <b>Last captured offer link:</b>\n\n{link}",
            parse_mode="HTML",
        )
    else:
        await update.message.reply_text(
            "ℹ️ No offer link has been captured yet. "
            "Use /check\\_offer to search for the Gemini Pro offer.",
            parse_mode="Markdown",
        )


# ── /status ───────────────────────────────────────────────────────────────────

async def status(update: Update,
                 context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show current session and device profile summary."""
    chat_id = update.effective_chat.id

    if chat_id not in SESSION_STORE or not SESSION_STORE[chat_id]:
        await update.message.reply_text(
            "ℹ️ No active session. Use /login to get started."
        )
        return

    session = SESSION_STORE[chat_id]

    email_raw = session.get("email", "—")
    # Decode bytearray email for display
    if isinstance(email_raw, bytearray):
        email = bytes(email_raw).decode("utf-8")
    else:
        email = str(email_raw) if email_raw else "—"
    has_creds = bool(session.get("email") and session.get("password"))
    offer_link = session.get("offer_link")
    device = session.get("device")

    lines = [
        "📊 *Session Status*\n",
        f"Account: `{email}`",
        f"Credentials loaded: {'✅' if has_creds else '❌'}",
        f"Offer link captured: {'✅' if offer_link else '❌'}",
    ]

    if device:
        lines.append("\n" + device.summary())

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown",
    )



# ── Periodic cleanup ──────────────────────────────────────────────────────────

async def _session_cleanup_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Periodic callback to purge expired sessions."""
    _purge_expired_sessions()


# ── Application setup ─────────────────────────────────────────────────────────

def main() -> None:
    token = config.TELEGRAM_BOT_TOKEN
    if not token:
        logger.error(
            "TELEGRAM_BOT_TOKEN environment variable is not set. "
            "Set it as an environment variable (e.g. via .env file or "
            "system environment) and restart."
        )
        sys.exit(1)

    app = Application.builder().token(token).build()

    # /login conversation
    login_conv = ConversationHandler(
        entry_points=[CommandHandler("login", login_start)],
        states={
            AWAIT_EMAIL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, login_email)
            ],
            AWAIT_PASSWORD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, login_password)
            ],
        },
        fallbacks=[CommandHandler("cancel", login_cancel)],
        allow_reentry=True,
    )

    # /check_offer conversation (handles 2FA)
    async def _offer_timeout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle conversation timeout – clean up driver."""
        if update and update.effective_chat:
            chat_id = update.effective_chat.id
            session = SESSION_STORE.get(chat_id, {})
            driver = session.pop("_driver", None)
            close_driver(driver)
            await context.bot.send_message(
                chat_id=chat_id,
                text="⏰ 2FA verification timed out. Please run /check_offer again.",
            )
        return ConversationHandler.END

    offer_conv = ConversationHandler(
        entry_points=[CommandHandler("check_offer", check_offer)],
        states={
            AWAIT_2FA_CODE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_2fa_code)
            ],
            ConversationHandler.TIMEOUT: [
                MessageHandler(filters.ALL, _offer_timeout)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_2fa)],
        allow_reentry=True,
        conversation_timeout=120,  # 2 minutes to enter 2FA code
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(login_conv)
    app.add_handler(CommandHandler("logout", logout))
    app.add_handler(offer_conv)
    app.add_handler(CommandHandler("get_link", get_link))
    app.add_handler(CommandHandler("status", status))

    # Periodic job: purge expired sessions every 5 minutes
    app.job_queue.run_repeating(
        _session_cleanup_job, interval=300, first=300,
    )

    logger.info("Bot is running. Press Ctrl-C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
