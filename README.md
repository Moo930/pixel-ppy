# pixel-gemini

**Pixel 10 Pro Google One Gemini Offer Bot – Telegram Interface**

A Replit-hosted Telegram bot that simulates a Google Pixel 10 Pro (Android 16)
device, logs into a user-supplied Gmail account, and retrieves the
**12-month free Gemini Pro** activation link from Google One.

---

## Project Structure

```
pixel-gemini/
├── main.py               # Telegram bot entry point
├── device_simulator.py   # Android Pixel 10 Pro device simulation
├── google_automation.py  # Google One login and offer detection
├── config.py             # Configuration and constants
├── requirements.txt      # Python dependencies
└── README.md             # This file
```

---

## Features

| Feature | Details |
|---|---|
| 📱 Device simulation | Pixel 10 Pro (Android 16) with unique IMEI, Android ID, and user-agent per session |
| 🤖 Telegram bot | `/start`, `/login`, `/check_offer`, `/get_link`, `/status` commands |
| 🔐 Gmail login | Selenium-based Google account authentication |
| 💳 Offer detection | Scans Google One for the 12-month Gemini Pro offer and extracts the activation link |
| 🔄 Session management | In-memory per-user sessions; passwords deleted from chat on capture |

---

## Setup on Replit

### 1. Fork / import this repository

Open [Replit](https://replit.com) and create a new Repl from this GitHub repo.

### 2. Create a Telegram Bot

1. Open Telegram and search for **@BotFather**.
2. Send `/newbot` and follow the prompts.
3. Copy the API token you receive (looks like `123456:ABC-DEF…`).

### 3. Set the environment variable

In the Replit sidebar click **Secrets** (🔒) and add:

| Key | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Your token from BotFather |

### 4. Install dependencies

```bash
pip install -r requirements.txt
```

Replit runs this automatically on first start if you use a `pyproject.toml`
or if the Run button is configured to execute `pip install` first.

### 5. Run the bot

Click **Run** in Replit, or execute:

```bash
python main.py
```

The bot will start polling for Telegram updates.

---

## Usage

| Command | Description |
|---|---|
| `/start` | Show welcome message and command list |
| `/login` | Enter Gmail email and password (two-step conversation) |
| `/check_offer` | Simulate device, log in, and search for the Gemini Pro offer |
| `/get_link` | Retrieve the last captured offer link |
| `/status` | View current session info and device profile |

### Typical flow

```
You: /start
Bot: Welcome…

You: /login
Bot: Please enter your Gmail address:

You: user@gmail.com
Bot: Email received. Now enter your password:

You: ••••••••
Bot: ✅ Credentials saved. New Pixel 10 Pro device profile created…

You: /check_offer
Bot: ⏳ Launching device simulator…
Bot: 🎉 Gemini Pro Offer Found! 🔗 https://one.google.com/…
```

---

## Technical Notes

- **Headless Chrome** is used via Selenium with mobile emulation matching
  the Pixel 10 Pro screen dimensions (390 × 844, pixel ratio 3.0).
- A new **IMEI**, **Android ID**, and **Chrome version patch** are generated
  for every session using the `device_simulator.py` module.
- The **user agent** keeps the Pixel 10 Pro identity constant while varying
  the Chrome patch version and Android ID to reduce fingerprinting.
- Credentials are stored **in memory only** and never written to disk.
  The Telegram message containing the password is deleted immediately after
  being read.

---

## Requirements

- Python 3.10+
- Google Chrome / Chromium installed (Replit provides this)
- `chromedriver` on PATH (managed automatically by `webdriver-manager`)

---

## Disclaimer

This project is provided for educational and personal use only.
Automating Google account access may violate Google's Terms of Service.
Use responsibly and only with accounts you own.
