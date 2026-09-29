import os
import sqlite3
import logging
from datetime import datetime, time
from zoneinfo import ZoneInfo

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID_RAW = os.getenv("ADMIN_ID")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set.")

if not ADMIN_ID_RAW:
    raise RuntimeError("ADMIN_ID is not set.")

try:
    ADMIN_ID = int(ADMIN_ID_RAW)
except ValueError:
    raise RuntimeError("ADMIN_ID must be a number.")

# Database is stored beside bot.py.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, "cafinet.db")

IRAN_TZ = ZoneInfo("Asia/Tehran")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger("CafiNetOnline24")


# =========================================================
# TIME
# =========================================================

def iran_now():
    return datetime.now(IRAN_TZ)


def now_text():
    return iran_now().strftime("%Y-%m-%d %H:%M:%S")


def today_text():
    return iran_now().strftime("%Y-%m-%d")


def is_bot_closed():
    current = iran_now().time()
    return current >= time(23, 0) or current < time(7, 0)


def closed_message():
    return (
        "🌙 کافی‌نت آنلاین ۲۴ در حال حاضر غیرفعال است.\n\n"
        "🕚 ساعت فعالیت:\n"
        "☀️ ۰۷:۰۰ تا ۲۳:۰۰\n\n"
        "⏰ لطفاً بعد از ساعت ۷ صبح دوباره مراجعه کنید."
    )


# =========================================================
# DATABASE
# =========================================================

def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tracking_code TEXT UNIQUE,
            user_id INTEGER NOT NULL,
            username TEXT,
            full_name TEXT NOT NULL,
            phone TEXT NOT NULL,
            telegram_id TEXT,
            description TEXT NOT NULL,
            category TEXT NOT NULL,
            service TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tracking_code TEXT NOT NULL,
            sender_type TEXT NOT NULL,
            sender_id INTEGER NOT NULL,
            message TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS registrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            registration_date TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()


# =========================================================
# REQUEST DATABASE FUNCTIONS
# =========================================================

def create_request(
    user_id,
    username,
    full_name,
    phone,
    telegram_id,
    description,
    category,
    service,
):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO requests (
            tracking_code,
            user_id,
            username,
            full_name,
            phone,
            telegram_id,
            description,
            category,
            service,
            status,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        "TEMP",
        user_id,
        username,
        full_name,
        phone,
        telegram_id,
        description,
        category,
        service,
        "در انتظار بررسی",
        now_text(),
        now_text(),
    ))

    request_id = cur.lastrowid
    tracking_code = f"CF{10000 + request_id}"

    cur.execute(
        """
        UPDATE requests
        SET tracking_code = ?
        WHERE id = ?
        """,
        (tracking_code, request_id),
    )

    conn.commit()

    row = cur.execute(
        "SELECT * FROM requests WHERE id = ?",
        (request_id,),
    ).fetchone()

    conn.close()

    return row


def get_request(tracking_code):
    if not tracking_code:
        return None

    tracking_code = (
        tracking_code
        .strip()
        .upper()
        .replace("#", "")
    )

    conn = get_db()

    row = conn.execute(
        """
        SELECT *
        FROM requests
        WHERE tracking_code = ?
        """,
        (tracking_code,),
    ).fetchone()

    conn.close()

    return row


def get_user_requests(user_id):
    conn = get_db()

    rows = conn.execute(
        """
        SELECT *
        FROM requests
        WHERE user_id = ?
        ORDER BY id DESC
        """,
        (user_id,),
    ).fetchall()

    conn.close()

    return rows


def update_status(tracking_code, status):
    conn = get_db()

    conn.execute(
        """
        UPDATE requests
        SET status = ?,
            updated_at = ?
        WHERE tracking_code = ?
        """,
        (
            status,
            now_text(),
            tracking_code,
        ),
    )

    conn.commit()
    conn.close()


def save_message(
    tracking_code,
    sender_type,
    sender_id,
    message,
):
    conn = get_db()

    conn.execute(
        """
        INSERT INTO messages (
            tracking_code,
            sender_type,
            sender_id,
            message,
            created_at
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            tracking_code,
            sender_type,
            sender_id,
            message,
            now_text(),
        ),
    )

    conn.commit()
    conn.close()


# =========================================================
# REGISTRATIONS
# =========================================================

def add_registration(title, registration_date=None):
    if registration_date is None:
        registration_date = today_text()

    conn = get_db()

    conn.execute(
        """
        INSERT INTO registrations (
            title,
            registration_date,
            active,
            created_at
        )
        VALUES (?, ?, 1, ?)
        """,
        (
            title,
            registration_date,
            now_text(),
        ),
    )

    conn.commit()
    conn.close()


def get_today_registrations():
    conn = get_db()

    rows = conn.execute(
        """
        SELECT *
        FROM registrations
        WHERE registration_date = ?
        AND active = 1
        ORDER BY id ASC
        """,
        (today_text(),),
    ).fetchall()

    conn.close()

    return rows


def get_registration(registration_id):
    conn = get_db()

    row = conn.execute(
        """
        SELECT *
        FROM registrations
        WHERE id = ?
        AND active = 1
        """,
        (registration_id,),
    ).fetchone()

    conn.close()

    return row


def deactivate_registration(registration_id):
    conn = get_db()

    conn.execute(
        """
        UPDATE registrations
        SET active = 0
        WHERE id = ?
        """,
        (registration_id,),
    )

    conn.commit()
    conn.close()


# =========================================================
# SERVICES
# =========================================================

UPDATING_SERVICES = {
    "vehicle": "🚗 خودرو",
    "insurance": "🛡️ بیمه",
    "tax": "💰 مالیاتی",
    "judicial": "⚖️ قضایی",
    "bank": "🏦 بانکی",
    "loan": "💵 وام",
    "medical": "🏥 درمانی",
    "education": "🎓 آموزشی",
    "ticket": "🎫 بلیط",
    "bill": "🧾 قبوض",
    "other": "➕ سایر خدمات",
}


# =========================================================
# USER STATES
# =========================================================

USER_STATES = {}

STATE_REG_FULLNAME = "reg_fullname"
STATE_REG_PHONE = "reg_phone"
STATE_REG_TELEGRAM = "reg_telegram"
STATE_REG_DESCRIPTION = "reg_description"

STATE_OTHER_FULLNAME = "other_fullname"
STATE_OTHER_PHONE = "other_phone"
STATE_OTHER_TELEGRAM = "other_telegram"
STATE_OTHER_DESCRIPTION = "other_description"

STATE_TRACKING = "tracking"

STATE_SUPPORT_CODE = "support_code"
STATE_SUPPORT_MESSAGE = "support_message"

STATE_ADMIN_SUPPORT_MESSAGE = "admin_support_message"
STATE_ADMIN_ADD_REG = "admin_add_reg"


# =========================================================
# KEYBOARDS
# =========================================================

def main_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📝 ثبت‌نام‌های آنلاین",
                callback_data="online_regs",
            )
        ],

        [
            InlineKeyboardButton(
                "🚗 خودرو",
                callback_data="updating|vehicle",
            ),
            InlineKeyboardButton(
                "🛡️ بیمه",
                callback_data="updating|insurance",
            ),
        ],

        [
            InlineKeyboardButton(
                "💰 مالیاتی",
                callback_data="updating|tax",
            ),
            InlineKeyboardButton(
                "⚖️ قضایی",
                callback_data="updating|judicial",
            ),
        ],

        [
            InlineKeyboardButton(
                "🏦 بانکی",
                callback_data="updating|bank",
            ),
            InlineKeyboardButton(
                "💵 وام",
                callback_data="updating|loan",
            ),
        ],

        [
            InlineKeyboardButton(
                "🏥 درمانی",
                callback_data="updating|medical",
            ),
            InlineKeyboardButton(
                "🎓 آموزشی",
                callback_data="updating|education",
            ),
        ],

        [
            InlineKeyboardButton(
                "🎫 بلیط",
                callback_data="updating|ticket",
            ),
            InlineKeyboardButton(
                "🧾 قبوض",
                callback_data="updating|bill",
            ),
        ],

        [
            InlineKeyboardButton(
                "➕ سایر خدمات",
                callback_data="updating|other",
            )
        ],

        [
            InlineKeyboardButton(
                "🔎 پیگیری درخواست",
                callback_data="tracking",
            ),
            InlineKeyboardButton(
                "📋 درخواست‌های من",
                callback_data="my_requests",
            ),
        ],

        [
            InlineKeyboardButton(
                "💬 پشتیبانی",
                callback_data="support",
            ),
            InlineKeyboardButton(
                "ℹ️ درباره ما",
                callback_data="about",
            ),
        ],
    ])


def home_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🏠 منوی اصلی",
                callback_data="home",
            )
        ]
    ])


def registrations_keyboard():
    rows = []

    registrations = get_today_registrations()

    for registration in registrations:
        rows.append([
            InlineKeyboardButton(
                f"📝 {registration['title']}",
                callback_data=f"registration|{registration['id']}",
            )
        ])

    rows.append([
        InlineKeyboardButton(
            "➕ سایر ثبت‌نام‌ها",
            callback_data="other_registration",
        )
    ])

    rows.append([
        InlineKeyboardButton(
            "🔙 منوی اصلی",
            callback_data="home",
        )
    ])

    return InlineKeyboardMarkup(rows)


# =========================================================
# START
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    user = update.effective_user

    USER_STATES.pop(user.id, None)

    if (
        is_bot_closed()
        and user.id != ADMIN_ID
    ):
        await update.message.reply_text(
            closed_message()
        )
        return

    await update.message.reply_text(
        "🌐 کافی‌نت آنلاین ۲۴\n\n"
        "به سامانه خدمات آنلاین خوش آمدید.\n\n"
        "📌 خدمت موردنظر خود را انتخاب کنید:",
        reply_markup=main_keyboard(),
    )


# =========================================================
# ONLINE REGISTRATIONS
# =========================================================

async def show_online_registrations(query):
    registrations = get_today_registrations()

    if registrations:
        text = (
            "📝 ثبت‌نام‌های آنلاین امروز\n\n"
            "ثبت‌نام موردنظر خود را انتخاب کنید:"
        )
    else:
        text = (
            "📝 ثبت‌نام‌های آنلاین امروز\n\n"
            "فعلاً ثبت‌نام فعالی برای امروز ثبت نشده است.\n\n"
            "اگر ثبت‌نام موردنظر شما در فهرست نیست، "
            "گزینه «سایر ثبت‌نام‌ها» را انتخاب کنید."
        )

    await query.edit_message_text(
        text,
        reply_markup=registrations_keyboard(),
    )


async def select_registration(
    query,
    registration_id,
):
    registration = get_registration(registration_id)

    if not registration:
        await query.answer(
            "این ثبت‌نام دیگر فعال نیست.",
            show_alert=True,
        )
        return

    user_id = query.from_user.id

    USER_STATES[user_id] = {
        "state": STATE_REG_FULLNAME,
        "category": "📝 ثبت‌نام‌های آنلاین",
        "service": registration["title"],
    }

    await query.edit_message_text(
        f"📝 ثبت‌نام: {registration['title']}\n\n"
        "👤 لطفاً نام و نام خانوادگی خود را ارسال کنید:"
    )


async def start_other_registration(query):
    user_id = query.from_user.id

    USER_STATES[user_id] = {
        "state": STATE_OTHER_FULLNAME,
        "category": "📝 ثبت‌نام‌های آنلاین",
        "service": "➕ سایر ثبت‌نام‌ها",
    }

    await query.edit_message_text(
        "➕ سایر ثبت‌نام‌ها\n\n"
        "ثبت‌نام موردنظر شما در فهرست امروز نیست.\n\n"
        "👤 لطفاً نام و نام خانوادگی خود را ارسال کنید:"
    )


# =========================================================
# REQUEST FORM
# =========================================================

async def finish_request(
    update,
    context,
    state_data,
):
    user = update.effective_user

    request = create_request(
        user_id=user.id,
        username=user.username or "",
        full_name=state_data["full_name"],
        phone=state_data["phone"],
        telegram_id=state_data.get(
            "telegram_id",
            "",
        ),
        description=state_data["description"],
        category=state_data["category"],
        service=state_data["service"],
    )

    tracking_code = request["tracking_code"]

    save_message(
        tracking_code,
        "user",
        user.id,
        request["description"],
    )

    USER_STATES.pop(user.id, None)

    await update.message.reply_text(
        "✅ درخواست شما با موفقیت ثبت شد.\n\n"
        f"🎫 کد رهگیری: {tracking_code}\n\n"
        f"📂 دسته: {request['category']}\n"
        f"🔧 خدمت: {request['service']}\n"
        "🟡 وضعیت: در انتظار بررسی\n\n"
        "⚠️ کد رهگیری خود را نگه دارید.",
        reply_markup=home_keyboard(),
    )

    admin_text = (
        "🆕 درخواست جدید\n\n"
        f"🎫 کد رهگیری: {tracking_code}\n"
        f"📂 دسته: {request['category']}\n"
        f"🔧 خدمت: {request['service']}\n\n"
        f"👤 نام: {request['full_name']}\n"
        f"📱 شماره: {request['phone']}\n"
        f"🔹 آیدی تلگرام: "
        f"{request['telegram_id'] or 'ثبت نشده'}\n\n"
        f"📝 توضیحات:\n"
        f"{request['description']}\n\n"
        "🟡 وضعیت: در انتظار بررسی"
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "✅ تأیید",
                callback_data=f"approve|{tracking_code}",
            ),
            InlineKeyboardButton(
                "❌ رد",
                callback_data=f"reject|{tracking_code}",
            ),
        ],
        [
            InlineKeyboardButton(
                "💬 پاسخ به کاربر",
                callback_data=f"admin_reply|{tracking_code}",
            )
        ],
    ])

    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=admin_text,
            reply_markup=keyboard,
        )
    except Exception:
        logger.exception(
            "Failed to notify admin"
        )


# =========================================================
# TEXT HANDLER
# =========================================================

async def handle_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    user = update.effective_user
    user_id = user.id
    text = update.message.text.strip()

    if (
        is_bot_closed()
        and user_id != ADMIN_ID
    ):
        USER_STATES.pop(user_id, None)

        await update.message.reply_text(
            closed_message()
        )
        return

    state_data = USER_STATES.get(user_id)

    if not state_data:
        await update.message.reply_text(
            "لطفاً یکی از گزینه‌های منوی اصلی را انتخاب کنید.",
            reply_markup=main_keyboard(),
        )
        return

    state = state_data["state"]

    # -----------------------------------------------------
    # NORMAL REGISTRATION
    # -----------------------------------------------------

    if state == STATE_REG_FULLNAME:
        state_data["full_name"] = text
        state_data["state"] = STATE_REG_PHONE

        await update.message.reply_text(
            "📱 لطفاً شماره همراه خود را ارسال کنید:"
        )
        return

    if state == STATE_REG_PHONE:
        state_data["phone"] = text
        state_data["state"] = STATE_REG_TELEGRAM

        await update.message.reply_text(
            "🔹 آیدی تلگرام خود را ارسال کنید.\n\n"
            "اگر آیدی ندارید، بنویسید «ندارم»."
        )
        return

    if state == STATE_REG_TELEGRAM:
        if text in (
            "ندارم",
            "ندارم.",
            "ندارم!",
        ):
            state_data["telegram_id"] = ""
        else:
            state_data["telegram_id"] = text

        state_data["state"] = STATE_REG_DESCRIPTION

        await update.message.reply_text(
            "📝 توضیحات درخواست را ارسال کنید.\n\n"
            "اگر توضیحی ندارید، بنویسید «ندارم»."
        )
        return

    if state == STATE_REG_DESCRIPTION:
        if text in (
            "ندارم",
            "ندارم.",
            "ندارم!",
        ):
            state_data["description"] = "بدون توضیحات"
        else:
            state_data["description"] = text

        await finish_request(
            update,
            context,
            state_data,
        )
        return

    # -----------------------------------------------------
    # OTHER REGISTRATION
    # -----------------------------------------------------

    if state == STATE_OTHER_FULLNAME:
        state_data["full_name"] = text
        state_data["state"] = STATE_OTHER_PHONE

        await update.message.reply_text(
            "📱 لطفاً شماره همراه خود را ارسال کنید:"
        )
        return

    if state == STATE_OTHER_PHONE:
        state_data["phone"] = text
        state_data["state"] = STATE_OTHER_TELEGRAM

        await update.message.reply_text(
            "🔹 آیدی تلگرام خود را ارسال کنید.\n\n"
            "اگر آیدی ندارید، بنویسید «ندارم»."
        )
        return

    if state == STATE_OTHER_TELEGRAM:
        if text in (
            "ندارم",
            "ندارم.",
            "ندارم!",
        ):
            state_data["telegram_id"] = ""
        else:
            state_data["telegram_id"] = text

        state_data["state"] = STATE_OTHER_DESCRIPTION

        await update.message.reply_text(
            "📝 توضیحات *اجباری* است.\n\n"
            "لطفاً نام یا نوع ثبت‌نام موردنظر و "
            "هر توضیح لازم را کامل بنویسید:"
        )
        return

    if state == STATE_OTHER_DESCRIPTION:
        if not text:
            await update.message.reply_text(
                "⚠️ توضیحات اجباری است.\n\n"
                "لطفاً توضیحات درخواست را ارسال کنید:"
            )
            return

        state_data["description"] = text

        await finish_request(
            update,
            context,
            state_data,
        )
        return

    # -----------------------------------------------------
    # TRACKING
    # -----------------------------------------------------

    if state == STATE_TRACKING:
        tracking_code = (
            text.upper()
            .replace("#", "")
        )

        request = get_request(
            tracking_code
        )

        if not request:
            await update.message.reply_text(
                "❌ درخواست با این کد رهگیری پیدا نشد.\n\n"
                "کد را دوباره ارسال کنید:"
            )
            return

        if (
            request["user_id"] != user_id
            and user_id != ADMIN_ID
        ):
            USER_STATES.pop(user_id, None)

            await update.message.reply_text(
                "❌ این درخواست متعلق به شما نیست.",
                reply_markup=home_keyboard(),
            )
            return

        USER_STATES.pop(user_id, None)

        await send_request_details(
            update.message.chat_id,
            request,
            context,
        )
        return

    # -----------------------------------------------------
    # USER SUPPORT CODE
    # -----------------------------------------------------

    if state == STATE_SUPPORT_CODE:
        tracking_code = (
            text.upper()
            .replace("#", "")
        )

        request = get_request(
            tracking_code
        )

        if not request:
            await update.message.reply_text(
                "❌ کد رهگیری پیدا نشد.\n\n"
                "دوباره ارسال کنید:"
            )
            return

        if request["user_id"] != user_id:
            USER_STATES.pop(user_id, None)

            await update.message.reply_text(
                "❌ این درخواست متعلق به شما نیست.",
                reply_markup=home_keyboard(),
            )
            return

        state_data["tracking"] = tracking_code
        state_data["state"] = STATE_SUPPORT_MESSAGE

        await update.message.reply_text(
            f"💬 پشتیبانی درخواست {tracking_code}\n\n"
            "پیام خود را ارسال کنید:"
        )
        return

    # -----------------------------------------------------
    # USER SUPPORT MESSAGE
    # -----------------------------------------------------

    if state == STATE_SUPPORT_MESSAGE:
        tracking_code = state_data["tracking"]

        request = get_request(
            tracking_code
        )

        if not request:
            USER_STATES.pop(user_id, None)

            await update.message.reply_text(
                "❌ درخواست پیدا نشد.",
                reply_markup=home_keyboard(),
            )
            return

        save_message(
            tracking_code,
            "user",
            user_id,
            text,
        )

        USER_STATES.pop(user_id, None)

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "💬 پاسخ",
                    callback_data=(
                        f"admin_reply|{tracking_code}"
                    ),
                )
            ]
        ])

        try:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    "💬 پیام جدید از کاربر\n\n"
                    f"🎫 کد رهگیری: {tracking_code}\n"
                    f"👤 {request['full_name']}\n\n"
                    f"📝 پیام:\n{text}"
                ),
                reply_markup=keyboard,
            )
        except Exception:
            logger.exception(
                "Support notification failed"
            )

        await update.message.reply_text(
            "✅ پیام شما برای پشتیبانی ارسال شد.",
            reply_markup=home_keyboard(),
        )
        return

    # -----------------------------------------------------
    # ADMIN REPLY
    # -----------------------------------------------------

    if state == STATE_ADMIN_SUPPORT_MESSAGE:
        if user_id != ADMIN_ID:
            USER_STATES.pop(user_id, None)
            return

        tracking_code = state_data["tracking"]

        request = get_request(
            tracking_code
        )

        if not request:
            USER_STATES.pop(user_id, None)

            await update.message.reply_text(
                "❌ درخواست پیدا نشد."
            )
            return

        save_message(
            tracking_code,
            "admin",
            ADMIN_ID,
            text,
        )

        USER_STATES.pop(user_id, None)

        try:
            await context.bot.send_message(
                chat_id=request["user_id"],
                text=(
                    "💬 پاسخ پشتیبانی\n\n"
                    f"🎫 کد رهگیری: {tracking_code}\n\n"
                    f"{text}"
                ),
            )
        except Exception:
            logger.exception(
                "Failed to send admin reply"
            )

        await update.message.reply_text(
            "✅ پاسخ برای کاربر ارسال شد."
        )
        return

    # -----------------------------------------------------
    # ADMIN ADD REGISTRATION
    # -----------------------------------------------------

    if state == STATE_ADMIN_ADD_REG:
        if user_id != ADMIN_ID:
            USER_STATES.pop(user_id, None)
            return

        if not text:
            await update.message.reply_text(
                "❌ نام ثبت‌نام نمی‌تواند خالی باشد."
            )
            return

        add_registration(text)

        USER_STATES.pop(user_id, None)

        await update.message.reply_text(
            f"✅ ثبت‌نام «{text}» برای امروز اضافه شد.\n\n"
            "کاربران از بخش ثبت‌نام‌های آنلاین آن را می‌بینند."
        )
        return


# =========================================================
# REQUEST DETAILS
# =========================================================

async def send_request_details(
    chat_id,
    request,
    context,
):
    text = (
        "📋 جزئیات درخواست\n\n"
        f"🎫 کد رهگیری: {request['tracking_code']}\n"
        f"📂 دسته: {request['category']}\n"
        f"🔧 خدمت: {request['service']}\n\n"
        f"👤 نام: {request['full_name']}\n"
        f"📱 شماره: {request['phone']}\n"
        f"🔹 آیدی تلگرام: "
        f"{request['telegram_id'] or 'ثبت نشده'}\n\n"
        f"📝 توضیحات:\n"
        f"{request['description']}\n\n"
        f"📌 وضعیت: {request['status']}\n"
        f"🕐 ثبت: {request['created_at']}"
    )

    await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=home_keyboard(),
    )


# =========================================================
# CALLBACK HANDLER
# =========================================================

async def callback_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query

    await query.answer()

    user_id = query.from_user.id
    data = query.data or ""

    if (
        is_bot_closed()
        and user_id != ADMIN_ID
    ):
        USER_STATES.pop(user_id, None)

        await query.edit_message_text(
            closed_message(),
        )
        return

    # -----------------------------------------------------
    # HOME
    # -----------------------------------------------------

    if data == "home":
        USER_STATES.pop(user_id, None)

        await query.edit_message_text(
            "🌐 کافی‌نت آنلاین ۲۴\n\n"
            "📌 خدمت موردنظر خود را انتخاب کنید:",
            reply_markup=main_keyboard(),
        )
        return

    # -----------------------------------------------------
    # ONLINE REGISTRATIONS
    # -----------------------------------------------------

    if data == "online_regs":
        USER_STATES.pop(user_id, None)

        await show_online_registrations(
            query
        )
        return

    if data == "other_registration":
        await start_other_registration(
            query
        )
        return

    if data.startswith("registration|"):
        try:
            registration_id = int(
                data.split("|", 1)[1]
            )
        except ValueError:
            await query.answer(
                "خطا.",
                show_alert=True,
            )
            return

        await select_registration(
            query,
            registration_id,
        )
        return

    # -----------------------------------------------------
    # UPDATING SERVICES
    # -----------------------------------------------------

    if data.startswith("updating|"):
        key = data.split(
            "|",
            1,
        )[1]

        name = UPDATING_SERVICES.get(
            key,
            "این خدمت",
        )

        await query.answer(
            "🔄 این بخش در حال بروزرسانی است.",
            show_alert=True,
        )

        await query.edit_message_text(
            f"{name}\n\n"
            "🔄 این بخش در حال بروزرسانی است.\n\n"
            "به‌زودی فعال خواهد شد.",
            reply_markup=home_keyboard(),
        )
        return

    # -----------------------------------------------------
    # TRACKING
    # -----------------------------------------------------

    if data == "tracking":
        USER_STATES[user_id] = {
            "state": STATE_TRACKING
        }

        await query.edit_message_text(
            "🔎 پیگیری درخواست\n\n"
            "کد رهگیری خود را ارسال کنید:"
        )
        return

    # -----------------------------------------------------
    # MY REQUESTS
    # -----------------------------------------------------

    if data == "my_requests":
        requests = get_user_requests(
            user_id
        )

        if not requests:
            await query.edit_message_text(
                "📋 درخواست‌های من\n\n"
                "هنوز درخواستی برای شما ثبت نشده است.",
                reply_markup=home_keyboard(),
            )
            return

        text = "📋 درخواست‌های من\n\n"

        for request in requests[:20]:
            text += (
                f"🎫 {request['tracking_code']}\n"
                f"🔧 {request['service']}\n"
                f"📌 {request['status']}\n"
                f"🕐 {request['created_at']}\n\n"
            )

        await query.edit_message_text(
            text,
            reply_markup=home_keyboard(),
        )
        return

    # -----------------------------------------------------
    # SUPPORT
    # -----------------------------------------------------

    if data == "support":
        USER_STATES[user_id] = {
            "state": STATE_SUPPORT_CODE
        }

        await query.edit_message_text(
            "💬 پشتیبانی\n\n"
            "کد رهگیری درخواست خود را ارسال کنید:"
        )
        return

    # -----------------------------------------------------
    # ABOUT
    # -----------------------------------------------------

    if data == "about":
        await query.edit_message_text(
            "ℹ️ درباره کافی‌نت آنلاین ۲۴\n\n"
            "سامانه ثبت و پیگیری خدمات آنلاین.\n\n"
            "🕚 ساعت فعالیت: ۰۷:۰۰ تا ۲۳:۰۰\n\n"
            "📌 ثبت درخواست، پیگیری و ارتباط "
            "با پشتیبانی از داخل ربات انجام می‌شود.",
            reply_markup=home_keyboard(),
        )
        return

    # =====================================================
    # ADMIN
    # =====================================================

    if user_id != ADMIN_ID:
        return

    # -----------------------------------------------------
    # APPROVE
    # -----------------------------------------------------

    if data.startswith("approve|"):
        tracking_code = data.split(
            "|",
            1,
        )[1]

        request = get_request(
            tracking_code
        )

        if not request:
            await query.answer(
                "درخواست پیدا نشد.",
                show_alert=True,
            )
            return

        update_status(
            tracking_code,
            "تأیید شده",
        )

        try:
            await context.bot.send_message(
                chat_id=request["user_id"],
                text=(
                    "🟢 درخواست شما تأیید شد.\n\n"
                    f"🎫 کد رهگیری: {tracking_code}"
                ),
            )
        except Exception:
            logger.exception(
                "Approval notification failed"
            )

        await query.edit_message_text(
            query.message.text
            + "\n\n🟢 وضعیت: تأیید شده"
        )
        return

    # -----------------------------------------------------
    # REJECT
    # -----------------------------------------------------

    if data.startswith("reject|"):
        tracking_code = data.split(
            "|",
            1,
        )[1]

        request = get_request(
            tracking_code
        )

        if not request:
            await query.answer(
                "درخواست پیدا نشد.",
                show_alert=True,
            )
            return

        update_status(
            tracking_code,
            "رد شده",
        )

        try:
            await context.bot.send_message(
                chat_id=request["user_id"],
                text=(
                    "🔴 درخواست شما رد شد.\n\n"
                    f"🎫 کد رهگیری: {tracking_code}\n\n"
                    "برای پیگیری بیشتر می‌توانید "
                    "با پشتیبانی ارتباط بگیرید."
                ),
            )
        except Exception:
            logger.exception(
                "Rejection notification failed"
            )

        await query.edit_message_text(
            query.message.text
            + "\n\n🔴 وضعیت: رد شده"
        )
        return

    # -----------------------------------------------------
    # ADMIN REPLY
    # -----------------------------------------------------

    if data.startswith("admin_reply|"):
        tracking_code = data.split(
            "|",
            1,
        )[1]

        request = get_request(
            tracking_code
        )

        if not request:
            await query.answer(
                "درخواست پیدا نشد.",
                show_alert=True,
            )
            return

        USER_STATES[ADMIN_ID] = {
            "state": STATE_ADMIN_SUPPORT_MESSAGE,
            "tracking": tracking_code,
        }

        await query.message.reply_text(
            f"💬 پاسخ به درخواست "
            f"{tracking_code} را همینجا ارسال کنید:"
        )
        return


# =========================================================
# ADMIN COMMANDS
# =========================================================

async def admin_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text(
            "⛔ دسترسی ندارید."
        )
        return

    await update.message.reply_text(
        "🛠️ پنل مدیریت\n\n"
        "/addreg — افزودن ثبت‌نام امروز\n"
        "/regs — مشاهده ثبت‌نام‌های امروز\n"
        "/delreg ID — حذف ثبت‌نام\n"
        "/find CFxxxxx — جستجوی درخواست\n"
        "/reply CFxxxxx — پاسخ به کاربر"
    )


async def addreg_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if update.effective_user.id != ADMIN_ID:
        return

    if not context.args:
        USER_STATES[ADMIN_ID] = {
            "state": STATE_ADMIN_ADD_REG
        }

        await update.message.reply_text(
            "📝 نام ثبت‌نامی که می‌خواهید "
            "برای امروز اضافه شود را ارسال کنید:"
        )
        return

    title = " ".join(
        context.args
    ).strip()

    add_registration(title)

    await update.message.reply_text(
        f"✅ «{title}» برای امروز اضافه شد."
    )


async def regs_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if update.effective_user.id != ADMIN_ID:
        return

    registrations = get_today_registrations()

    if not registrations:
        await update.message.reply_text(
            "📝 برای امروز هیچ ثبت‌نام فعالی وجود ندارد."
        )
        return

    text = "📝 ثبت‌نام‌های امروز:\n\n"

    for registration in registrations:
        text += (
            f"ID: {registration['id']}\n"
            f"📝 {registration['title']}\n\n"
        )

    await update.message.reply_text(
        text
    )


async def delreg_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if update.effective_user.id != ADMIN_ID:
        return

    if not context.args:
        await update.message.reply_text(
            "مثال:\n/delreg 3"
        )
        return

    try:
        registration_id = int(
            context.args[0]
        )
    except ValueError:
        await update.message.reply_text(
            "❌ ID باید عدد باشد."
        )
        return

    deactivate_registration(
        registration_id
    )

    await update.message.reply_text(
        "✅ ثبت‌نام غیرفعال شد."
    )


async def find_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if update.effective_user.id != ADMIN_ID:
        return

    if not context.args:
        await update.message.reply_text(
            "مثال:\n/find CF10001"
        )
        return

    request = get_request(
        context.args[0]
    )

    if not request:
        await update.message.reply_text(
            "❌ درخواست پیدا نشد."
        )
        return

    await send_request_details(
        update.message.chat_id,
        request,
        context,
    )


async def reply_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if update.effective_user.id != ADMIN_ID:
        return

    if not context.args:
        await update.message.reply_text(
            "مثال:\n/reply CF10001"
        )
        return

    tracking_code = (
        context.args[0]
        .upper()
        .replace("#", "")
    )

    request = get_request(
        tracking_code
    )

    if not request:
        await update.message.reply_text(
            "❌ درخواست پیدا نشد."
        )
        return

    USER_STATES[ADMIN_ID] = {
        "state": STATE_ADMIN_SUPPORT_MESSAGE,
        "tracking": tracking_code,
    }

    await update.message.reply_text(
        f"💬 پاسخ به {tracking_code} را ارسال کنید:"
    )


# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
):
    logger.exception(
        "Unhandled exception",
        exc_info=context.error,
    )


# =========================================================
# MAIN
# =========================================================

def main():
    init_db()

    application = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    application.add_handler(
        CommandHandler(
            "admin",
            admin_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "addreg",
            addreg_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "regs",
            regs_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "delreg",
            delreg_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "find",
            find_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "reply",
            reply_command,
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            callback_handler
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_text,
        )
    )

    application.add_error_handler(
        error_handler
    )

    logger.info(
        "CafiNetOnline24 bot started."
    )

    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()
