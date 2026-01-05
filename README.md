# 🎭 Verification Bot | Tyrell's Edition

![Status](https://img.shields.io/badge/Status-Operational-green)
![Python](https://img.shields.io/badge/Python-3.11+-blue)
![License](https://img.shields.io/badge/License-MIT-purple)

A robust, asynchronous Telegram bot designed for automated Student Verification. Includes a full credit system, referral mechanics, global FIFO queue, and proxy rotation for maximum success rates.

---

## ✨ Key Features

### 🤖 Core Automation
- **Automated Verification:** Handles the entire SheerID flow from info generation to document upload.
- **Smart Queue System:** Global FIFO (First-In-First-Out) queue prevents server overload and API rate limits.
- **Async & Fast:** Built with `asyncio` and `httpx` for non-blocking concurrent operations.
- **Proxy Rotation:** Automatically rotates through a list of US proxies (SOCKS5/HTTP).

### 💰 Economy & Users
- **Credit System:**
  - New users start with **3 credits**.
  - Verifications cost **1 credit**.
  - Failed verifications **refund** the credit automatically.
- **Referral Program:**
  - Unique referral links for every user.
  - Earn **+2 credits** for every friend referred.
- **Daily Limits:** Global limit of **24 verifications/day** to ensure safety.

### 📊 Analytics & UI
- **Beautiful UI:** stylized messages, progress bars, and custom fun messages.
- **Live Stats:** Track success rates, active proxies, and user rankings (Newbie -> Legend).
- **Real-time Updates:** Users see step-by-step progress of their verification.

---

## 🛠 Directory Structure

```plaintext
.
├── bot.py                # Main Telegram Bot logic
├── script.py             # Core verification engine (SheerID logic)
├── proxies.json          # List of proxies (Not on GitHub)
├── users.json            # Database of user credits/referrals (Auto-generated)
├── daily.json            # Daily limit counter (Auto-generated)
├── stats.json            # Success/Fail statistics (Auto-generated)
├── .env                  # Secrets (Not on GitHub)
└── requirements.txt      # Python dependencies
```

---

## 🚀 Deployment Guide (Render)

This bot is optimized for deployment on **Render**.

### 1. Prepare Environment
1. Fork/Clone this repository.
2. Create a new **Web Service** on Render.
3. Connect your repository.

### 2. Configure Settings
- **Runtime:** `Python 3`
- **Build Command:** `pip install -r requirements.txt`
- **Start Command:** `python bot.py`

### 3. Environment Variables
Go to the **Environment** tab and add:

| Key | Value | Description |
| :--- | :--- | :--- |
| `TELEGRAM_BOT_TOKEN` | `123456:ABC...` | Your Bot Token from @BotFather |
| `PROXIES_JSON` | `["socks5://..."]` | List of proxies (JSON Array format) |
| `PORT` | `8080` | Internal port (Render sets this auto) |

> **Note:** Proper format for `PROXIES_JSON`:
> `["socks5://user:pass@host:port", "http://user:pass@host:port"]`

---

## 💻 Local Development

1. **Clone & Install**
   ```bash
   git clone https://github.com/your-username/verification-bot.git
   cd verification-bot
   pip install -r requirements.txt
   ```

2. **Configure Secrets**
   - Rename `.env.example` to `.env`
   - Add your `TELEGRAM_BOT_TOKEN`

3. **Add Proxies (Optional)**
   - Rename `proxies.example.json` to `proxies.json`
   - Add your proxies there.

4. **Run**
   ```bash
   python bot.py
   ```

---

## ⚠️ Disclaimer
This tool is for educational purposes only. The author is not responsible for any misuse.

---

**Author:** Tyrell 🎭
