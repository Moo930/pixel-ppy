# Pixel Gemini – Telegram Bot

## Overview
A Telegram bot that simulates a Google Pixel 10 Pro (Android 16) device, logs into a user-provided Gmail account via Selenium, and retrieves the 12-month free Gemini Pro activation link from Google One.

## Tech Stack
- **Language:** Python 3.12
- **Bot Framework:** `python-telegram-bot[job-queue]==21.3`
- **Browser Automation:** `selenium==4.21.0` + `webdriver-manager==4.0.1`
- **Scheduler:** APScheduler (via job-queue extra)

## Project Structure
- `main.py` – Bot entry point; defines all Telegram command handlers and conversation flows
- `config.py` – Constants: device specs, URLs, Selenium timeouts, session TTL
- `device_simulator.py` – Generates unique Pixel 10 Pro device profiles (IMEI, Android ID, user-agent)
- `google_automation.py` – Selenium automation: logs into Google and scans Google One for the Gemini Pro offer
- `requirements.txt` – Python dependencies

## Environment Variables / Secrets
- `TELEGRAM_BOT_TOKEN` – Required. Obtain from @BotFather on Telegram.

## Workflow
- **Start application** – Runs `python main.py` (console output). The bot polls the Telegram API and responds to commands.

## Bot Commands
- `/start` – Welcome message
- `/login` – Enter Google credentials (email then password)
- `/logout` – Clear session/credentials
- `/check_offer` – Run automation and detect Gemini Pro offer (5-min cooldown per user)
- `/get_link` – Show last captured offer link
- `/status` – Show session and device info

## Notes
- Credentials are held in memory only (never persisted); passwords are zero-wiped after use.
- Max 3 simultaneous Chrome instances (semaphore-controlled).
- Sessions auto-expire after 30 minutes.
