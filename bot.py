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
from flask import Flask
from threading import Thread

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
STATS_FILE = Path(__file__).parent / "stats.json"
USERS_FILE = Path(__file__).parent / "users.json"
DAILY_FILE = Path(__file__).parent / "daily.json"
PROXIES_FILE = Path(__file__).parent / "proxies.json"

# Credits Configuration
INITIAL_CREDITS = 3
VERIFICATION_COST = 1
REFERRAL_BONUS = 2
DAILY_LIMIT = 24

# --- PROXY MANAGEMENT ---
def load_proxies() -> list:
    """Load proxies from ENV or file. Returns empty list if no proxies."""
    # 1. Try Environment Variable (Perfect for Render)
    env_proxies = os.getenv("PROXIES_JSON")
    if env_proxies:
        try:
            proxies = json.loads(env_proxies)
            if isinstance(proxies, list):
                return [p for p in proxies if p]
        except:
            logger.error("Failed to parse PROXIES_JSON env var")

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
    """Get a random proxy. Returns (proxy_string, display_name)"""
    proxies = load_proxies()
    if not proxies:
        return None, "DIRECT 🏠"
    
    proxy = random.choice(proxies)
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

# --- DAILY LIMIT ---
def load_daily() -> dict:
    """Load daily stats"""
    if DAILY_FILE.exists():
        try:
            data = json.loads(DAILY_FILE.read_text())
            # Reset if it's a new day
            if data.get("date") != str(date.today()):
                return {"date": str(date.today()), "count": 0}
            return data
        except:
            pass
    return {"date": str(date.today()), "count": 0}

def save_daily(data: dict):
    """Save daily stats"""
    DAILY_FILE.write_text(json.dumps(data, indent=2))

def check_daily_limit() -> tuple[bool, int]:
    """Check if daily limit is reached. Returns (can_proceed, remaining)"""
    daily = load_daily()
    remaining = DAILY_LIMIT - daily["count"]
    return remaining > 0, remaining

def increment_daily():
    """Increment daily counter"""
    daily = load_daily()
    daily["count"] += 1
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
    return {"total": 0, "success": 0, "failed": 0, "orgs": {}}

def get_main_menu_keyboard(user_id: int):
    user = get_user(user_id)
    credits = user.get("credits", 0)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"� My Credits: {credits}", callback_data="credits")],
        [InlineKeyboardButton("�📊 Stats & Glory", callback_data="stats"),
         InlineKeyboardButton("📋 Queue", callback_data="queue")],
        [InlineKeyboardButton("🎁 Refer Friends", callback_data="refer")],
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
            increment_daily()
            
            user = get_user(job.user_id)
            credits_left = user.get("credits", 0)

            if result.get("success"):
                fun_success = random.choice(SUCCESS_MESSAGES)
                response = (
                    "╔══════════════════════════╗\n"
                    "║   🎉 **VICTORY ROYALE**  ║\n"
                    "╚══════════════════════════╝\n\n"
                    f"*{fun_success}*\n\n"
                    "Your verification is in SheerID's hands now.\n"
                    "They'll review it like it's a college essay 📝\n\n"
                    "⏳ **ETA:** 24-48 hours\n"
                    "📧 Check your email for the good news!\n\n"
                    f"💰 **Credits remaining:** {credits_left}\n\n"
                    "_Tyrell out_ ✌️"
                )
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Another Round?", callback_data="new")],
                    [InlineKeyboardButton("🎁 Get More Credits", callback_data="refer")]
                ])
            else:
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
        daily_remaining = DAILY_LIMIT - daily.get("count", 0)
        
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
            f"📅 **Today's Slots:** {daily_remaining}/{DAILY_LIMIT}\n"
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
        daily_remaining = DAILY_LIMIT - daily.get("count", 0)
        
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
            f"📅 **Daily Slots Remaining:** {daily_remaining}/{DAILY_LIMIT}\n\n"
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
            f"📅 Daily limit: **{DAILY_LIMIT} verifications**\n\n"
            "_Failed attempts = credit refunded!_ ✨"
        )
        
        await query.edit_message_text(
            help_text,
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
    can_proceed, remaining = check_daily_limit()
    if not can_proceed:
        await update.message.reply_text(
            "╔══════════════════════════╗\n"
            "║  ⏰ **DAILY LIMIT HIT**  ║\n"
            "╚══════════════════════════╝\n\n"
            f"We've hit **{DAILY_LIMIT}** verifications today!\n\n"
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

# --- FLASK HEALTH CHECK ---
flask_app = Flask(__name__)

@flask_app.route('/')
def health_check():
    daily = load_daily()
    return f"Tyrell's Bot 🎭 | Today: {daily.get('count', 0)}/{DAILY_LIMIT}", 200

def run_flask():
    import logging as flask_logging
    flask_logging.getLogger('werkzeug').setLevel(flask_logging.WARNING)
    flask_app.run(host='0.0.0.0', port=PORT, threaded=True)

# --- POST INIT ---
async def post_init(application: Application):
    global task_queue
    task_queue = asyncio.Queue()
    asyncio.create_task(worker(application))
    logger.info("Bot initialized. Worker task started.")

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
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Tyrell's Bot is online and ready to roll! 🎭")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
