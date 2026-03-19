# pixel-gemini

**Pixel 10 Pro Google One Gemini Offer Bot – Telegram Interface**

A Telegram bot that simulates a Google Pixel 10 Pro (Android 16) device,
logs into a user-supplied Gmail account, and retrieves the
**12-month free Gemini Pro** activation link from Google One.

---

## Project Structure

```
pixel-gemini/
├── main.py               # Telegram bot entry point
├── device_simulator.py   # Android Pixel 10 Pro device simulation
├── google_automation.py  # Google One login and offer detection
├── config.py             # Configuration and constants
├── Dockerfile            # Docker image definition
├── docker-compose.yml    # Docker Compose orchestration
├── requirements.txt      # Python dependencies
└── README.md             # This file
```

---

## Features

| Feature | Details |
|---|---|
| 📱 Device simulation | Pixel 10 Pro (Android 16) with unique IMEI, Android ID, and user-agent per session |
| 🤖 Telegram bot | `/start`, `/login`, `/check_offer`, `/get_link`, `/status`, `/logout` commands |
| 🔐 Gmail login | Selenium-based Google account authentication |
| 💳 Offer detection | Scans Google One for the 12-month Gemini Pro offer and extracts the activation link |
| 🔄 Session management | In-memory per-user sessions with secure credential wiping |
| 🛡️ Security | Passwords stored as `bytearray` with in-place memory erasure, per-user rate limiting |

---

## Deployment (Ubuntu + Docker)

### Prerequisites

- Ubuntu 24.04 64-bit server
- Docker and Docker Compose installed

### 1. Install Docker

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# Log out and back in for group change to take effect
```

### 2. Create a Telegram Bot

1. Open Telegram and search for **@BotFather**.
2. Send `/newbot` and follow the prompts.
3. Copy the API token you receive (looks like `123456:ABC-DEF…`).

### 3. Clone and configure

```bash
git clone https://github.com/Moo930/pixel-ppy.git
cd pixel-ppy

# Create environment file
cp .env.example .env
nano .env
# Set TELEGRAM_BOT_TOKEN=<your token from BotFather>
```

### 4. Build and run

```bash
docker compose up -d --build
```

### 5. Management commands

```bash
# 停止 bot
docker compose stop

# 停止并删除容器
docker compose down

# 重启
docker compose restart

# 代码更新后重新构建
docker compose up -d --build

# 查看实时日志（控制台）
docker compose logs -f

# 查看日志文件
cat logs/bot.log

# 查看最近 100 行日志
tail -n 100 logs/bot.log

# 查看容器状态
docker compose ps
```

> **注意**：容器使用 `restart: on-failure:3` 策略，仅在异常退出时自动重启（最多 3 次）。
> 手动 `docker compose stop` 或 `docker compose down` 不会触发重启。

---

## Usage

| Command | Description |
|---|---|
| `/start` | Show welcome message and command list |
| `/login` | Enter Gmail email and password (two-step conversation) |
| `/check_offer` | Simulate device, log in, and search for the Gemini Pro offer |
| `/get_link` | Retrieve the last captured offer link |
| `/status` | View current session info and device profile |
| `/logout` | Securely clear credentials and session data |

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
- Credentials are stored as **`bytearray`** objects for secure in-place
  memory erasure. Passwords are wiped after use and never written to disk.
- **Rate limiting**: 5-minute cooldown per user between `/check_offer` calls.
- **Concurrency control**: Maximum 3 simultaneous Chrome instances.
- Session **TTL** of 30 minutes with automatic cleanup.

---

## Requirements

- Docker (recommended) or Python 3.10+ with Chromium and chromedriver
- A Telegram Bot token from @BotFather

---

## Disclaimer

This project is provided for educational and personal use only.
Automating Google account access may violate Google's Terms of Service.
Use responsibly and only with accounts you own.
