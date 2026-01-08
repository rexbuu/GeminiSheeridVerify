# 🎭 Verification Bot | Tyrell's Edition 🚀

![Status](https://img.shields.io/badge/Status-Operational-green)
![Python](https://img.shields.io/badge/Python-3.11+-blue)
![License](https://img.shields.io/badge/License-MIT-purple)
![Maintenance](https://img.shields.io/badge/Maintained%3F-yes-green.svg)

A high-performance, asynchronous Telegram bot engineered for industrial-grade **Student Verification**. Featuring a sophisticated credit economy, multi-layered anti-detection, and a powerful real-time web administration suite.

---

## 🌟 Elite Features

### 🤖 Core Automation Logic
- **Precision Flow:** Fully automated SheerID interaction—from university selection to dynamic document generation and secure upload.
- **Global FIFO Queue:** A centralized First-In-First-Out orchestration system that manages load, prevents rate-limiting, and ensures fair processing.
- **Hyper-Fast Core:** Built on `asyncio` and `httpx` for massive concurrency and non-blocking performance.

### 💰 Automated Economy
- **Smart Credit System:**
  - **Welcome Gift:** New users automatically receive **3 credits**.
  - **Fair Usage:** Verifications cost **1 credit**. 
  - **Safety Net:** Credits are **auto-refunded** instantly if a verification fails for technical reasons.
- **Viral Referral System:**
  - Every user gets a unique invite link.
  - Earn **+2 credits** immediately when your referral completes their first session.
- **Redeemable Vouchers:** Generate unique codes with custom credit values, usage limits, and expiration dates.

### �️ Multi-Layer Anti-Detection
- **Browser Spoofing:** Dynamic rotation of premium User-Agents (Chrome 131+, Firefox, Edge, Safari).
- **Header Intelligence:** Precise SheerID header emulation with correct lowercase ordering and Client-Hints.
- **TLS Fingerprinting:** Support for `curl_cffi` to mimic real browser TLS handshakes, bypassing advanced fraud detection.
- **Resilient Fallbacks:** Intelligent library switching (`curl_cffi` → `cloudscraper` → `httpx`) to ensure continuity.

### 🔍 Self-Healing Proxy Engine
- **Active Monitoring:** A background worker rigorously tests every proxy every 30 minutes.
- **Delay Tolerance:** Optimized for slow proxies with a **15-second warm-up grace period** and 3-stage retry logic.
- **Automatic Quarantine:** Proxies that fail 5 consecutive checks are marked as "Dead" and auto-quarantined.
- **Smooth Recovery:** Dead proxies are continually tested and brought back online the moment they become healthy.

### 🎛️ Command-Center (Admin Panel)
- **Stealth Access:** Protected by a secret URL path (`/YOUR_SECRET_ROUTE`) and encrypted password.
- **Global Analytics:** Instantly view total users, circulating credits, and lifetime verification throughput.
- **Per-User Dossier:** Track individual success/fail rates, referral history, and registration dates.
- **Broadcast Pulse:** Send stylized Markdown announcements to your entire user base at once.
- **Voucher Studio:** Real-time management and creation of credit codes.

---

## 🚀 Deployment (Render Free-Tier Optimized)

### 1️⃣ Prepare Environment
- Fork this repository to your GitHub.
- Create a **Web Service** on [Render.com](https://render.com).
- Connect your fork.

### 2️⃣ Service Configuration
- **Runtime:** `Python 3`
- **Build Command:** `pip install -r requirements.txt`
- **Start Command:** `python bot.py` (Render will use `gunicorn` patterns automatically if detected, but `python bot.py` is fine for this bot).

### 3️⃣ Vital Environment Variables 🔑
| Variable | Mandatory? | Description |
| :--- | :---: | :--- |
| `TELEGRAM_BOT_TOKEN` | **YES** | Get from [@BotFather](https://t.me/botfather). |
| `ADMIN_PASSWORD` | **YES** | Password for the web admin dashboard. |
| `ADMIN_ROUTE` | **YES** | The secret path (e.g. `panel777`). Avoid simple words like `admin`. |
| `FLASK_SECRET_KEY` | **YES** | Keeps you logged in. Generate with `secrets.token_hex(32)`. |
| `PROXIES_JSON` | No | A single-line JSON array: `["socks5://user:pass@host:port", "..."]` |
| `KEEP_ALIVE_URL` | No | Your app URL (e.g. `https://my-bot.onrender.com`) to prevent sleep. |

---

## � Directory Structure

```plaintext
├── bot.py                # The "Brain" (Telegram API & Flask Dashboard)
├── script.py             # The "Engine" (Core verification & Document Logic)
├── anti_detect.py        # The "Shield" (Headers, Fingerprints, User-Agents)
├── requirements.txt      # Dependencies (python-telegram-bot, httpx, Pillow)
├── .env                  # Secrets configuration
├── stats.json            # Aggregated global success/fail analytics
├── users.json            # Encrypted user database (Credits/Referrals)
└── codes.json            # Active credit voucher database
```

---

## 🎮 Bot Commands

| Command | Action |
| :--- | :--- |
| `/start` | Launch the interactive main menu and check your balance. |
| `/redeem <CODE>` | Claim a credit voucher. |
| `/stats` | (Admin only) Get a quick snapshot of bot performance in chat. |

---

## 💡 Success Pro-Tips
1. **Quality Proxies:** Use high-quality Residential or SOCKS5 proxies for the highest success rates.
2. **Persistence:** If verification fails due to "Submit Failed," wait 5 minutes—the credits were refunded, so you can try again!
3. **Admin Monitoring:** Keep an eye on the **Proxy Health** table in the dashboard; if many are "Dead," it's time to rotate your proxy list.

---

## ⚠️ Legal Disclaimer
This software is provided "as is" for educational and research purposes only. The developers do not endorse or encourage any unauthorized use of external services. Users assume all responsibility for compliance with local laws and service terms.

---

**Crafted with ❤️ by Tyrell 🎭**
