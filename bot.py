import os
import asyncio
import random
import logging
import json
import hashlib
from pathlib import Path
from dataclasses import dataclass, asdict
from datetime import datetime, date
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from flask import Flask, request, session, redirect, url_for
import secrets
from threading import Thread
import httpx

# Load .env file from the same directory as this script
load_dotenv(Path(__file__).parent / ".env")

# Configure Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- CONFIGURATION ---
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
PORT = int(os.environ.get("PORT", 8080))
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "Mrn00btnw")
ADMIN_ROUTE = os.getenv("ADMIN_ROUTE", "admin")  # Secret admin path
KEEP_ALIVE_URL = os.getenv("KEEP_ALIVE_URL")  # Self-ping URL to prevent Render sleep
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY", secrets.token_hex(32))  # Persistent session key
STATS_FILE = Path(__file__).parent / "stats.json"
USERS_FILE = Path(__file__).parent / "users.json"
DAILY_FILE = Path(__file__).parent / "daily.json"
PROXIES_FILE = Path(__file__).parent / "proxies.json"
CODES_FILE = Path(__file__).parent / "codes.json"

# Credits Configuration
INITIAL_CREDITS = 3
VERIFICATION_COST = 1
REFERRAL_BONUS = 2
DAILY_LIMIT_GLOBAL = 1200
DAILY_LIMIT_USER = 24

# Keep-Alive Configuration
KEEP_ALIVE_INTERVAL = 300  # 5 minutes
KEEP_ALIVE_MAX_FAILURES = 3

# Proxy Health Check Configuration
PROXY_CHECK_INTERVAL = 1800  # 30 minutes
PROXY_CHECK_TIMEOUT = 10     # 10 seconds
PROXY_MAX_FAILURES = 5       # Mark dead after 5 fails (tolerant for slow proxies)

# Global proxy health tracking
proxy_health: dict = {}  # {"proxy_url": {"status": "healthy/dead", "failures": 0, "last_check": "..."}}

# --- PROXY MANAGEMENT ---
def load_proxies() -> list:
    """Load proxies from ENV or file. Returns empty list if no proxies."""
    # 1. Try Environment Variable (Perfect for Render)
    env_proxies = os.getenv("PROXIES_JSON", "").strip()
    if env_proxies:
        try:
            proxies = json.loads(env_proxies)
            if isinstance(proxies, list):
                return [p for p in proxies if p]
        except Exception as e:
            # Only log if it's not a multiline issue we've already seen
            if env_proxies != "[" and env_proxies != "[]":
                logger.error(f"Failed to parse PROXIES_JSON env var: {e}")

    # 2. Try Local File
    if PROXIES_FILE.exists():
        try:
            proxies = json.loads(PROXIES_FILE.read_text())
            if isinstance(proxies, list):
                return [p for p in proxies if p]  # Filter empty strings
        except:
            pass
    return []

def get_proxy() -> tuple[str | None, str]:
    """Get a random healthy proxy. Returns (proxy_string, display_name)"""
    proxies = load_proxies()
    if not proxies:
        return None, "DIRECT 🏠"
    
    # Filter to only healthy proxies
    healthy_proxies = [p for p in proxies if proxy_health.get(p, {}).get("status", "healthy") != "dead"]
    
    # If all proxies are dead, fallback to DIRECT
    if not healthy_proxies:
        logger.warning("All proxies are dead, using DIRECT connection")
        return None, "DIRECT ⚠️"
    
    proxy = random.choice(healthy_proxies)
    try:
        # Extract city code from proxy URL
        city = proxy.split('@')[1].split('.')[0].upper()
        return proxy, f"{city} 🌐"
    except:
        return proxy, "PROXY 🔒"

# Fun messages
PROCESSING_MESSAGES = [
    "Hacking the mainframe... just kidding 😏",
    "Warming up the quantum processors ⚛️",
    "Summoning the verification spirits 👻",
    "Teaching AI to pretend to be a student 📚",
    "Bribing the SheerID servers with cookies 🍪",
]

SUCCESS_MESSAGES = [
    "We did it! High five! 🙌",
    "Mission accomplished, agent! 🕵️",
    "That was smoother than butter 🧈",
    "Tyrell sends his regards 😎",
    "Another successful heist! 💰",
]

FAIL_MESSAGES = [
    "Houston, we have a problem 🚀",
    "The matrix rejected us 💊",
    "SheerID said 'nah fam' 😤",
    "Even hackers have bad days 😅",
    "Time to blame the firewall 🔥",
]

# --- USER DATABASE ---
def load_users() -> dict:
    """Load users from file"""
    if USERS_FILE.exists():
        try:
            return json.loads(USERS_FILE.read_text())
        except:
            pass
    return {}

def save_users(users: dict):
    """Save users to file"""
    USERS_FILE.write_text(json.dumps(users, indent=2))

def get_user(user_id: int) -> dict:
    """Get or create user"""
    users = load_users()
    user_id_str = str(user_id)
    
    if user_id_str not in users:
        # Generate unique referral code
        ref_code = hashlib.md5(f"{user_id}{datetime.now().timestamp()}".encode()).hexdigest()[:8].upper()
        users[user_id_str] = {
            "credits": INITIAL_CREDITS,
            "referral_code": ref_code,
            "referred_by": None,
            "referrals": [],
            "total_verifications": 0,
            "joined": datetime.now().isoformat()
        }
        save_users(users)
    
    return users[user_id_str]

def update_user(user_id: int, data: dict):
    """Update user data"""
    users = load_users()
    user_id_str = str(user_id)
    if user_id_str in users:
        users[user_id_str].update(data)
        save_users(users)

def deduct_credit(user_id: int) -> bool:
    """Deduct 1 credit from user. Returns True if successful."""
    users = load_users()
    user_id_str = str(user_id)
    
    if user_id_str in users and users[user_id_str]["credits"] >= VERIFICATION_COST:
        users[user_id_str]["credits"] -= VERIFICATION_COST
        users[user_id_str]["total_verifications"] += 1
        save_users(users)
        return True
    return False

def add_credits(user_id: int, amount: int):
    """Add credits to user"""
    users = load_users()
    user_id_str = str(user_id)
    if user_id_str in users:
        users[user_id_str]["credits"] += amount
        save_users(users)

def record_verification_result(user_id: int, success: bool):
    """Record verification result (success/fail) for a user"""
    users = load_users()
    user_id_str = str(user_id)
    if user_id_str in users:
        # Initialize if not exists
        if "success_count" not in users[user_id_str]:
            users[user_id_str]["success_count"] = 0
        if "failed_count" not in users[user_id_str]:
            users[user_id_str]["failed_count"] = 0
        
        if success:
            users[user_id_str]["success_count"] += 1
        else:
            users[user_id_str]["failed_count"] += 1
        save_users(users)

def process_referral(new_user_id: int, ref_code: str) -> tuple[bool, int]:
    """Process a referral. Returns (success, referrer_id)"""
    users = load_users()
    
    # Find referrer by code
    referrer_id = None
    for uid, data in users.items():
        if data.get("referral_code") == ref_code.upper():
            referrer_id = int(uid)
            break
    
    if not referrer_id or referrer_id == new_user_id:
        return False, 0
    
    new_user_str = str(new_user_id)
    referrer_str = str(referrer_id)
    
    # Check if already referred
    if users.get(new_user_str, {}).get("referred_by"):
        return False, 0
    
    # Process referral
    users[new_user_str]["referred_by"] = referrer_id
    users[referrer_str]["credits"] += REFERRAL_BONUS
    users[referrer_str]["referrals"].append(new_user_id)
    save_users(users)
    
    return True, referrer_id

# --- CODE REDEMPTION SYSTEM ---
def load_codes() -> dict:
    """Load redeem codes from file"""
    if CODES_FILE.exists():
        try:
            return json.loads(CODES_FILE.read_text())
        except:
            pass
    return {}

def save_codes(codes: dict):
    """Save redeem codes to file"""
    CODES_FILE.write_text(json.dumps(codes, indent=2))

def redeem_code(user_id: int, code_str: str) -> tuple[bool, str, int]:
    """Redeem a code for a user. Returns (success, message, credit_amount)"""
    codes = load_codes()
    code_str = code_str.upper().strip()
    
    if code_str not in codes:
        return False, "Invalid code! ❌", 0
    
    code_data = codes[code_str]
    
    # Check expiry
    if code_data.get("expires_at"):
        try:
            expiry = datetime.fromisoformat(code_data["expires_at"])
            if datetime.now() > expiry:
                return False, "This code has expired! ⏰", 0
        except:
            pass
            
    # Check max uses
    if code_data.get("max_uses") is not None:
        if code_data.get("current_uses", 0) >= code_data["max_uses"]:
            return False, "This code has reached its usage limit! 🛑", 0
            
    # Check if user already redeemed
    if user_id in code_data.get("redeemed_by", []):
        return False, "You've already redeemed this code! ✋", 0
        
    # Process redemption
    credit_amount = code_data.get("credits", 0)
    add_credits(user_id, credit_amount)
    
    # Update code data
    if "redeemed_by" not in code_data:
        code_data["redeemed_by"] = []
    code_data["redeemed_by"].append(user_id)
    code_data["current_uses"] = code_data.get("current_uses", 0) + 1
    
    codes[code_str] = code_data
    save_codes(codes)
    
    return True, f"Successfully redeemed! 💎 +{credit_amount} credits added.", credit_amount

# --- DAILY LIMIT ---
def load_daily() -> dict:
    """Load daily stats"""
    default_data = {
        "date": str(date.today()), 
        "global_count": 0, 
        "user_counts": {}
    }
    
    if DAILY_FILE.exists():
        try:
            data = json.loads(DAILY_FILE.read_text())
            # Reset if it's a new day
            if data.get("date") != str(date.today()):
                return default_data
            
            # Ensure new structure exists (migration)
            if "global_count" not in data:
                data["global_count"] = data.get("count", 0)
            if "user_counts" not in data:
                data["user_counts"] = {}
                
            return data
        except:
            pass
    return default_data

def save_daily(data: dict):
    """Save daily stats"""
    DAILY_FILE.write_text(json.dumps(data, indent=2))

def check_daily_limit(user_id: int) -> tuple[bool, str]:
    """Check limits. Returns (can_proceed, reason_if_failed)"""
    daily = load_daily()
    user_str = str(user_id)
    
    # 1. Check Global Limit
    if daily["global_count"] >= DAILY_LIMIT_GLOBAL:
        return False, "GLOBAL_LIMIT"
        
    # 2. Check User Limit
    user_usage = daily["user_counts"].get(user_str, 0)
    if user_usage >= DAILY_LIMIT_USER:
        return False, "USER_LIMIT"
        
    return True, "OK"

def increment_daily(user_id: int):
    """Increment daily counters"""
    daily = load_daily()
    user_str = str(user_id)
    
    daily["global_count"] += 1
    daily["user_counts"][user_str] = daily["user_counts"].get(user_str, 0) + 1
    
    save_daily(daily)

# --- QUEUE SYSTEM ---
@dataclass
class VerificationJob:
    chat_id: int
    url: str
    username: str
    user_id: int

task_queue: asyncio.Queue = None

# --- HELPER FUNCTIONS ---
def get_stats() -> dict:
    if STATS_FILE.exists():
        try:
            return json.loads(STATS_FILE.read_text())
        except:
            pass
    return {
        "total": 0, 
        "success": 0, 
        "failed": 0, 
        "errors": {
            "submit_failed": 0,
            "api_error": 0,
            "no_upload_url": 0,
            "upload_failed": 0,
            "unknown_step": 0,
            "other": 0
        },
        "orgs": {}
    }

def get_main_menu_keyboard(user_id: int):
    user = get_user(user_id)
    credits = user.get("credits", 0)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f" My Credits: {credits}", callback_data="credits")],
        [InlineKeyboardButton("📊 Stats & Glory", callback_data="stats"),
         InlineKeyboardButton("📋 Queue", callback_data="queue")],
        [InlineKeyboardButton("🎁 Refer Friends", callback_data="refer"),
         InlineKeyboardButton("💎 Redeem Code", callback_data="redeem_menu")],
        [InlineKeyboardButton("🎓 How This Works", callback_data="help")],
    ])

def get_back_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Back to Base", callback_data="menu")]
    ])

# --- WORKER ---
async def worker(application: Application):
    global task_queue
    logger.info("Worker started and waiting for jobs...")
    
    while True:
        job = await task_queue.get()
        logger.info(f"Starting job for {job.username} ({job.chat_id})")
        
        try:
            fun_msg = random.choice(PROCESSING_MESSAGES)
            await application.bot.send_message(
                chat_id=job.chat_id,
                text=(
                    "╔══════════════════════════╗\n"
                    "║  🚀 **LAUNCH SEQUENCE**  ║\n"
                    "╚══════════════════════════╝\n\n"
                    f"*{fun_msg}*\n\n"
                    "Buckle up, this is gonna be good! 🎢"
                ),
                parse_mode="Markdown"
            )

            proxy, proxy_display = get_proxy()
            if proxy:
                logger.info(f"Using proxy: {proxy.split('@')[1]}")
            else:
                logger.info("Using direct connection (no proxies configured)")
            
            await application.bot.send_message(
                chat_id=job.chat_id,
                text=f"🌐 *Connection:* **{proxy_display}**",
                parse_mode="Markdown"
            )
            
            from script import GeminiVerifier
            import queue
            
            progress_queue = queue.Queue()
            
            def progress_callback(message: str):
                progress_queue.put(message)
            
            async def send_progress_updates():
                while True:
                    try:
                        await asyncio.sleep(0.3)
                        while not progress_queue.empty():
                            msg = progress_queue.get_nowait()
                            await application.bot.send_message(
                                chat_id=job.chat_id,
                                text=msg,
                                parse_mode="Markdown"
                            )
                    except asyncio.CancelledError:
                        while not progress_queue.empty():
                            msg = progress_queue.get_nowait()
                            await application.bot.send_message(
                                chat_id=job.chat_id,
                                text=msg,
                                parse_mode="Markdown"
                            )
                        break
            
            progress_task = asyncio.create_task(send_progress_updates())
            
            verifier = GeminiVerifier(job.url, proxy=proxy, progress_callback=progress_callback)
            result = await asyncio.to_thread(verifier.verify)
            
            progress_task.cancel()
            try:
                await progress_task
            except asyncio.CancelledError:
                pass

            # Increment daily counter
            increment_daily(job.user_id)
            
            user = get_user(job.user_id)
            credits_left = user.get("credits", 0)

            if result.get("success"):
                # Record success for user analytics
                record_verification_result(job.user_id, True)
                
                fun_success = random.choice(SUCCESS_MESSAGES)
                response = (
                    "╔══════════════════════════╗\n"
                    "║   🎉 **VICTORY ROYALE**  ║\n"
                    "╚══════════════════════════╝\n\n"
                    f"*{fun_success}*\n\n"
                    "**Verification submitted! Wait 24-48h for review**\n\n"
                    "They'll review it like it's a college essay 📝\n\n"
                    "📧 Check your email for the good news!\n\n"
                    f"💰 **Credits remaining:** {credits_left}\n\n"
                    "_Tyrell out_ ✌️"
                )
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Another Round?", callback_data="new")],
                    [InlineKeyboardButton("🎁 Get More Credits", callback_data="refer")]
                ])
            else:
                # Record failure for user analytics
                record_verification_result(job.user_id, False)
                
                # Refund credit on failure
                add_credits(job.user_id, VERIFICATION_COST)
                credits_left += VERIFICATION_COST
                
                fun_fail = random.choice(FAIL_MESSAGES)
                response = (
                    "╔══════════════════════════╗\n"
                    "║     ❌ **PLOT TWIST**    ║\n"
                    "╚══════════════════════════╝\n\n"
                    f"*{fun_fail}*\n\n"
                    f"**What went wrong:** `{result.get('error')}`\n\n"
                    "🔧 **Quick fixes:**\n"
                    "• Get a fresh link (this one's stale 🍞)\n"
                    "• Wait a bit and try again\n\n"
                    f"💰 **Credit refunded!** You have: {credits_left}\n\n"
                    "_Don't worry, we'll get 'em next time_ 💪"
                )
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Try Again", callback_data="new")],
                    [InlineKeyboardButton("🔙 Back to Base", callback_data="menu")]
                ])

            await application.bot.send_message(
                chat_id=job.chat_id, 
                text=response, 
                parse_mode="Markdown",
                reply_markup=keyboard
            )
            
        except Exception as e:
            logger.error(f"Error in worker: {e}", exc_info=True)
            # Refund on error
            add_credits(job.user_id, VERIFICATION_COST)
            
            await application.bot.send_message(
                chat_id=job.chat_id, 
                text=(
                    "╔══════════════════════════╗\n"
                    "║   💥 **OOPS!**           ║\n"
                    "╚══════════════════════════╝\n\n"
                    "Something exploded (not literally) 🔥\n\n"
                    f"`{str(e)}`\n\n"
                    "💰 **Credit refunded!**\n"
                    "_Try again later, the servers need therapy_ 🛋️"
                ),
                parse_mode="Markdown",
                reply_markup=get_back_keyboard()
            )
        finally:
            task_queue.task_done()
            logger.info(f"Finished job for {job.chat_id}")
            
            if not task_queue.empty():
                logger.info("Cooling down for 10 seconds before next job...")
                await asyncio.sleep(10)

# --- BOT HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_data = get_user(user.id)
    
    # Check for referral code in start command
    if context.args and len(context.args) > 0:
        ref_code = context.args[0]
        success, referrer_id = process_referral(user.id, ref_code)
        if success:
            # Notify the user
            await update.message.reply_text(
                "🎁 **Referral Applied!**\n\n"
                "Your friend will receive bonus credits!\n"
                "_Welcome to the family_ ✨",
                parse_mode="Markdown"
            )
            # Notify the referrer
            try:
                await context.bot.send_message(
                    chat_id=referrer_id,
                    text=(
                        "╔══════════════════════════╗\n"
                        "║   🎉 **NEW REFERRAL!**   ║\n"
                        "╚══════════════════════════╝\n\n"
                        f"**{user.first_name}** just joined using your link!\n\n"
                        f"💰 **+{REFERRAL_BONUS} credits** added to your account!\n\n"
                        "_Keep spreading the word!_ 🚀"
                    ),
                    parse_mode="Markdown"
                )
            except:
                pass
    
    credits = user_data.get("credits", INITIAL_CREDITS)
    
    welcome_text = (
        "╔══════════════════════════╗\n"
        "║  🤖 **TYRELL'S BOT**     ║\n"
        "║  _Gemini Verification_   ║\n"
        "╚══════════════════════════╝\n\n"
        f"Yo **{user.first_name}**! Welcome to the club 🎭\n\n"
        f"💰 **Your Credits:** {credits}\n"
        f"📊 **Cost per verify:** {VERIFICATION_COST} credit\n\n"
        "I turn regular folks into verified students\n"
        "for **Google One AI Premium**. Magic? Nah,\n"
        "just really good code 😏\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🎯 **THE DEAL:**\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Drop your SheerID link below and watch\n"
        "me work my magic ✨\n\n"
        "📎 Looks like: `services.sheerid.com/verify/...`"
    )
    
    await update.message.reply_text(
        welcome_text,
        parse_mode="Markdown",
        reply_markup=get_main_menu_keyboard(user.id)
    )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    if query.data == "menu":
        user = get_user(user_id)
        await query.edit_message_text(
            "╔══════════════════════════╗\n"
            "║   🏠 **HOME BASE**       ║\n"
            "╚══════════════════════════╝\n\n"
            f"💰 **Credits:** {user.get('credits', 0)}\n\n"
            "What's the move, chief? 🎮\n\n"
            "_Or just yeet me a SheerID link!_",
            parse_mode="Markdown",
            reply_markup=get_main_menu_keyboard(user_id)
        )
    
    elif query.data == "credits":
        user = get_user(user_id)
        credits = user.get("credits", 0)
        total_verifications = user.get("total_verifications", 0)
        referrals = len(user.get("referrals", []))
        
        credits_text = (
            "╔══════════════════════════╗\n"
            "║   💰 **YOUR WALLET**     ║\n"
            "╚══════════════════════════╝\n\n"
            f"💎 **Credits:** {credits}\n"
            f"✅ **Total Verifications:** {total_verifications}\n"
            f"👥 **Friends Referred:** {referrals}\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "💡 **HOW TO GET MORE:**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🎁 Refer a friend = **+{REFERRAL_BONUS} credits**\n"
            "📱 Share your referral link below!\n\n"
            f"_Each verification costs {VERIFICATION_COST} credit_"
        )
        
        await query.edit_message_text(
            credits_text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🎁 Get Referral Link", callback_data="refer")],
                [InlineKeyboardButton("🔙 Back to Base", callback_data="menu")]
            ])
        )
    
    elif query.data == "refer":
        user = get_user(user_id)
        ref_code = user.get("referral_code", "ERROR")
        bot_username = (await context.bot.get_me()).username
        ref_link = f"https://t.me/{bot_username}?start={ref_code}"
        referrals = len(user.get("referrals", []))
        
        refer_text = (
            "╔══════════════════════════╗\n"
            "║   🎁 **REFER & EARN**    ║\n"
            "╚══════════════════════════╝\n\n"
            f"Share this link with friends:\n\n"
            f"`{ref_link}`\n\n"
            f"_(Tap to copy)_\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 **You get:** +{REFERRAL_BONUS} credits per friend\n"
            f"👥 **Friends referred:** {referrals}\n"
            f"💎 **Total earned:** {referrals * REFERRAL_BONUS} credits\n\n"
            "_More friends = More verifications!_ 🚀"
        )
        
        await query.edit_message_text(
            refer_text,
            parse_mode="Markdown",
            reply_markup=get_back_keyboard()
        )
    
    elif query.data == "stats":
        stats = get_stats()
        total = stats.get("total", 0)
        success = stats.get("success", 0)
        failed = stats.get("failed", 0)
        rate = (success / total * 100) if total > 0 else 0
        
        daily = load_daily()
        daily_remaining_global = DAILY_LIMIT_GLOBAL - daily.get("global_count", 0)
        daily_user_usage = daily.get("user_counts", {}).get(str(user_id), 0)
        
        bar_length = 10
        filled = int(bar_length * rate / 100) if rate > 0 else 0
        bar = "▓" * filled + "░" * (bar_length - filled)
        
        user = get_user(user_id)
        user_verifications = user.get("total_verifications", 0)
        
        if user_verifications >= 100:
            rank = "🏆 Legend"
        elif user_verifications >= 50:
            rank = "⭐ Elite"
        elif user_verifications >= 20:
            rank = "🎖️ Veteran"
        elif user_verifications >= 5:
            rank = "🔰 Rookie"
        else:
            rank = "🆕 Newbie"
        
        proxies = load_proxies()
        proxy_status = f"**{len(proxies)}** 🇺🇸" if proxies else "None (Direct) 🏠"
        
        errors = stats.get("errors", {})
        
        stats_text = (
            "╔══════════════════════════╗\n"
            "║  📊 **HALL OF FAME**     ║\n"
            "╚══════════════════════════╝\n\n"
            f"🎮 **Your Rank:** {rank}\n\n"
            f"📈 Total Runs: **{total}**\n"
            f"✅ Victories: **{success}**\n"
            f"❌ Fails: **{failed}**\n\n"
            f"**Win Rate:** {rate:.1f}%\n"
            f"`[{bar}]`\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚠️ **FAILURE BREAKDOWN:**\n"
            f"• Submit Failed: **{errors.get('submit_failed', 0)}**\n"
            f"• API Error: **{errors.get('api_error', 0)}**\n"
            f"• No Upload URL: **{errors.get('no_upload_url', 0)}**\n"
            f"• Upload Failed: **{errors.get('upload_failed', 0)}**\n"
            f"• Unknown Step: **{errors.get('unknown_step', 0)}**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📅 **Global Slots:** {daily_remaining_global}/{DAILY_LIMIT_GLOBAL}\n"
            f"👤 **Your Slots:** {daily_user_usage}/{DAILY_LIMIT_USER}\n"
            f"🌐 **Proxies:** {proxy_status}"
        )
        
        await query.edit_message_text(
            stats_text,
            parse_mode="Markdown",
            reply_markup=get_back_keyboard()
        )
    
    elif query.data == "queue":
        q_size = task_queue.qsize() if task_queue else 0
        daily = load_daily()
        daily_remaining_global = DAILY_LIMIT_GLOBAL - daily.get("global_count", 0)
        
        if q_size == 0:
            status_emoji = "😴"
            status_text = "Queue's empty. I'm just chillin' ☕"
        elif q_size < 3:
            status_emoji = "🏃"
            status_text = "Light work, we moving fast!"
        else:
            status_emoji = "🔥"
            status_text = "It's getting spicy in here!"
        
        queue_text = (
            "╔══════════════════════════╗\n"
            "║  📋 **QUEUE STATUS**     ║\n"
            "╚══════════════════════════╝\n\n"
            f"{status_emoji} **{status_text}**\n\n"
            f"📍 Jobs waiting: **{q_size}**\n"
            f"⏱️ Approx wait: **~{q_size} min**\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📅 **Global Slots Remaining:** {daily_remaining_global}/{DAILY_LIMIT_GLOBAL}\n\n"
            "_First come, first served_ 🎫"
        )
        
        await query.edit_message_text(
            queue_text,
            parse_mode="Markdown",
            reply_markup=get_back_keyboard()
        )
    
    elif query.data == "help":
        help_text = (
            "╔══════════════════════════╗\n"
            "║  🎓 **THE MASTER PLAN**  ║\n"
            "╚══════════════════════════╝\n\n"
            "**Step 1️⃣** Go to Google One's student page\n"
            "_The one with free AI Premium_ 🎁\n\n"
            "**Step 2️⃣** Click \"Verify as Student\"\n"
            "_SheerID will pop up_ 👔\n\n"
            "**Step 3️⃣** Copy the URL from your browser\n"
            "_The whole thing_ 📋\n\n"
            "**Step 4️⃣** Send it to me right here\n"
            "_Just paste and send_ 🤝\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "💰 **CREDIT SYSTEM:**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🆕 New users: **{INITIAL_CREDITS} free credits**\n"
            f"✅ Each verification: **{VERIFICATION_COST} credit**\n"
            f"🎁 Refer a friend: **+{REFERRAL_BONUS} credits**\n"
            f"📅 **Daily limit:** {DAILY_LIMIT_USER} (You) / {DAILY_LIMIT_GLOBAL} (Total)\n\n"
            "_Failed attempts = credit refunded!_ ✨"
        )
        
        await query.edit_message_text(
            help_text,
            parse_mode="Markdown",
            reply_markup=get_back_keyboard()
        )
    
    elif query.data == "redeem_menu":
        await query.edit_message_text(
            "╔══════════════════════════╗\n"
            "║   💎 **REDEEM CODE**     ║\n"
            "╚══════════════════════════╝\n\n"
            "Got a special code? 🎫\n\n"
            "Type `/redeem YOUR_CODE` in the chat to\n"
            "claim your credits!\n\n"
            "_Example: `/redeem WELCOME2026`_",
            parse_mode="Markdown",
            reply_markup=get_back_keyboard()
        )
    
    elif query.data == "new":
        user = get_user(user_id)
        credits = user.get("credits", 0)
        
        await query.edit_message_text(
            "╔══════════════════════════╗\n"
            "║  🔄 **ROUND TWO!**       ║\n"
            "╚══════════════════════════╝\n\n"
            f"💰 **Your Credits:** {credits}\n\n"
            "Ready when you are! 🎯\n\n"
            "Drop that SheerID link below:\n"
            "`services.sheerid.com/verify/...`\n\n"
            "_Let's get this bread_ 🍞",
            parse_mode="Markdown",
            reply_markup=get_back_keyboard()
        )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global task_queue
    url = update.message.text.strip()
    user_id = update.effective_user.id
    
    if "sheerid.com" not in url:
        funny_rejects = [
            "That's not a SheerID link, bestie 😅",
            "Nice try, but I need a SheerID URL 🧐",
            "My SheerID senses are not tingling 🕷️",
            "404: Valid URL not found 🔍",
        ]
        await update.message.reply_text(
            "╔══════════════════════════╗\n"
            "║   ⚠️ **HOLD UP**         ║\n"
            "╚══════════════════════════╝\n\n"
            f"*{random.choice(funny_rejects)}*\n\n"
            "I need something like:\n"
            "`services.sheerid.com/verify/...`\n\n"
            "_Try again, you got this!_ 💪",
            parse_mode="Markdown",
            reply_markup=get_main_menu_keyboard(user_id)
        )
        return

    # Check daily limit
    can_proceed, reason = check_daily_limit(user_id)
    if not can_proceed:
        if reason == "GLOBAL_LIMIT":
            msg = f"Global limit of **{DAILY_LIMIT_GLOBAL}** reached! 🌍"
        else:
            msg = f"You hit your daily limit of **{DAILY_LIMIT_USER}**! 🛑"
            
        await update.message.reply_text(
            "╔══════════════════════════╗\n"
            "║  ⏰ **DAILY LIMIT HIT**  ║\n"
            "╚══════════════════════════╝\n\n"
            f"{msg}\n\n"
            "The servers need rest too 😴\n"
            "Come back tomorrow for more!\n\n"
            "_Limit resets at midnight UTC_ 🌙",
            parse_mode="Markdown",
            reply_markup=get_back_keyboard()
        )
        return

    # Check credits
    user = get_user(user_id)
    credits = user.get("credits", 0)
    
    if credits < VERIFICATION_COST:
        await update.message.reply_text(
            "╔══════════════════════════╗\n"
            "║  💸 **OUT OF CREDITS**   ║\n"
            "╚══════════════════════════╝\n\n"
            f"You need **{VERIFICATION_COST}** credit but have **{credits}** 😢\n\n"
            "🎁 **Get more credits:**\n"
            f"• Refer a friend = +{REFERRAL_BONUS} credits\n"
            "• Share your link below!\n\n"
            "_Sharing is caring_ 💝",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🎁 Get Referral Link", callback_data="refer")],
                [InlineKeyboardButton("🔙 Back to Base", callback_data="menu")]
            ])
        )
        return

    # Deduct credit
    if not deduct_credit(user_id):
        await update.message.reply_text("❌ Error processing credits. Please try again.")
        return

    q_size = task_queue.qsize()
    pos = q_size + 1
    wait_time = pos * 1
    
    job = VerificationJob(
        chat_id=update.effective_chat.id,
        url=url,
        username=update.effective_user.username or update.effective_user.first_name,
        user_id=user_id
    )
    
    await task_queue.put(job)
    logger.info(f"New job added to queue by {job.username}. Queue size: {pos}")
    
    credits_after = credits - VERIFICATION_COST
    
    if pos == 1:
        position_msg = "You're up NEXT! 🎯"
    elif pos <= 3:
        position_msg = "Almost there, just a few ahead 🏃"
    else:
        position_msg = "Grab some popcorn, might be a wait 🍿"
    
    await update.message.reply_text(
        "╔══════════════════════════╗\n"
        "║  📥 **LINK CAPTURED!**   ║\n"
        "╚══════════════════════════╝\n\n"
        f"🎫 **Your Ticket:** #{pos}\n"
        f"⏳ **Wait Time:** ~{wait_time} min\n"
        f"💰 **Credits Used:** {VERIFICATION_COST}\n"
        f"💎 **Remaining:** {credits_after}\n\n"
        f"*{position_msg}*\n\n"
        "I'll ping you when it's showtime! 🎬\n"
        "_Please don't spam links_ 🙏",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 Check Queue", callback_data="queue")]
        ])
    )

async def redeem_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text("Usage: `/redeem CODE`", parse_mode="Markdown")
        return
        
    code_str = context.args[0]
    success, message, amount = redeem_code(user_id, code_str)
    
    if success:
        await update.message.reply_text(
            "╔══════════════════════════╗\n"
            "║   ✨ **CODE ACCEPTED!**  ║\n"
            "╚══════════════════════════╝\n\n"
            f"{message}\n\n"
            "What's next? 🚀",
            parse_mode="Markdown",
            reply_markup=get_main_menu_keyboard(user_id)
        )
    else:
        await update.message.reply_text(message)

# --- FLASK HEALTH CHECK ---
flask_app = Flask(__name__)

@flask_app.route('/')
def dashboard():
    stats = get_stats()
    daily = load_daily()
    q_size = task_queue.qsize() if task_queue else 0
    
    total = int(stats.get("total", 0))
    success = int(stats.get("success", 0))
    failed = int(stats.get("failed", 0))
    daily_count = int(daily.get("global_count", 0))
    
    errors = stats.get("errors", {})
    
    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Tyrell's Bot Dashboard 🎭</title>
        <style>
            body {{
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background-color: #0d1117;
                color: #c9d1d9;
                margin: 0;
                padding: 20px;
                display: flex;
                justify-content: center;
                align-items: center;
                min-height: 100vh;
            }}
            .container {{
                background-color: #161b22;
                padding: 40px;
                border-radius: 12px;
                box-shadow: 0 4px 20px rgba(0, 0, 0, 0.5);
                border: 1px solid #30363d;
                max-width: 600px;
                width: 100%;
            }}
            h1 {{
                text-align: center;
                color: #58a6ff;
                margin-bottom: 30px;
                font-size: 24px;
            }}
            .stat-grid {{
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 20px;
                margin-bottom: 20px;
            }}
            .stat-card {{
                background-color: #21262d;
                padding: 15px;
                border-radius: 8px;
                text-align: center;
                border: 1px solid #30363d;
            }}
            .stat-value {{
                font-size: 28px;
                font-weight: bold;
                color: #f0f6fc;
                margin: 5px 0;
            }}
            .stat-label {{
                font-size: 14px;
                color: #8b949e;
            }}
            .error-grid {{
                display: grid;
                grid-template-columns: repeat(3, 1fr);
                gap: 10px;
                margin-top: 20px;
            }}
            .error-card {{
                background-color: #1c2128;
                padding: 10px;
                border-radius: 6px;
                text-align: center;
                border: 1px solid #30363d;
                font-size: 12px;
            }}
            .error-value {{
                font-size: 18px;
                font-weight: bold;
                color: #da3633;
            }}
            .success {{ color: #2ea043; }}
            .failed {{ color: #da3633; }}
            .queue {{ color: #d29922; }}
            .section-title {{
                font-size: 14px;
                color: #8b949e;
                margin: 25px 0 10px 0;
                text-transform: uppercase;
                letter-spacing: 1px;
                text-align: center;
            }}
            .footer {{
                text-align: center;
                margin-top: 30px;
                font-size: 12px;
                color: #8b949e;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🎭 Tyrell's Command Center</h1>
            
            <div class="stat-grid">
                <div class="stat-card">
                    <div class="stat-label">Daily Verifications</div>
                    <div class="stat-value">{daily_count} <span style="font-size:16px; color:#8b949e">/ {DAILY_LIMIT_GLOBAL}</span></div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Queue Size</div>
                    <div class="stat-value queue">{q_size}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Total Processed</div>
                    <div class="stat-value">{total}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Success Rate</div>
                    <div class="stat-value">{(success / total * 100) if total > 0 else 0:.1f}%</div>
                </div>
            </div>

            <div class="stat-card" style="display: flex; justify-content: space-around;">
                <div>
                    <div class="stat-value success">{success}</div>
                    <div class="stat-label">Success ✅</div>
                </div>
                <div>
                    <div class="stat-value failed">{failed}</div>
                    <div class="stat-label">Failed ❌</div>
                </div>
            </div>

            <div class="section-title">⚠️ Failure Breakdown</div>
            <div class="error-grid">
                <div class="error-card">
                    <div class="error-value">{errors.get('submit_failed', 0)}</div>
                    <div class="stat-label">Submit Failed</div>
                </div>
                <div class="error-card">
                    <div class="error-value">{errors.get('api_error', 0)}</div>
                    <div class="stat-label">API Error</div>
                </div>
                <div class="error-card">
                    <div class="error-value">{errors.get('no_upload_url', 0)}</div>
                    <div class="stat-label">No Upload URL</div>
                </div>
                <div class="error-card">
                    <div class="error-value">{errors.get('upload_failed', 0)}</div>
                    <div class="stat-label">Upload Failed</div>
                </div>
                <div class="error-card">
                    <div class="error-value">{errors.get('unknown_step', 0)}</div>
                    <div class="stat-label">Unknown Step</div>
                </div>
                <div class="error-card">
                    <div class="error-value">{errors.get('other', 0)}</div>
                    <div class="stat-label">Other</div>
                </div>
            </div>

            <div class="footer">
                Tyrell's Verification Bot • Running on Port {PORT}
            </div>
        </div>
        <script>
            // Auto-refresh every 30 seconds
            setTimeout(function() {{
                location.reload();
            }}, 30000);
        </script>
    </body>
    </html>
    """
    return html, 200

@flask_app.route(f'/{ADMIN_ROUTE}', methods=['GET', 'POST'])
def admin():
    broadcast_result = None
    
    if request.method == 'POST':
        if request.form.get('password') == ADMIN_PASSWORD:
            session['admin_logged_in'] = True
            return redirect(url_for('admin'))
        
        if not session.get('admin_logged_in'):
            return "Unauthorized", 401
            
        action = request.form.get('action')
        if action == 'create':
            code = request.form.get('code', '').upper().strip()
            try:
                credits = int(request.form.get('credits', 0) or 0)
                max_uses = int(request.form.get('max_uses', 0) or 0)
            except ValueError:
                credits = 0
                max_uses = 0
            expires_at = request.form.get('expires_at')
            
            if code:
                codes = load_codes()
                codes[code] = {
                    "credits": credits,
                    "max_uses": max_uses if max_uses > 0 else None,
                    "current_uses": 0,
                    "expires_at": expires_at if expires_at else None,
                    "redeemed_by": []
                }
                save_codes(codes)
        
        elif action == 'delete':
            code = request.form.get('code')
            codes = load_codes()
            if code in codes:
                del codes[code]
                save_codes(codes)
                
        elif action == 'broadcast':
            message = request.form.get('message', '').strip()
            if message:
                # Store broadcast request (will be processed by bot)
                broadcast_file = Path(__file__).parent / "broadcast.json"
                broadcast_file.write_text(json.dumps({
                    "message": message,
                    "timestamp": datetime.now().isoformat(),
                    "status": "pending"
                }))
                broadcast_result = "Broadcast queued! It will be sent shortly."
                
        elif action == 'logout':
            session.pop('admin_logged_in', None)
            return redirect(url_for('dashboard'))
            
        if action != 'broadcast':
            return redirect(url_for('admin'))

    if not session.get('admin_logged_in'):
        return """
        <body style="background:#0d1117;color:#c9d1d9;font-family:sans-serif;display:flex;justify-content:center;align-items:center;height:100vh;">
            <form method="POST" style="background:#161b22;padding:40px;border-radius:12px;border:1px solid #30363d;">
                <h2>Admin Login</h2>
                <input type="password" name="password" placeholder="Password" style="padding:10px;width:200px;border-radius:4px;border:1px solid #30363d;background:#0d1117;color:#fff;"><br><br>
                <button type="submit" style="padding:10px 20px;background:#2ea043;color:white;border:none;border-radius:4px;cursor:pointer;">Login</button>
            </form>
        </body>
        """

    codes = load_codes()
    codes_html = ""
    for c, d in codes.items():
        codes_html += f"""
        <tr style="border-bottom: 1px solid #30363d;">
            <td style="padding:10px;">{c}</td>
            <td style="padding:10px;">{d['credits']}</td>
            <td style="padding:10px;">{d.get('current_uses', 0)} / {d['max_uses'] if d['max_uses'] else '∞'}</td>
            <td style="padding:10px;">{d['expires_at'] if d['expires_at'] else 'Never'}</td>
            <td style="padding:10px;">
                <form method="POST" style="display:inline;">
                    <input type="hidden" name="action" value="delete">
                    <input type="hidden" name="code" value="{c}">
                    <button type="submit" style="background:#da3633;color:white;border:none;padding:5px 10px;border-radius:4px;cursor:pointer;">Delete</button>
                </form>
            </td>
        </tr>
        """

    # Calculate user stats
    users = load_users()
    total_users = len(users)
    total_credits = sum(u.get('credits', 0) for u in users.values())
    total_verifications = sum(u.get('total_verifications', 0) for u in users.values())
    
    # Generate users table HTML (sorted by verifications)
    users_html = ""
    sorted_users = sorted(users.items(), key=lambda x: x[1].get('total_verifications', 0), reverse=True)
    for uid, udata in sorted_users[:50]:  # Top 50 users
        joined = udata.get('joined', '')[:10] if udata.get('joined') else 'Unknown'
        success_count = udata.get('success_count', 0)
        failed_count = udata.get('failed_count', 0)
        total = success_count + failed_count
        rate = f"{(success_count / total * 100):.0f}%" if total > 0 else "-"
        users_html += f"""
        <tr style="border-bottom: 1px solid #30363d;">
            <td style="padding:10px;font-family:monospace;">{uid}</td>
            <td style="padding:10px;color:#d29922;">{udata.get('credits', 0)}</td>
            <td style="padding:10px;"><span style="color:#2ea043;">{success_count}</span> / <span style="color:#da3633;">{failed_count}</span></td>
            <td style="padding:10px;color:#58a6ff;">{rate}</td>
            <td style="padding:10px;">{len(udata.get('referrals', []))}</td>
            <td style="padding:10px;color:#8b949e;">{joined}</td>
        </tr>
        """
    
    # Generate proxy health HTML
    proxies_html = ""
    total_proxies = len(proxy_health)
    healthy_proxies = sum(1 for p in proxy_health.values() if p.get("status") == "healthy")
    dead_proxies = sum(1 for p in proxy_health.values() if p.get("status") == "dead")
    
    for proxy_url, health in proxy_health.items():
        status = health.get("status", "unknown")
        failures = health.get("failures", 0)
        last_check = health.get("last_check", "Never")[:19] if health.get("last_check") else "Never"
        
        # Truncate proxy for display
        try:
            display_proxy = proxy_url.split('@')[1][:25] + "..."
        except:
            display_proxy = proxy_url[:30] + "..."
        
        status_color = "#2ea043" if status == "healthy" else "#da3633" if status == "dead" else "#d29922"
        status_emoji = "✅" if status == "healthy" else "❌" if status == "dead" else "⚠️"
        
        proxies_html += f"""
        <tr style="border-bottom: 1px solid #30363d;">
            <td style="padding:8px;font-family:monospace;font-size:12px;">{display_proxy}</td>
            <td style="padding:8px;color:{status_color};">{status_emoji} {status}</td>
            <td style="padding:8px;">{failures}</td>
            <td style="padding:8px;color:#8b949e;font-size:11px;">{last_check}</td>
        </tr>
        """
    
    broadcast_msg = f'<div style="background:#2ea043;color:white;padding:10px;border-radius:4px;margin-bottom:20px;">{broadcast_result}</div>' if broadcast_result else ''

    return f"""
    <body style="background:#0d1117;color:#c9d1d9;font-family:sans-serif;padding:20px;">
        <div style="max-width:900px;margin:0 auto;background:#161b22;padding:30px;border-radius:12px;border:1px solid #30363d;">
            <div style="display:flex;justify-content:space-between;align-items:center;">
                <h2>�️ Admin Panel</h2>
                <form method="POST"><input type="hidden" name="action" value="logout"><button type="submit" style="background:none;border:none;color:#58a6ff;cursor:pointer;text-decoration:underline;">Logout</button></form>
            </div>
            
            {broadcast_msg}
            
            <!-- User Stats -->
            <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:15px;margin-bottom:30px;">
                <div style="background:#21262d;padding:20px;border-radius:8px;text-align:center;border:1px solid #30363d;">
                    <div style="font-size:32px;font-weight:bold;color:#58a6ff;">{total_users}</div>
                    <div style="color:#8b949e;">Total Users</div>
                </div>
                <div style="background:#21262d;padding:20px;border-radius:8px;text-align:center;border:1px solid #30363d;">
                    <div style="font-size:32px;font-weight:bold;color:#d29922;">{total_credits}</div>
                    <div style="color:#8b949e;">Total Credits</div>
                </div>
                <div style="background:#21262d;padding:20px;border-radius:8px;text-align:center;border:1px solid #30363d;">
                    <div style="font-size:32px;font-weight:bold;color:#2ea043;">{total_verifications}</div>
                    <div style="color:#8b949e;">Total Verifications</div>
                </div>
            </div>
            
            <!-- Proxy Health -->
            <h3 style="margin-top:20px;">🌐 Proxy Health <span style="font-size:14px;color:#8b949e;">({healthy_proxies}/{total_proxies} healthy)</span></h3>
            <div style="max-height:200px;overflow-y:auto;margin-bottom:20px;">
                <table style="width:100%;text-align:left;border-collapse:collapse;">
                    <tr style="background:#21262d;">
                        <th style="padding:8px;">Proxy</th>
                        <th style="padding:8px;">Status</th>
                        <th style="padding:8px;">Fails</th>
                        <th style="padding:8px;">Last Check</th>
                    </tr>
                    {proxies_html}
                </table>
            </div>
            
            <!-- Broadcast Message -->
            <h3>📢 Broadcast Message</h3>
            <form method="POST" style="margin-bottom:30px;">
                <input type="hidden" name="action" value="broadcast">
                <textarea name="message" placeholder="Enter message to send to ALL users... (Supports Markdown)" required style="width:100%;height:80px;padding:10px;background:#0d1117;border:1px solid #30363d;color:white;border-radius:4px;resize:vertical;box-sizing:border-box;"></textarea>
                <button type="submit" style="margin-top:10px;background:#58a6ff;color:white;border:none;padding:10px 20px;border-radius:4px;cursor:pointer;">📤 Send to All Users</button>
            </form>
            
            <!-- Code Management -->
            <h3>🎫 Create New Code</h3>
            <form method="POST" style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr auto;gap:10px;margin-bottom:30px;">
                <input type="hidden" name="action" value="create">
                <input type="text" name="code" placeholder="CODE NAME" required style="padding:8px;background:#0d1117;border:1px solid #30363d;color:white;border-radius:4px;">
                <input type="number" name="credits" placeholder="Credits" required style="padding:8px;background:#0d1117;border:1px solid #30363d;color:white;border-radius:4px;">
                <input type="number" name="max_uses" placeholder="Max Uses (0=∞)" style="padding:8px;background:#0d1117;border:1px solid #30363d;color:white;border-radius:4px;">
                <input type="date" name="expires_at" style="padding:8px;background:#0d1117;border:1px solid #30363d;color:white;border-radius:4px;">
                <button type="submit" style="background:#2ea043;color:white;border:none;padding:8px 15px;border-radius:4px;cursor:pointer;">Create</button>
            </form>

            <h3>Active Codes</h3>
            <table style="width:100%;text-align:left;border-collapse:collapse;">
                <tr style="background:#21262d;">
                    <th style="padding:10px;">Code</th>
                    <th style="padding:10px;">Credits</th>
                    <th style="padding:10px;">Uses</th>
                    <th style="padding:10px;">Expiry</th>
                    <th style="padding:10px;">Action</th>
                </tr>
                {codes_html}
            </table>
            
            <!-- User Analytics -->
            <h3 style="margin-top:30px;">👥 User Analytics</h3>
            <table style="width:100%;text-align:left;border-collapse:collapse;">
                <tr style="background:#21262d;">
                    <th style="padding:10px;">User ID</th>
                    <th style="padding:10px;">Credits</th>
                    <th style="padding:10px;">✅/❌</th>
                    <th style="padding:10px;">Rate</th>
                    <th style="padding:10px;">Refs</th>
                    <th style="padding:10px;">Joined</th>
                </tr>
                {users_html}
            </table>
            <br>
            <a href="/" style="color:#58a6ff;">&larr; Back to Dashboard</a>
        </div>
    </body>
    """

def run_flask():
    import logging as flask_logging
    flask_logging.getLogger('werkzeug').setLevel(flask_logging.WARNING)
    flask_app.secret_key = FLASK_SECRET_KEY
    flask_app.run(host='0.0.0.0', port=PORT, threaded=True)

# --- BROADCAST WORKER ---
BROADCAST_FILE = Path(__file__).parent / "broadcast.json"

async def broadcast_worker(application: Application):
    """Background task that checks for and processes broadcast messages"""
    while True:
        await asyncio.sleep(5)  # Check every 5 seconds
        
        if not BROADCAST_FILE.exists():
            continue
            
        try:
            data = json.loads(BROADCAST_FILE.read_text())
            if data.get("status") != "pending":
                continue
                
            message = data.get("message", "")
            if not message:
                continue
                
            # Mark as processing
            data["status"] = "processing"
            BROADCAST_FILE.write_text(json.dumps(data))
            
            users = load_users()
            sent = 0
            failed = 0
            
            for user_id in users.keys():
                try:
                    await application.bot.send_message(
                        chat_id=int(user_id),
                        text=f"📢 **ANNOUNCEMENT**\n\n{message}",
                        parse_mode="Markdown"
                    )
                    sent += 1
                    await asyncio.sleep(0.1)  # Avoid rate limits
                except Exception as e:
                    logger.warning(f"Failed to send broadcast to {user_id}: {e}")
                    failed += 1
            
            # Mark as completed
            data["status"] = "completed"
            data["sent"] = sent
            data["failed"] = failed
            BROADCAST_FILE.write_text(json.dumps(data))
            logger.info(f"Broadcast completed: {sent} sent, {failed} failed")
            
        except Exception as e:
            logger.error(f"Broadcast error: {e}")

# --- KEEP ALIVE WORKER ---
async def keep_alive_worker():
    """Ping the service URL every 10 minutes to prevent Render from sleeping"""
    if not KEEP_ALIVE_URL:
        logger.info("KEEP_ALIVE_URL not set, skipping keep-alive worker")
        return
    
    logger.info(f"Keep-alive worker started, pinging {KEEP_ALIVE_URL}")
    consecutive_failures = 0
    
    while True:
        await asyncio.sleep(KEEP_ALIVE_INTERVAL)
        
        success = False
        
        # Try 1: External URL ping
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(KEEP_ALIVE_URL)
                if response.status_code == 200:
                    success = True
                    consecutive_failures = 0
                    logger.debug(f"Keep-alive ping OK: {response.status_code}")
        except Exception as e:
            logger.warning(f"Keep-alive external ping failed: {e}")
        
        # Try 2: Localhost fallback if external failed
        if not success:
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    response = await client.get(f"http://localhost:{PORT}/")
                    if response.status_code == 200:
                        success = True
                        logger.debug("Keep-alive localhost ping OK")
            except Exception as e:
                logger.warning(f"Keep-alive localhost ping also failed: {e}")
        
        # Track failures
        if not success:
            consecutive_failures += 1
            if consecutive_failures >= KEEP_ALIVE_MAX_FAILURES:
                logger.error(f"Keep-alive failed {consecutive_failures} times in a row!")

# --- PROXY HEALTH CHECK WORKER ---
async def check_single_proxy(proxy: str, retries: int = 2) -> bool:
    """
    Test a single proxy with retry logic for slow proxies.
    Returns True if healthy.
    
    - First attempt: 15 second timeout (warm-up)
    - Retry attempts: 10 second timeout
    - Total: up to 3 attempts before marking as failed
    """
    for attempt in range(retries + 1):
        timeout = 15 if attempt == 0 else PROXY_CHECK_TIMEOUT  # First try gets more time
        
        try:
            async with httpx.AsyncClient(timeout=timeout, proxy=proxy) as client:
                response = await client.get("https://api.ipify.org")
                if response.status_code == 200:
                    return True
        except:
            try:
                # Fallback for older httpx
                async with httpx.AsyncClient(timeout=timeout, proxies=proxy) as client:
                    response = await client.get("https://api.ipify.org")
                    if response.status_code == 200:
                        return True
            except:
                pass
        
        # Wait before retry
        if attempt < retries:
            await asyncio.sleep(2)
    
    return False

async def proxy_health_worker():
    """Check proxy health every 30 minutes"""
    global proxy_health
    
    proxies = load_proxies()
    if not proxies:
        logger.info("No proxies configured, skipping health check worker")
        return
    
    logger.info(f"Proxy health worker started, monitoring {len(proxies)} proxies")
    
    # Initial check on startup
    await asyncio.sleep(10)  # Wait for everything to initialize
    
    while True:
        proxies = load_proxies()  # Reload in case they changed
        
        for proxy in proxies:
            # Initialize if not exists
            if proxy not in proxy_health:
                proxy_health[proxy] = {"status": "unknown", "failures": 0, "last_check": None}
            
            is_healthy = await check_single_proxy(proxy)
            now = datetime.now().isoformat()
            
            if is_healthy:
                proxy_health[proxy] = {
                    "status": "healthy",
                    "failures": 0,
                    "last_check": now
                }
            else:
                proxy_health[proxy]["failures"] += 1
                proxy_health[proxy]["last_check"] = now
                
                if proxy_health[proxy]["failures"] >= PROXY_MAX_FAILURES:
                    proxy_health[proxy]["status"] = "dead"
                    logger.warning(f"Proxy marked as dead: {proxy[:30]}...")
                else:
                    proxy_health[proxy]["status"] = "unhealthy"
            
            await asyncio.sleep(1)  # Small delay between checks
        
        healthy = sum(1 for p in proxy_health.values() if p["status"] == "healthy")
        unhealthy = sum(1 for p in proxy_health.values() if p["status"] == "unhealthy")
        dead = sum(1 for p in proxy_health.values() if p["status"] == "dead")
        logger.info(f"Proxy check complete: {healthy} healthy, {unhealthy} unhealthy, {dead} dead")
        
        await asyncio.sleep(PROXY_CHECK_INTERVAL)

# --- POST INIT ---
async def post_init(application: Application):
    global task_queue
    task_queue = asyncio.Queue()
    asyncio.create_task(worker(application))
    asyncio.create_task(broadcast_worker(application))
    asyncio.create_task(keep_alive_worker())
    asyncio.create_task(proxy_health_worker())
    logger.info("Bot initialized. Worker tasks started.")

# --- MAIN ---
def main():
    if not TOKEN:
        print("❌ Yo, where's the TELEGRAM_BOT_TOKEN?")
        print("   Set it: export TELEGRAM_BOT_TOKEN='your_token'")
        return

    Thread(target=run_flask, daemon=True).start()
    logger.info(f"Flask health check on port {PORT}")

    application = Application.builder().token(TOKEN).post_init(post_init).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("redeem", redeem_handler))
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Tyrell's Bot is online and ready to roll! 🎭")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
