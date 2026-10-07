import os
import sqlite3
import logging

from datetime import datetime, time
from zoneinfo import ZoneInfo

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

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
    raise RuntimeError("BOT_TOKEN تنظیم نشده است.")

if not ADMIN_ID_RAW:
    raise RuntimeError("ADMIN_ID تنظیم نشده است.")

try:
    ADMIN_ID = int(ADMIN_ID_RAW)
except ValueError:
    raise RuntimeError("ADMIN_ID باید عدد باشد.")


# =========================================================
# GENERAL SETTINGS
# =========================================================

DB_NAME = "cafinet.db"

TIMEZONE = ZoneInfo("Asia/Tehran")

CHANNEL_LINK = "https://t.me/CafiNetOnlin24"
BOT_LINK = "https://t.me/CafiNetOnlinBot"

OPEN_HOUR = 7
CLOSE_HOUR = 23


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# =========================================================
# USER STATES
# =========================================================

STATE_NAME = "name"
STATE_PHONE = "phone"
STATE_TELEGRAM = "telegram"
STATE_DESCRIPTION = "description"
STATE_TRACKING = "tracking"

STATE_ADMIN_SEARCH = "admin_search"
STATE_ADMIN_ADD_REG = "admin_add_reg"
STATE_BROADCAST = "broadcast"
STATE_SUPPORT = "support"


# =========================================================
# DATABASE
# =========================================================

def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cursor = conn.cursor()

    # -----------------------------------------------------
    # Requests
    # -----------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tracking_code TEXT,
            user_id INTEGER,
            username TEXT,
            full_name TEXT,
            phone TEXT,
            telegram_id TEXT,
            description TEXT,
            category TEXT,
            service TEXT,
            status TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    """)

    # -----------------------------------------------------
    # Registrations
    # -----------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS registrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            registration_date TEXT,
            active INTEGER DEFAULT 1,
            created_at TEXT
        )
    """)

    # -----------------------------------------------------
    # Users
    # -----------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    """)

    # -----------------------------------------------------
    # Support
    # -----------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS support_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            message TEXT,
            created_at TEXT,
            replied INTEGER DEFAULT 0
        )
    """)

    conn.commit()
    conn.close()


# =========================================================
# TIME
# =========================================================

def now_tehran():
    return datetime.now(TIMEZONE)


def now_text():
    return now_tehran().strftime("%Y-%m-%d %H:%M:%S")


def is_open():
    current_hour = now_tehran().hour

    return OPEN_HOUR <= current_hour < CLOSE_HOUR


# =========================================================
# USER DATABASE
# =========================================================

def save_user(user):
    conn = get_db()
    cursor = conn.cursor()

    current_time = now_text()

    cursor.execute("""
        INSERT INTO users (
            user_id,
            username,
            full_name,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?)

        ON CONFLICT(user_id)
        DO UPDATE SET
            username = excluded.username,
            full_name = excluded.full_name,
            updated_at = excluded.updated_at
    """, (
        user.id,
        user.username or "",
        user.full_name or "",
        current_time,
        current_time,
    ))

    conn.commit()
    conn.close()


# =========================================================
# REQUEST FUNCTIONS
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
    cursor = conn.cursor()

    created_at = now_text()

    cursor.execute("""
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
        "🟡 در انتظار بررسی",
        created_at,
        created_at,
    ))

    request_id = cursor.lastrowid

    tracking_code = f"CF{10000 + request_id}"

    cursor.execute("""
        UPDATE requests
        SET tracking_code = ?
        WHERE id = ?
    """, (
        tracking_code,
        request_id,
    ))

    conn.commit()

    cursor.execute("""
        SELECT *
        FROM requests
        WHERE id = ?
    """, (request_id,))

    request = cursor.fetchone()

    conn.close()

    return request


def get_request(tracking_code):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT *
        FROM requests
        WHERE tracking_code = ?
        LIMIT 1
    """, (tracking_code,))

    request = cursor.fetchone()

    conn.close()

    return request


def update_status(tracking_code, status):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE requests
        SET
            status = ?,
            updated_at = ?
        WHERE tracking_code = ?
    """, (
        status,
        now_text(),
        tracking_code,
    ))

    conn.commit()
    conn.close()


def get_user_requests(user_id):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT *
        FROM requests
        WHERE user_id = ?
        ORDER BY id DESC
    """, (user_id,))

    requests = cursor.fetchall()

    conn.close()

    return requests


# =========================================================
# 🧾 DIGITAL RECEIPT
# =========================================================

def format_receipt(request):
    """
    ساخت رسید دیجیتال از اطلاعات واقعی درخواست
    """

    if not request:
        return "❌ اطلاعات درخواست پیدا نشد."

    tracking_code = request["tracking_code"] or "نامشخص"
    full_name = request["full_name"] or "نامشخص"
    phone = request["phone"] or "نامشخص"
    category = request["category"] or "نامشخص"
    service = request["service"] or "نامشخص"
    status = request["status"] or "🟡 در انتظار بررسی"
    created_at = request["created_at"] or ""

    # -----------------------------------------------------
    # Date / Time
    # -----------------------------------------------------

    try:
        created_dt = datetime.strptime(
            created_at,
            "%Y-%m-%d %H:%M:%S"
        )

        date_text = created_dt.strftime("%Y/%m/%d")
        time_text = created_dt.strftime("%H:%M")

    except Exception:
        date_text = "نامشخص"
        time_text = "نامشخص"

    # -----------------------------------------------------
    # Receipt
    # -----------------------------------------------------

    return (
        "╔══════════════════════════════╗\n"
        "║       🟢 CAFINET ONLINE      ║\n"
        "║        🧾 رسید درخواست       ║\n"
        "╠══════════════════════════════╣\n"
        "║ 🔢 کد پیگیری                 ║\n"
        f"║ {tracking_code:<28}║\n"
        "║                              ║\n"
        "║ 👤 نام و نام خانوادگی        ║\n"
        f"║ {full_name[:26]:<28}║\n"
        "║                              ║\n"
        "║ 📱 شماره موبایل              ║\n"
        f"║ {phone[:26]:<28}║\n"
        "║                              ║\n"
        "║ 📂 دسته‌بندی                 ║\n"
        f"║ {category[:26]:<28}║\n"
        "║                              ║\n"
        "║ 📌 خدمت                      ║\n"
        f"║ {service[:26]:<28}║\n"
        "║                              ║\n"
        "║ 📅 تاریخ                     ║\n"
        f"║ {date_text:<28}║\n"
        "║                              ║\n"
        "║ 🕐 ساعت                      ║\n"
        f"║ {time_text:<28}║\n"
        "║                              ║\n"
        "║ 📊 وضعیت                     ║\n"
        f"║ {status[:26]:<28}║\n"
        "╠══════════════════════════════╣\n"
        "║ 💰 هزینه: بدون هزینه         ║\n"
        "╚══════════════════════════════╝\n\n"
        "       🧾 CafiNetOnline24"
    )


# =========================================================
# RECEIPT KEYBOARD
# =========================================================

def receipt_keyboard(tracking_code):

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🧾 مشاهده رسید",
                callback_data=f"receipt|{tracking_code}"
            )
        ],
        [
            InlineKeyboardButton(
                "🏠 منوی اصلی",
                callback_data="home"
            )
        ]
    ])


# =========================================================
# REQUEST DETAILS
# =========================================================

def format_request_details(request):

    if not request:
        return "❌ درخواست پیدا نشد."

    return (
        "📄 جزئیات درخواست\n\n"
        f"🎫 کد رهگیری: {request['tracking_code']}\n"
        f"👤 نام: {request['full_name']}\n"
        f"📱 موبایل: {request['phone']}\n"
        f"📂 دسته‌بندی: {request['category']}\n"
        f"📌 خدمت: {request['service']}\n"
        f"📊 وضعیت: {request['status']}\n"
        f"📅 تاریخ ثبت: {request['created_at']}\n"
        f"🔄 آخرین بروزرسانی: {request['updated_at']}"
    )


# =========================================================
# SEND REQUEST DETAILS
# =========================================================

async def send_request_details(
    chat_id,
    request,
    context,
):

    if not request:
        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ درخواست پیدا نشد.",
        )
        return

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🧾 مشاهده رسید",
                callback_data=f"receipt|{request['tracking_code']}"
            )
        ],
        [
            InlineKeyboardButton(
                "🏠 منوی اصلی",
                callback_data="home"
            )
        ]
    ])

    await context.bot.send_message(
        chat_id=chat_id,
        text=format_request_details(request),
        reply_markup=keyboard,# =========================================================
# KEYBOARDS & MENUS
# =========================================================

def home_keyboard(user_id=None):
    """
    منوی اصلی ربات
    """

    keyboard = [
        [
            InlineKeyboardButton(
                "📝 ثبت‌نام‌های آنلاین",
                callback_data="online_registrations"
            )
        ],
        [
            InlineKeyboardButton(
                "🚗 خودرو",
                callback_data="category|vehicle"
            ),
            InlineKeyboardButton(
                "🛡 بیمه",
                callback_data="category|insurance"
            )
        ],
        [
            InlineKeyboardButton(
                "💰 مالیاتی",
                callback_data="category|tax"
            ),
            InlineKeyboardButton(
                "⚖️ قضایی",
                callback_data="category|judicial"
            )
        ],
        [
            InlineKeyboardButton(
                "🏦 بانکی",
                callback_data="category|bank"
            ),
            InlineKeyboardButton(
                "💵 وام",
                callback_data="category|loan"
            )
        ],
        [
            InlineKeyboardButton(
                "🔎 پیگیری درخواست",
                callback_data="tracking"
            ),
            InlineKeyboardButton(
                "📋 درخواست‌های من",
                callback_data="my_requests"
            )
        ],
        [
            InlineKeyboardButton(
                "💬 پشتیبانی",
                callback_data="support"
            ),
            InlineKeyboardButton(
                "ℹ️ درباره ما",
                callback_data="about"
            )
        ],
    ]

    if user_id == ADMIN_ID:
        keyboard.append([
            InlineKeyboardButton(
                "🛠 پنل مدیریت",
                callback_data="admin_panel"
            )
        ])

    return InlineKeyboardMarkup(keyboard)


# =========================================================
# BACK / HOME KEYBOARD
# =========================================================

def back_home_keyboard(back_callback="home"):

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🔙 بازگشت",
                callback_data=back_callback
            )
        ],
        [
            InlineKeyboardButton(
                "🏠 منوی اصلی",
                callback_data="home"
            )
        ]
    ])


# =========================================================
# ADMIN KEYBOARD
# =========================================================

def admin_keyboard():

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📥 درخواست‌های جدید",
                callback_data="admin_requests"
            )
        ],
        [
            InlineKeyboardButton(
                "🔎 جستجوی درخواست",
                callback_data="admin_search"
            )
        ],
        [
            InlineKeyboardButton(
                "➕ ثبت‌نام امروز",
                callback_data="admin_add_registration"
            )
        ],
        [
            InlineKeyboardButton(
                "📋 لیست ثبت‌نام‌ها",
                callback_data="admin_registrations"
            )
        ],
        [
            InlineKeyboardButton(
                "📊 آمار",
                callback_data="admin_stats"
            )
        ],
        [
            InlineKeyboardButton(
                "📢 ارسال همگانی",
                callback_data="admin_broadcast"
            )
        ],
        [
            InlineKeyboardButton(
                "⚙️ تنظیمات",
                callback_data="admin_settings"
            )
        ],
        [
            InlineKeyboardButton(
                "🏠 منوی اصلی",
                callback_data="home"
            )
        ]
    ])


# =========================================================
# SERVICE DATA
# =========================================================

SERVICE_CATEGORIES = {

    "vehicle": {
        "title": "🚗 خدمات خودرو",
        "services": [
            "ثبت‌نام ایران خودرو",
            "ثبت‌نام سایپا",
            "پیگیری ثبت‌نام خودرو",
            "استعلام و خدمات خودرو",
        ],
    },

    "insurance": {
        "title": "🛡 خدمات بیمه",
        "services": [
            "خدمات بیمه تأمین اجتماعی",
            "استعلام بیمه",
            "پرداخت و پیگیری بیمه",
            "سایر خدمات بیمه",
        ],
    },

    "tax": {
        "title": "💰 خدمات مالیاتی",
        "services": [
            "تشکیل پرونده مالیاتی",
            "دریافت کد مالیاتی",
            "اظهارنامه مالیاتی",
            "استعلام مالیاتی",
        ],
    },

    "judicial": {
        "title": "⚖️ خدمات قضایی",
        "services": [
            "ثبت‌نام ثنا",
            "پیگیری پرونده قضایی",
            "استعلام قضایی",
            "سایر خدمات قضایی",
        ],
    },

    "bank": {
        "title": "🏦 خدمات بانکی",
        "services": [
            "خدمات بانکی",
            "سامانه صیاد",
            "ثبت و پیگیری چک",
            "استعلام بانکی",
        ],
    },

    "loan": {
        "title": "💵 خدمات وام",
        "services": [
            "ثبت‌نام وام",
            "پیگیری وام",
            "استعلام وضعیت وام",
            "سایر خدمات وام",
        ],
    },
}


# =========================================================
# CATEGORY KEYBOARD
# =========================================================

def category_keyboard(category_key):

    category = SERVICE_CATEGORIES.get(category_key)

    if not category:
        return back_home_keyboard()

    buttons = []

    for index, service in enumerate(category["services"]):

        buttons.append([
            InlineKeyboardButton(
                f"📌 {service}",
                callback_data=f"service|{category_key}|{index}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            "🔙 بازگشت",
            callback_data="home"
        )
    ])

    return InlineKeyboardMarkup(buttons)


# =========================================================
# STATUS KEYBOARD
# =========================================================

def status_keyboard(tracking_code):

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🔵 در حال انجام",
                callback_data=f"status|doing|{tracking_code}"
            )
        ],
        [
            InlineKeyboardButton(
                "🟢 انجام شد",
                callback_data=f"status|done|{tracking_code}"
            )
        ],
        [
            InlineKeyboardButton(
                "🔴 رد شد",
                callback_data=f"status|reject|{tracking_code}"
            )
        ],
        [
            InlineKeyboardButton(
                "🧾 مشاهده رسید",
                callback_data=f"receipt|{tracking_code}"
            )
        ],
        [
            InlineKeyboardButton(
                "🛠 پنل مدیریت",
                callback_data="admin_panel"
            )
        ]
    ])


# =========================================================
# STATUS TEXT
# =========================================================

STATUS_MAP = {
    "doing": "🔵 در حال انجام",
    "done": "🟢 انجام شد",
    "reject": "🔴 رد شد",
}


# =========================================================
# ONLINE REGISTRATIONS
# =========================================================

def registration_keyboard(registrations):

    buttons = []

    for registration in registrations:

        buttons.append([
            InlineKeyboardButton(
                f"📝 {registration['title']}",
                callback_data=f"reg|{registration['id']}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            "🏠 منوی اصلی",
            callback_data="home"
        )
    ])

    return InlineKeyboardMarkup(buttons)


# =========================================================
# REGISTRATION DATABASE
# =========================================================

def add_registration(title):

    conn = get_db()
    cursor = conn.cursor()

    current_time = now_text()

    cursor.execute("""
        INSERT INTO registrations (
            title,
            registration_date,
            active,
            created_at
        )
        VALUES (?, ?, ?, ?)
    """, (
        title,
        current_time,
        1,
        current_time,
    ))

    conn.commit()
    conn.close()


def get_active_registrations():

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT *
        FROM registrations
        WHERE active = 1
        ORDER BY id DESC
    """)

    registrations = cursor.fetchall()

    conn.close()

    return registrations


def get_registration(registration_id):

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT *
        FROM registrations
        WHERE id = ?
        LIMIT 1
    """, (registration_id,))

    registration = cursor.fetchone()

    conn.close()

    return registration


def deactivate_registration(registration_id):

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE registrations
        SET active = 0
        WHERE id = ?
    """, (registration_id,))

    conn.commit()
    conn.close()


def get_all_registrations():

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT *
        FROM registrations
        ORDER BY id DESC
    """)

    registrations = cursor.fetchall()

    conn.close()

    return registrations


# =========================================================
# STATS
# =========================================================

def get_stats():

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT COUNT(*) AS total
        FROM requests
    """)

    total = cursor.fetchone()["total"]

    cursor.execute("""
        SELECT COUNT(*) AS pending
        FROM requests
        WHERE status = '🟡 در انتظار بررسی'
    """)

    pending = cursor.fetchone()["pending"]

    cursor.execute("""
        SELECT COUNT(*) AS doing
        FROM requests
        WHERE status = '🔵 در حال انجام'
    """)

    doing = cursor.fetchone()["doing"]

    cursor.execute("""
        SELECT COUNT(*) AS done
        FROM requests
        WHERE status = '🟢 انجام شد'
    """)

    done = cursor.fetchone()["done"]

    cursor.execute("""
        SELECT COUNT(*) AS rejected
        FROM requests
        WHERE status = '🔴 رد شد'
    """)

    rejected = cursor.fetchone()["rejected"]

    cursor.execute("""
        SELECT COUNT(*) AS users
        FROM users
    """)

    users = cursor.fetchone()["users"]

    conn.close()

    return {
        "total": total,
        "pending": pending,
        "doing": doing,
        "done": done,
        "rejected": rejected,
        "users": users,
    }


# =========================================================
# ADMIN REQUEST LIST
# =========================================================

def get_pending_requests():

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT *
        FROM requests
        WHERE status = '🟡 در انتظار بررسی'
        ORDER BY id ASC
    """)

    requests = cursor.fetchall()

    conn.close()

    return requests


def admin_request_keyboard(request):

    code = request["tracking_code"]

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "👁 مشاهده درخواست",
                callback_data=f"admin_view|{code}"
            )
        ],
        [
            InlineKeyboardButton(
                "🧾 مشاهده رسید",
                callback_data=f"receipt|{code}"
            )
        ],
        [
            InlineKeyboardButton(
                "🔙 درخواست‌های جدید",
                callback_data="admin_requests"
            )
        ]
    ])


# =========================================================
# SUPPORT KEYBOARD
# =========================================================

def support_keyboard():

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📨 ارسال پیام به پشتیبانی",
                callback_data="support_send"
            )
        ],
        [
            InlineKeyboardButton(
                "🏠 منوی اصلی",
                callback_data="home"
            )
        ]
    ])


# =========================================================
# OPEN HOURS MESSAGE
# =========================================================

def closed_message():

    return (
        "⏰ ربات در حال حاضر خارج از ساعت فعالیت است.\n\n"
        f"🕐 ساعات فعالیت: {OPEN_HOUR:02d}:00 تا {CLOSE_HOUR:02d}:00\n\n"
        "لطفاً در ساعات فعالیت دوباره مراجعه کنید.\n\n"
        "🟢 CafiNetOnline24"
    )


# =========================================================
# ABOUT TEXT
# =========================================================

def about_text():

    return (
        "ℹ️ درباره CafiNetOnline24\n\n"
        "🟢 کافی‌نت آنلاین ۲۴\n\n"
        "ارائه خدمات و ثبت درخواست‌های اینترنتی "
        "به‌صورت آنلاین.\n\n"
        "📌 خدمات موجود:\n"
        "🚗 خودرو\n"
        "🛡 بیمه\n"
        "💰 مالیاتی\n"
        "⚖️ قضایی\n"
        "🏦 بانکی\n"
        "💵 وام\n\n"
        "🕐 ساعات فعالیت:\n"
        f"{OPEN_HOUR:02d}:00 تا {CLOSE_HOUR:02d}:00\n\n"
        "📢 کانال:\n"
        f"{CHANNEL_LINK}\n\n"
        "🤖 ربات:\n"
        f"{BOT_LINK}"
    )


# =========================================================
# ONLINE REGISTRATIONS TEXT
# =========================================================

def online_registrations_text(registrations):

    if not registrations:

        return (
            "📝 ثبت‌نام‌های آنلاین\n\n"
            "در حال حاضر ثبت‌نام فعالی وجود ندارد.\n\n"
            "📌 ثبت‌نام‌های جدید در این بخش قرار می‌گیرند."
        )

    text = (
        "📝 ثبت‌نام‌های آنلاین\n\n"
        "یکی از گزینه‌های زیر را انتخاب کنید:\n\n"
    )

    for index, registration in enumerate(registrations, start=1):
        text += f"{index}. 📝 {registration['title']}\n"

    return text# =========================================================
# REQUEST FLOW
# =========================================================

async def begin_request(
    update,
    context,
    category_key,
    service_index,
):
    """
    شروع ثبت یک درخواست جدید
    """

    category = SERVICE_CATEGORIES.get(category_key)

    if not category:
        await update.effective_message.reply_text(
            "❌ دسته‌بندی پیدا نشد.",
            reply_markup=home_keyboard(
                update.effective_user.id
            ),
        )
        return

    try:
        service_index = int(service_index)
    except (TypeError, ValueError):
        await update.effective_message.reply_text(
            "❌ خدمت انتخاب‌شده نامعتبر است.",
            reply_markup=home_keyboard(
                update.effective_user.id
            ),
        )
        return

    services = category["services"]

    if service_index < 0 or service_index >= len(services):
        await update.effective_message.reply_text(
            "❌ خدمت انتخاب‌شده وجود ندارد.",
            reply_markup=home_keyboard(
                update.effective_user.id
            ),
        )
        return

    service = services[service_index]

    # -----------------------------------------------------
    # Save temporary request information
    # -----------------------------------------------------

    context.user_data["request"] = {
        "category_key": category_key,
        "category": category["title"],
        "service": service,
    }

    context.user_data["state"] = STATE_NAME

    await update.effective_message.reply_text(
        "📝 ثبت درخواست جدید\n\n"
        f"📂 دسته‌بندی: {category['title']}\n"
        f"📌 خدمت: {service}\n\n"
        "👤 لطفاً نام و نام خانوادگی خود را وارد کنید:",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "❌ لغو",
                    callback_data="home"
                )
            ]
        ]),
    )


# =========================================================
# REQUEST FLOW - CALLBACK VERSION
# =========================================================

async def start_request_from_callback(
    query,
    context,
    category_key,
    service_index,
):
    """
    شروع ثبت درخواست از طریق CallbackQuery
    """

    category = SERVICE_CATEGORIES.get(category_key)

    if not category:
        await query.edit_message_text(
            "❌ دسته‌بندی پیدا نشد.",
            reply_markup=home_keyboard(
                query.from_user.id
            ),
        )
        return

    try:
        service_index = int(service_index)
    except (TypeError, ValueError):
        await query.edit_message_text(
            "❌ خدمت انتخاب‌شده نامعتبر است.",
            reply_markup=home_keyboard(
                query.from_user.id
            ),
        )
        return

    services = category["services"]

    if service_index < 0 or service_index >= len(services):
        await query.edit_message_text(
            "❌ خدمت انتخاب‌شده وجود ندارد.",
            reply_markup=home_keyboard(
                query.from_user.id
            ),
        )
        return

    service = services[service_index]

    context.user_data["request"] = {
        "category_key": category_key,
        "category": category["title"],
        "service": service,
    }

    context.user_data["state"] = STATE_NAME

    await query.edit_message_text(
        "📝 ثبت درخواست جدید\n\n"
        f"📂 دسته‌بندی: {category['title']}\n"
        f"📌 خدمت: {service}\n\n"
        "👤 لطفاً نام و نام خانوادگی خود را وارد کنید:",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "❌ لغو",
                    callback_data="home"
                )
            ]
        ]),
    )


# =========================================================
# REQUEST - NAME
# =========================================================

async def request_name_step(update, context, text):
    """
    دریافت نام و نام خانوادگی
    """

    text = text.strip()

    if len(text) < 3:
        await update.message.reply_text(
            "❌ نام واردشده خیلی کوتاه است.\n\n"
            "لطفاً نام و نام خانوادگی خود را کامل وارد کنید:"
        )
        return

    context.user_data["request"]["full_name"] = text

    context.user_data["state"] = STATE_PHONE

    await update.message.reply_text(
        "📱 لطفاً شماره موبایل خود را وارد کنید:\n\n"
        "مثال:\n"
        "09123456789"
    )


# =========================================================
# REQUEST - PHONE
# =========================================================

async def request_phone_step(update, context, text):
    """
    دریافت شماره موبایل
    """

    text = text.strip()

    # حذف فاصله و کاراکترهای اضافی
    phone = (
        text
        .replace(" ", "")
        .replace("-", "")
        .replace("(", "")
        .replace(")", "")
    )

    # تبدیل اعداد فارسی به انگلیسی
    persian_numbers = "۰۱۲۳۴۵۶۷۸۹"
    english_numbers = "0123456789"

    for fa, en in zip(
        persian_numbers,
        english_numbers
    ):
        phone = phone.replace(fa, en)

    # -----------------------------------------------------
    # Basic validation
    # -----------------------------------------------------

    if not phone.isdigit():
        await update.message.reply_text(
            "❌ شماره موبایل نامعتبر است.\n\n"
            "لطفاً شماره را فقط به صورت عدد وارد کنید."
        )
        return

    if len(phone) != 11 or not phone.startswith("09"):
        await update.message.reply_text(
            "❌ شماره موبایل صحیح نیست.\n\n"
            "مثال صحیح:\n"
            "09123456789"
        )
        return

    context.user_data["request"]["phone"] = phone

    context.user_data["state"] = STATE_TELEGRAM

    await update.message.reply_text(
        "📲 آیدی تلگرام خود را وارد کنید.\n\n"
        "اگر آیدی ندارید یا نمی‌خواهید وارد کنید، "
        "بنویسید:\n"
        "ندارم"
    )


# =========================================================
# REQUEST - TELEGRAM ID
# =========================================================

async def request_telegram_step(update, context, text):
    """
    دریافت Telegram ID
    """

    text = text.strip()

    if text.lower() in [
        "ندارم",
        "ندارم.",
        "ندارم!",
        "none",
        "no",
    ]:
        telegram_id = ""

    else:
        telegram_id = text

        if not telegram_id.startswith("@"):
            telegram_id = "@" + telegram_id

    context.user_data["request"]["telegram_id"] = telegram_id

    context.user_data["state"] = STATE_DESCRIPTION

    await update.message.reply_text(
        "📝 اگر توضیح یا توضیحات بیشتری درباره درخواست دارید، "
        "وارد کنید.\n\n"
        "اگر توضیحی ندارید، بنویسید:\n"
        "ندارم"
    )


# =========================================================
# REQUEST - DESCRIPTION
# =========================================================

async def request_description_step(update, context, text):
    """
    دریافت توضیحات و ثبت نهایی درخواست
    """

    text = text.strip()

    if text.lower() in [
        "ندارم",
        "ندارم.",
        "ندارم!",
        "none",
        "no",
    ]:
        description = ""

    else:
        description = text

    request_data = context.user_data.get("request")

    if not request_data:
        context.user_data.clear()

        await update.message.reply_text(
            "❌ اطلاعات درخواست پیدا نشد.\n\n"
            "لطفاً دوباره از منوی اصلی شروع کنید.",
            reply_markup=home_keyboard(
                update.effective_user.id
            ),
        )
        return

    user = update.effective_user

    # -----------------------------------------------------
    # Save user
    # -----------------------------------------------------

    save_user(user)

    # -----------------------------------------------------
    # Create request
    # -----------------------------------------------------

    request = create_request(
        user_id=user.id,
        username=user.username or "",
        full_name=request_data["full_name"],
        phone=request_data["phone"],
        telegram_id=request_data["telegram_id"],
        description=description,
        category=request_data["category"],
        service=request_data["service"],
    )

    # -----------------------------------------------------
    # Clear temporary state
    # -----------------------------------------------------

    context.user_data.pop("request", None)
    context.user_data.pop("state", None)

    # -----------------------------------------------------
    # Success message
    # -----------------------------------------------------

    await update.message.reply_text(
        "✅ درخواست شما با موفقیت ثبت شد.\n\n"
        f"🎫 کد رهگیری: {request['tracking_code']}\n"
        f"📌 وضعیت: {request['status']}\n\n"
        "🧾 رسید دیجیتال درخواست شما آماده است.\n"
        "برای مشاهده رسید، دکمه زیر را بزنید.",
        reply_markup=receipt_keyboard(
            request["tracking_code"]
        ),
    )

    # -----------------------------------------------------
    # Admin notification
    # -----------------------------------------------------

    try:

        admin_text = (
            "📥 درخواست جدید\n\n"
            f"🎫 کد رهگیری: {request['tracking_code']}\n"
            f"👤 نام: {request['full_name']}\n"
            f"📱 موبایل: {request['phone']}\n"
            f"📂 دسته‌بندی: {request['category']}\n"
            f"📌 خدمت: {request['service']}\n"
            f"📲 تلگرام: "
            f"{request['telegram_id'] or 'ندارد'}\n"
            f"📝 توضیحات: "
            f"{request['description'] or 'ندارد'}\n"
            f"📊 وضعیت: {request['status']}\n"
            f"📅 ثبت: {request['created_at']}"
        )

        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=admin_text,
            reply_markup=admin_request_keyboard(
                request
            ),
        )

    except Exception as e:
        logger.error(
            f"Admin notification error: {e}"
        )


# =========================================================
# CANCEL REQUEST
# =========================================================

async def cancel_request(update, context):

    context.user_data.clear()

    if update.callback_query:

        await update.callback_query.edit_message_text(
            "❌ ثبت درخواست لغو شد.",
            reply_markup=home_keyboard(
                update.effective_user.id
            ),
        )

    elif update.message:

        await update.message.reply_text(
            "❌ ثبت درخواست لغو شد.",
            reply_markup=home_keyboard(
                update.effective_user.id
            ),
        )# =========================================================
# USER REQUESTS
# =========================================================

def my_requests_keyboard(requests):

    buttons = []

    for request in requests:

        code = request["tracking_code"]

        # متن دکمه
        button_text = (
            f"🎫 {code} | "
            f"{request['status']}"
        )

        buttons.append([
            InlineKeyboardButton(
                button_text,
                callback_data=f"my_request|{code}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            "🏠 منوی اصلی",
            callback_data="home"
        )
    ])

    return InlineKeyboardMarkup(buttons)


# =========================================================
# USER REQUESTS TEXT
# =========================================================

def my_requests_text(requests):

    if not requests:

        return (
            "📋 درخواست‌های من\n\n"
            "هنوز هیچ درخواستی ثبت نکرده‌اید.\n\n"
            "برای ثبت درخواست جدید از منوی اصلی "
            "استفاده کنید."
        )

    text = (
        "📋 درخواست‌های من\n\n"
        "درخواست‌های ثبت‌شده شما:\n\n"
    )

    for index, request in enumerate(
        requests,
        start=1
    ):

        text += (
            f"{index}. 🎫 {request['tracking_code']}\n"
            f"   📌 {request['service']}\n"
            f"   📊 {request['status']}\n"
            f"   📅 {request['created_at']}\n\n"
        )

    text += (
        "👇 برای مشاهده جزئیات، "
        "یکی از درخواست‌ها را انتخاب کنید."
    )

    return text


# =========================================================
# SINGLE REQUEST KEYBOARD
# =========================================================

def user_request_keyboard(
    tracking_code,
    back_callback="my_requests"
):

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🧾 مشاهده رسید",
                callback_data=f"receipt|{tracking_code}"
            )
        ],
        [
            InlineKeyboardButton(
                "🔙 درخواست‌های من",
                callback_data=back_callback
            )
        ],
        [
            InlineKeyboardButton(
                "🏠 منوی اصلی",
                callback_data="home"
            )
        ]
    ])


# =========================================================
# RECEIPT KEYBOARD
# =========================================================

def receipt_view_keyboard(
    tracking_code
):

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🔙 جزئیات درخواست",
                callback_data=f"my_request|{tracking_code}"
            )
        ],
        [
            InlineKeyboardButton(
                "📋 درخواست‌های من",
                callback_data="my_requests"
            )
        ],
        [
            InlineKeyboardButton(
                "🏠 منوی اصلی",
                callback_data="home"
            )
        ]
    ])


# =========================================================
# SHOW USER REQUESTS
# =========================================================

async def show_my_requests(
    query,
    user_id
):

    requests = get_user_requests(
        user_id
    )

    await query.edit_message_text(
        my_requests_text(requests),
        reply_markup=my_requests_keyboard(
            requests
        ),
    )


# =========================================================
# SHOW SINGLE REQUEST
# =========================================================

async def show_my_request(
    query,
    user_id,
    tracking_code
):

    request = get_request(
        tracking_code
    )

    # -----------------------------------------------------
    # Request not found
    # -----------------------------------------------------

    if not request:

        await query.edit_message_text(
            "❌ درخواست موردنظر پیدا نشد.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "📋 درخواست‌های من",
                        callback_data="my_requests"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🏠 منوی اصلی",
                        callback_data="home"
                    )
                ]
            ]),
        )

        return

    # -----------------------------------------------------
    # Security check
    # -----------------------------------------------------

    if (
        request["user_id"] != user_id
        and user_id != ADMIN_ID
    ):

        await query.edit_message_text(
            "❌ شما اجازه مشاهده این درخواست را ندارید.",
            reply_markup=home_keyboard(
                user_id
            ),
        )

        return

    # -----------------------------------------------------
    # Show request
    # -----------------------------------------------------

    await query.edit_message_text(
        format_request_details(
            request
        ),
        reply_markup=user_request_keyboard(
            tracking_code
        ),
    )


# =========================================================
# SHOW RECEIPT
# =========================================================

async def show_receipt(
    query,
    user_id,
    tracking_code
):

    request = get_request(
        tracking_code
    )

    # -----------------------------------------------------
    # Not found
    # -----------------------------------------------------

    if not request:

        await query.edit_message_text(
            "❌ رسید موردنظر پیدا نشد.",
            reply_markup=home_keyboard(
                user_id
            ),
        )

        return

    # -----------------------------------------------------
    # Security
    # -----------------------------------------------------

    if (
        request["user_id"] != user_id
        and user_id != ADMIN_ID
    ):

        await query.edit_message_text(
            "❌ شما اجازه مشاهده این رسید را ندارید.",
            reply_markup=home_keyboard(
                user_id
            ),
        )

        return

    # -----------------------------------------------------
    # Receipt
    # -----------------------------------------------------

    await query.edit_message_text(
        format_receipt(
            request
        ),
        reply_markup=receipt_view_keyboard(
            tracking_code
        ),
    )


# =========================================================
# TRACKING SEARCH
# =========================================================

async def ask_tracking_code(
    query,
    context
):

    context.user_data["state"] = STATE_TRACKING

    await query.edit_message_text(
        "🔎 پیگیری درخواست\n\n"
        "لطفاً کد رهگیری درخواست خود را وارد کنید.\n\n"
        "مثال:\n"
        "CF10027",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "❌ لغو",
                    callback_data="home"
                )
            ]
        ]),
    )


# =========================================================
# PROCESS TRACKING CODE
# =========================================================

async def process_tracking_code(
    update,
    context,
    tracking_code
):

    tracking_code = tracking_code.strip().upper()

    # -----------------------------------------------------
    # Basic validation
    # -----------------------------------------------------

    if not tracking_code.startswith("CF"):

        await update.message.reply_text(
            "❌ کد رهگیری نامعتبر است.\n\n"
            "کد باید مانند نمونه زیر باشد:\n"
            "CF10027"
        )

        return

    # -----------------------------------------------------
    # Find request
    # -----------------------------------------------------

    request = get_request(
        tracking_code
    )

    if not request:

        await update.message.reply_text(
            "❌ هیچ درخواستی با این کد پیدا نشد.\n\n"
            "لطفاً کد رهگیری را بررسی کنید."
        )

        return

    # -----------------------------------------------------
    # Security
    # -----------------------------------------------------

    user_id = update.effective_user.id

    if (
        request["user_id"] != user_id
        and user_id != ADMIN_ID
    ):

        await update.message.reply_text(
            "❌ این درخواست متعلق به حساب شما نیست.",
            reply_markup=home_keyboard(
                user_id
            ),
        )

        context.user_data.pop(
            "state",
            None
        )

        return

    # -----------------------------------------------------
    # Clear tracking state
    # -----------------------------------------------------

    context.user_data.pop(
        "state",
        None
    )

    # -----------------------------------------------------
    # Show details
    # -----------------------------------------------------

    await send_request_details(
        update.effective_chat.id,
        request,
        context,
    )


# =========================================================
# CALLBACK - USER REQUESTS
# =========================================================

async def handle_user_request_callbacks(
    query,
    context,
    data
):

    user_id = query.from_user.id

    # -----------------------------------------------------
    # My requests
    # -----------------------------------------------------

    if data == "my_requests":

        await show_my_requests(
            query,
            user_id
        )

        return True

    # -----------------------------------------------------
    # Single request
    # -----------------------------------------------------

    if data.startswith(
        "my_request|"
    ):

        tracking_code = data.split(
            "|",
            1
        )[1]

        await show_my_request(
            query,
            user_id,
            tracking_code
        )

        return True

    # -----------------------------------------------------
    # Receipt
    # -----------------------------------------------------

    if data.startswith(
        "receipt|"
    ):

        tracking_code = data.split(
            "|",
            1
        )[1]

        await show_receipt(
            query,
            user_id,
            tracking_code
        )

        return True

    return False# =========================================================
# ADMIN PANEL
# =========================================================

async def show_admin_panel(query):

    if query.from_user.id != ADMIN_ID:
        await query.edit_message_text(
            "❌ شما دسترسی به پنل مدیریت ندارید.",
            reply_markup=home_keyboard(
                query.from_user.id
            ),
        )
        return

    await query.edit_message_text(
        "🛠 پنل مدیریت CafiNetOnline24\n\n"
        "از منوی زیر بخش موردنظر را انتخاب کنید:",
        reply_markup=admin_keyboard(),
    )


# =========================================================
# ADMIN - NEW REQUESTS
# =========================================================

async def show_admin_requests(query):

    if query.from_user.id != ADMIN_ID:
        return

    requests = get_pending_requests()

    if not requests:

        await query.edit_message_text(
            "📥 درخواست‌های جدید\n\n"
            "✅ در حال حاضر درخواست جدیدی وجود ندارد.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔙 پنل مدیریت",
                        callback_data="admin_panel"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🏠 منوی اصلی",
                        callback_data="home"
                    )
                ]
            ]),
        )

        return

    text = (
        "📥 درخواست‌های جدید\n\n"
        f"تعداد: {len(requests)}\n\n"
        "یکی از درخواست‌ها را انتخاب کنید:"
    )

    buttons = []

    for request in requests:

        buttons.append([
            InlineKeyboardButton(
                f"🎫 {request['tracking_code']} | "
                f"{request['full_name'][:18]}",
                callback_data=(
                    f"admin_view|"
                    f"{request['tracking_code']}"
                )
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            "🔙 پنل مدیریت",
            callback_data="admin_panel"
        )
    ])

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            buttons
        ),
    )


# =========================================================
# ADMIN - VIEW REQUEST
# =========================================================

async def show_admin_request(
    query,
    tracking_code
):

    if query.from_user.id != ADMIN_ID:
        return

    request = get_request(
        tracking_code
    )

    if not request:

        await query.edit_message_text(
            "❌ درخواست پیدا نشد.",
            reply_markup=admin_keyboard(),
        )

        return

    text = (
        "👁 جزئیات درخواست\n\n"
        f"🎫 کد رهگیری: {request['tracking_code']}\n"
        f"👤 نام: {request['full_name']}\n"
        f"📱 موبایل: {request['phone']}\n"
        f"📲 تلگرام: "
        f"{request['telegram_id'] or 'ندارد'}\n"
        f"📂 دسته‌بندی: {request['category']}\n"
        f"📌 خدمت: {request['service']}\n"
        f"📝 توضیحات: "
        f"{request['description'] or 'ندارد'}\n"
        f"📊 وضعیت: {request['status']}\n"
        f"📅 ثبت: {request['created_at']}\n"
        f"🔄 بروزرسانی: {request['updated_at']}"
    )

    await query.edit_message_text(
        text,
        reply_markup=status_keyboard(
            tracking_code
        ),
    )


# =========================================================
# ADMIN - CHANGE STATUS
# =========================================================

async def change_request_status(
    query,
    context,
    status_key,
    tracking_code
):

    if query.from_user.id != ADMIN_ID:
        return

    status = STATUS_MAP.get(
        status_key
    )

    if not status:

        await query.edit_message_text(
            "❌ وضعیت نامعتبر است.",
            reply_markup=admin_keyboard(),
        )

        return

    request = get_request(
        tracking_code
    )

    if not request:

        await query.edit_message_text(
            "❌ درخواست پیدا نشد.",
            reply_markup=admin_keyboard(),
        )

        return

    # -----------------------------------------------------
    # Update database
    # -----------------------------------------------------

    update_status(
        tracking_code,
        status
    )

    # -----------------------------------------------------
    # Get updated request
    # -----------------------------------------------------

    updated_request = get_request(
        tracking_code
    )

    # -----------------------------------------------------
    # Show updated request to admin
    # -----------------------------------------------------

    await query.edit_message_text(
        "✅ وضعیت درخواست بروزرسانی شد.\n\n"
        f"🎫 کد رهگیری: {tracking_code}\n"
        f"📊 وضعیت جدید: {status}",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "👁 مشاهده درخواست",
                    callback_data=(
                        f"admin_view|{tracking_code}"
                    )
                )
            ],
            [
                InlineKeyboardButton(
                    "🧾 مشاهده رسید",
                    callback_data=(
                        f"receipt|{tracking_code}"
                    )
                )
            ],
            [
                InlineKeyboardButton(
                    "📥 درخواست‌های جدید",
                    callback_data="admin_requests"
                )
            ],
            [
                InlineKeyboardButton(
                    "🛠 پنل مدیریت",
                    callback_data="admin_panel"
                )
            ]
        ]),
    )

    # -----------------------------------------------------
    # Notify user
    # -----------------------------------------------------

    try:

        await context.bot.send_message(
            chat_id=updated_request["user_id"],
            text=(
                "🔔 بروزرسانی درخواست\n\n"
                f"🎫 کد رهگیری: {tracking_code}\n"
                f"📊 وضعیت جدید: {status}\n\n"
                "🧾 رسید دیجیتال شما نیز "
                "به‌صورت خودکار بروزرسانی شده است."
            ),
            reply_markup=receipt_keyboard(
                tracking_code
            ),
        )

    except Exception as e:

        logger.error(
            f"User status notification error: {e}"
        )


# =========================================================
# ADMIN - SEARCH
# =========================================================

def search_request(
    tracking_code
):

    return get_request(
        tracking_code.strip().upper()
    )


# =========================================================
# ADMIN - SEARCH RESULT
# =========================================================

async def show_admin_search_result(
    update,
    context,
    tracking_code
):

    if update.effective_user.id != ADMIN_ID:
        return

    request = search_request(
        tracking_code
    )

    context.user_data.pop(
        "state",
        None
    )

    if not request:

        await update.message.reply_text(
            "❌ درخواست پیدا نشد.",
            reply_markup=admin_keyboard(),
        )

        return

    await update.message.reply_text(
        (
            "🔎 نتیجه جستجو\n\n"
            f"🎫 کد رهگیری: {request['tracking_code']}\n"
            f"👤 نام: {request['full_name']}\n"
            f"📱 موبایل: {request['phone']}\n"
            f"📂 دسته‌بندی: {request['category']}\n"
            f"📌 خدمت: {request['service']}\n"
            f"📊 وضعیت: {request['status']}\n"
            f"📅 ثبت: {request['created_at']}"
        ),
        reply_markup=status_keyboard(
            request["tracking_code"]
        ),
    )


# =========================================================
# ADMIN - REGISTRATIONS
# =========================================================

async def show_admin_registrations(
    query
):

    if query.from_user.id != ADMIN_ID:
        return

    registrations = get_all_registrations()

    if not registrations:

        await query.edit_message_text(
            "📋 لیست ثبت‌نام‌ها\n\n"
            "هیچ ثبت‌نامی ثبت نشده است.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔙 پنل مدیریت",
                        callback_data="admin_panel"
                    )
                ]
            ]),
        )

        return

    text = "📋 لیست ثبت‌نام‌ها\n\n"

    buttons = []

    for registration in registrations:

        active_text = (
            "🟢 فعال"
            if registration["active"]
            else "🔴 غیرفعال"
        )

        text += (
            f"#{registration['id']} "
            f"📝 {registration['title']}\n"
            f"وضعیت: {active_text}\n"
            f"تاریخ: {registration['registration_date']}\n\n"
        )

        if registration["active"]:

            buttons.append([
                InlineKeyboardButton(
                    f"🗑 حذف #{registration['id']}",
                    callback_data=(
                        f"admin_delete_reg|"
                        f"{registration['id']}"
                    )
                )
            ])

    buttons.append([
        InlineKeyboardButton(
            "🔙 پنل مدیریت",
            callback_data="admin_panel"
        )
    ])

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            buttons
        ),
    )


# =========================================================
# ADMIN - DELETE REGISTRATION
# =========================================================

async def delete_admin_registration(
    query,
    registration_id
):

    if query.from_user.id != ADMIN_ID:
        return

    try:
        registration_id = int(
            registration_id
        )
    except ValueError:

        await query.answer(
            "شناسه نامعتبر است."
        )

        return

    registration = get_registration(
        registration_id
    )

    if not registration:

        await query.edit_message_text(
            "❌ ثبت‌نام پیدا نشد.",
            reply_markup=admin_keyboard(),
        )

        return

    deactivate_registration(
        registration_id
    )

    await query.edit_message_text(
        "✅ ثبت‌نام غیرفعال شد.\n\n"
        f"📝 {registration['title']}",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "📋 لیست ثبت‌نام‌ها",
                    callback_data="admin_registrations"
                )
            ],
            [
                InlineKeyboardButton(
                    "🛠 پنل مدیریت",
                    callback_data="admin_panel"
                )
            ]
        ]),
    )


# =========================================================
# ADMIN - STATS
# =========================================================

async def show_admin_stats(query):

    if query.from_user.id != ADMIN_ID:
        return

    stats = get_stats()

    text = (
        "📊 آمار CafiNetOnline24\n\n"
        f"👥 کاربران: {stats['users']}\n\n"
        f"📋 کل درخواست‌ها: {stats['total']}\n"
        f"🟡 در انتظار بررسی: {stats['pending']}\n"
        f"🔵 در حال انجام: {stats['doing']}\n"
        f"🟢 انجام شده: {stats['done']}\n"
        f"🔴 رد شده: {stats['rejected']}"
    )

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔄 بروزرسانی",
                    callback_data="admin_stats"
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 پنل مدیریت",
                    callback_data="admin_panel"
                )
            ]
        ]),
    )


# =========================================================
# ADMIN - SETTINGS
# =========================================================

async def show_admin_settings(query):

    if query.from_user.id != ADMIN_ID:
        return

    await query.edit_message_text(
        "⚙️ تنظیمات ربات\n\n"
        f"🕐 ساعت فعالیت: "
        f"{OPEN_HOUR:02d}:00 تا {CLOSE_HOUR:02d}:00\n\n"
        "💰 پرداخت: بدون هزینه\n"
        "🧾 رسید دیجیتال: فعال\n"
        "🔎 پیگیری درخواست: فعال\n"
        "📋 درخواست‌های من: فعال",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔙 پنل مدیریت",
                    callback_data="admin_panel"
                )
            ]
        ]),
    )# =========================================================
# ONLINE REGISTRATIONS
# =========================================================

async def show_online_registrations(query):

    registrations = get_active_registrations()

    text = online_registrations_text(
        registrations
    )

    await query.edit_message_text(
        text,
        reply_markup=registration_keyboard(
            registrations
        ),
    )


# =========================================================
# SHOW SINGLE REGISTRATION
# =========================================================

async def show_registration(
    query,
    registration_id
):

    try:
        registration_id = int(
            registration_id
        )
    except ValueError:

        await query.edit_message_text(
            "❌ ثبت‌نام نامعتبر است.",
            reply_markup=home_keyboard(
                query.from_user.id
            ),
        )

        return

    registration = get_registration(
        registration_id
    )

    if not registration:
        await query.edit_message_text(
            "❌ این ثبت‌نام دیگر وجود ندارد.",
            reply_markup=home_keyboard(
                query.from_user.id
            ),
        )
        return

    if not registration["active"]:
        await query.edit_message_text(
            "❌ این ثبت‌نام در حال حاضر غیرفعال است.",
            reply_markup=home_keyboard(
                query.from_user.id
            ),
        )
        return

    await query.edit_message_text(
        "📝 ثبت‌نام آنلاین\n\n"
        f"📌 عنوان:\n"
        f"{registration['title']}\n\n"
        f"📅 تاریخ ثبت در سامانه:\n"
        f"{registration['registration_date']}\n\n"
        "برای هماهنگی و ثبت درخواست، "
        "از دکمه زیر استفاده کنید.",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "📝 ثبت درخواست",
                    callback_data=(
                        f"reg_start|"
                        f"{registration_id}"
                    )
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 ثبت‌نام‌های آنلاین",
                    callback_data="online_registrations"
                )
            ],
            [
                InlineKeyboardButton(
                    "🏠 منوی اصلی",
                    callback_data="home"
                )
            ]
        ]),
    )


# =========================================================
# START REGISTRATION REQUEST
# =========================================================

async def start_registration_request(
    query,
    context,
    registration_id
):

    registration = get_registration(
        registration_id
    )

    if not registration:
        await query.edit_message_text(
            "❌ ثبت‌نام پیدا نشد.",
            reply_markup=home_keyboard(
                query.from_user.id
            ),
        )
        return

    if not registration["active"]:
        await query.edit_message_text(
            "❌ این ثبت‌نام در حال حاضر فعال نیست.",
            reply_markup=home_keyboard(
                query.from_user.id
            ),
        )
        return

    context.user_data["online_registration"] = {
        "id": registration["id"],
        "title": registration["title"],
    }

    context.user_data["state"] = STATE_NAME

    await query.edit_message_text(
        "📝 ثبت درخواست ثبت‌نام آنلاین\n\n"
        f"📌 مورد انتخابی:\n"
        f"{registration['title']}\n\n"
        "👤 لطفاً نام و نام خانوادگی خود را وارد کنید:",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "❌ لغو",
                    callback_data="home"
                )
            ]
        ]),
    )


# =========================================================
# SUPPORT
# =========================================================

def save_support_message(
    user_id,
    message
):

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO support_messages (
            user_id,
            message,
            created_at,
            replied
        )
        VALUES (?, ?, ?, ?)
    """, (
        user_id,
        message,
        now_text(),
        0,
    ))

    conn.commit()
    conn.close()


# =========================================================
# SHOW SUPPORT
# =========================================================

async def show_support(query):

    await query.edit_message_text(
        "💬 پشتیبانی CafiNetOnline24\n\n"
        "اگر در مورد ثبت درخواست، پیگیری یا "
        "خدمات ربات مشکلی دارید، می‌توانید "
        "پیام خود را برای پشتیبانی ارسال کنید.\n\n"
        "📌 پیام شما برای مدیریت ارسال می‌شود.",
        reply_markup=support_keyboard(),
    )


# =========================================================
# START SUPPORT
# =========================================================

async def start_support(
    query,
    context
):

    context.user_data["state"] = STATE_SUPPORT

    await query.edit_message_text(
        "💬 ارسال پیام به پشتیبانی\n\n"
        "لطفاً پیام خود را در یک پیام ارسال کنید.\n\n"
        "مثال:\n"
        "«برای پیگیری درخواست خودم مشکل دارم.»",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "❌ لغو",
                    callback_data="home"
                )
            ]
        ]),
    )


# =========================================================
# PROCESS SUPPORT MESSAGE
# =========================================================

async def process_support_message(
    update,
    context,
    message
):

    user = update.effective_user

    save_user(user)

    save_support_message(
        user.id,
        message
    )

    context.user_data.pop(
        "state",
        None
    )

    # -----------------------------------------------------
    # User confirmation
    # -----------------------------------------------------

    await update.message.reply_text(
        "✅ پیام شما با موفقیت برای پشتیبانی ارسال شد.\n\n"
        "📨 مدیریت پیام شما را بررسی خواهد کرد.",
        reply_markup=home_keyboard(
            user.id
        ),
    )

    # -----------------------------------------------------
    # Admin notification
    # -----------------------------------------------------

    try:

        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                "💬 پیام جدید پشتیبانی\n\n"
                f"👤 کاربر: {user.full_name}\n"
                f"🆔 شناسه: {user.id}\n"
                f"📲 یوزرنیم: "
                f"@{user.username}"
                if user.username
                else "📲 یوزرنیم: ندارد"
            ),
        )

        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                "📝 متن پیام:\n\n"
                f"{message}"
            ),
        )

    except Exception as e:

        logger.error(
            f"Support admin notification error: {e}"
        )


# =========================================================
# ADMIN - ADD REGISTRATION
# =========================================================

async def start_admin_add_registration(
    query,
    context
):

    if query.from_user.id != ADMIN_ID:
        return

    context.user_data["state"] = (
        STATE_ADMIN_ADD_REG
    )

    await query.edit_message_text(
        "➕ افزودن ثبت‌نام آنلاین\n\n"
        "عنوان ثبت‌نام را ارسال کنید.\n\n"
        "مثال:\n"
        "ثبت‌نام فروش خودرو",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "❌ لغو",
                    callback_data="admin_panel"
                )
            ]
        ]),
    )


# =========================================================
# ADMIN - SAVE REGISTRATION
# =========================================================

async def process_admin_add_registration(
    update,
    context,
    title
):

    if update.effective_user.id != ADMIN_ID:
        return

    title = title.strip()

    if len(title) < 3:

        await update.message.reply_text(
            "❌ عنوان خیلی کوتاه است.\n\n"
            "لطفاً عنوان کامل‌تری وارد کنید."
        )

        return

    add_registration(
        title
    )

    context.user_data.pop(
        "state",
        None
    )

    await update.message.reply_text(
        "✅ ثبت‌نام با موفقیت اضافه شد.\n\n"
        f"📝 عنوان:\n{title}",
        reply_markup=admin_keyboard(),
    )


# =========================================================
# ADMIN - BROADCAST
# =========================================================

async def start_broadcast(
    query,
    context
):

    if query.from_user.id != ADMIN_ID:
        return

    context.user_data["state"] = (
        STATE_BROADCAST
    )

    await query.edit_message_text(
        "📢 ارسال پیام همگانی\n\n"
        "متن پیام موردنظر را ارسال کنید.\n\n"
        "⚠️ پیام برای کاربران ثبت‌شده در ربات "
        "ارسال خواهد شد.",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "❌ لغو",
                    callback_data="admin_panel"
                )
            ]
        ]),
    )


# =========================================================
# GET ALL USERS
# =========================================================

def get_all_users():

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT user_id
        FROM users
        ORDER BY user_id
    """)

    users = cursor.fetchall()

    conn.close()

    return users


# =========================================================
# PROCESS BROADCAST
# =========================================================

async def process_broadcast(
    update,
    context,
    message
):

    if update.effective_user.id != ADMIN_ID:
        return

    context.user_data.pop(
        "state",
        None
    )

    users = get_all_users()

    sent = 0
    failed = 0

    for user in users:

        try:

            await context.bot.send_message(
                chat_id=user["user_id"],
                text=(
                    "📢 اطلاعیه CafiNetOnline24\n\n"
                    f"{message}"
                ),
            )

            sent += 1

        except Exception as e:

            failed += 1

            logger.warning(
                f"Broadcast failed for "
                f"{user['user_id']}: {e}"
            )

    await update.message.reply_text(
        "✅ ارسال همگانی به پایان رسید.\n\n"
        f"📨 ارسال موفق: {sent}\n"
        f"❌ ناموفق: {failed}",
        reply_markup=admin_keyboard(),
    )


# =========================================================
# ADMIN - SEARCH START
# =========================================================

async def start_admin_search(
    query,
    context
):

    if query.from_user.id != ADMIN_ID:
        return

    context.user_data["state"] = (
        STATE_ADMIN_SEARCH
    )

    await query.edit_message_text(
        "🔎 جستجوی درخواست\n\n"
        "کد رهگیری را وارد کنید.\n\n"
        "مثال:\n"
        "CF10027",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "❌ لغو",
                    callback_data="admin_panel"
                )
            ]
        ]),
    )


# =========================================================
# ONLINE REGISTRATION REQUEST
# =========================================================

async def finish_online_registration_request(
    update,
    context,
    text
):

    registration = context.user_data.get(
        "online_registration"
    )

    if not registration:
        return False

    user = update.effective_user

    # -----------------------------------------------------
    # This flow uses the same request system
    # -----------------------------------------------------

    if context.user_data.get("state") == STATE_NAME:

        name = text.strip()

        if len(name) < 3:

            await update.message.reply_text(
                "❌ نام واردشده صحیح نیست.\n\n"
                "لطفاً نام و نام خانوادگی را وارد کنید."
            )

            return True

        context.user_data[
            "online_full_name"
        ] = name

        context.user_data["state"] = (
            STATE_PHONE
        )

        await update.message.reply_text(
            "📱 لطفاً شماره موبایل خود را وارد کنید:"
        )

        return True

    if context.user_data.get("state") == STATE_PHONE:

        phone = (
            text.strip()
            .replace(" ", "")
            .replace("-", "")
        )

        persian_numbers = "۰۱۲۳۴۵۶۷۸۹"
        english_numbers = "0123456789"

        for fa, en in zip(
            persian_numbers,
            english_numbers
        ):
            phone = phone.replace(
                fa,
                en
            )

        if (
            not phone.isdigit()
            or len(phone) != 11
            or not phone.startswith("09")
        ):

            await update.message.reply_text(
                "❌ شماره موبایل صحیح نیست.\n\n"
                "مثال:\n"
                "09123456789"
            )

            return True

        context.user_data[
            "online_phone"
        ] = phone

        context.user_data["state"] = (
            STATE_TELEGRAM
        )

        await update.message.reply_text(
            "📲 آیدی تلگرام خود را وارد کنید.\n\n"
            "اگر ندارید بنویسید:\n"
            "ندارم"
        )

        return True

    if context.user_data.get("state") == STATE_TELEGRAM:

        telegram_id = text.strip()

        if telegram_id.lower() == "ندارم":
            telegram_id = ""

        elif not telegram_id.startswith("@"):
            telegram_id = "@" + telegram_id

        context.user_data[
            "online_telegram"
        ] = telegram_id

        context.user_data["state"] = (
            STATE_DESCRIPTION
        )

        await update.message.reply_text(
            "📝 توضیحات درخواست را وارد کنید.\n\n"
            "اگر توضیحی ندارید، بنویسید:\n"
            "ندارم"
        )

        return True

    if context.user_data.get("state") == STATE_DESCRIPTION:

        description = text.strip()

        if description.lower() == "ندارم":
            description = ""

        request = create_request(
            user_id=user.id,
            username=user.username or "",
            full_name=context.user_data[
                "online_full_name"
            ],
            phone=context.user_data[
                "online_phone"
            ],
            telegram_id=context.user_data[
                "online_telegram"
            ],
            description=description,
            category="📝 ثبت‌نام‌های آنلاین",
            service=registration["title"],
        )

        save_user(user)

        context.user_data.clear()

        await update.message.reply_text(
            "✅ درخواست ثبت‌نام آنلاین شما ثبت شد.\n\n"
            f"🎫 کد رهگیری: "
            f"{request['tracking_code']}\n"
            f"📌 وضعیت: {request['status']}\n\n"
            "🧾 رسید دیجیتال درخواست شما آماده است.",
            reply_markup=receipt_keyboard(
                request["tracking_code"]
            ),
        )

        # -------------------------------------------------
        # Admin notification
        # -------------------------------------------------

        try:

            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    "📥 ثبت‌نام آنلاین جدید\n\n"
                    f"🎫 کد رهگیری: "
                    f"{request['tracking_code']}\n"
                    f"👤 نام: "
                    f"{request['full_name']}\n"
                    f"📱 موبایل: "
                    f"{request['phone']}\n"
                    f"📝 ثبت‌نام: "
                    f"{request['service']}\n"
                    f"📊 وضعیت: "
                    f"{request['status']}"
                ),
                reply_markup=admin_request_keyboard(
                    request
                ),
            )

        except Exception as e:

            logger.error(
                f"Online registration "
                f"admin notification error: {e}"
            )

        return True

    return False# =========================================================
# CALLBACK HANDLER
# =========================================================

async def callback_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    if not query:
        return

    data = query.data
    user_id = query.from_user.id

    # -----------------------------------------------------
    # Save user
    # -----------------------------------------------------

    save_user(
        query.from_user
    )

    # -----------------------------------------------------
    # Answer callback
    # -----------------------------------------------------

    try:
        await query.answer()
    except Exception:
        pass

    # =====================================================
    # HOME
    # =====================================================

    if data == "home":

        context.user_data.clear()

        await query.edit_message_text(
            "🏠 منوی اصلی CafiNetOnline24\n\n"
            "یکی از خدمات زیر را انتخاب کنید:",
            reply_markup=home_keyboard(
                user_id
            ),
        )

        return

    # =====================================================
    # ABOUT
    # =====================================================

    if data == "about":

        await query.edit_message_text(
            about_text(),
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔙 بازگشت",
                        callback_data="home"
                    )
                ]
            ]),
        )

        return

    # =====================================================
    # CATEGORY
    # =====================================================

    if data.startswith("category|"):

        category_key = data.split(
            "|",
            1
        )[1]

        category = SERVICE_CATEGORIES.get(
            category_key
        )

        if not category:

            await query.edit_message_text(
                "❌ دسته‌بندی پیدا نشد.",
                reply_markup=home_keyboard(
                    user_id
                ),
            )

            return

        await query.edit_message_text(
            f"{category['title']}\n\n"
            "📌 خدمت موردنظر را انتخاب کنید:",
            reply_markup=category_keyboard(
                category_key
            ),
        )

        return

    # =====================================================
    # SERVICE
    # =====================================================

    if data.startswith("service|"):

        parts = data.split("|")

        if len(parts) != 3:

            await query.edit_message_text(
                "❌ اطلاعات خدمت نامعتبر است.",
                reply_markup=home_keyboard(
                    user_id
                ),
            )

            return

        category_key = parts[1]
        service_index = parts[2]

        category = SERVICE_CATEGORIES.get(
            category_key
        )

        if not category:

            await query.edit_message_text(
                "❌ دسته‌بندی پیدا نشد.",
                reply_markup=home_keyboard(
                    user_id
                ),
            )

            return

        try:
            service_index_int = int(
                service_index
            )

            service = category["services"][
                service_index_int
            ]

        except (
            ValueError,
            IndexError
        ):

            await query.edit_message_text(
                "❌ خدمت پیدا نشد.",
                reply_markup=home_keyboard(
                    user_id
                ),
            )

            return

        await query.edit_message_text(
            "📌 خدمت انتخاب‌شده\n\n"
            f"📂 {category['title']}\n"
            f"📌 {service}\n\n"
            "آیا می‌خواهید برای این خدمت "
            "درخواست ثبت کنید؟",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "✅ ثبت درخواست",
                        callback_data=(
                            f"service_start|"
                            f"{category_key}|"
                            f"{service_index}"
                        )
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🔙 بازگشت",
                        callback_data=(
                            f"category|{category_key}"
                        )
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🏠 منوی اصلی",
                        callback_data="home"
                    )
                ]
            ]),
        )

        return

    # =====================================================
    # START SERVICE REQUEST
    # =====================================================

    if data.startswith("service_start|"):

        parts = data.split("|")

        if len(parts) != 3:

            await query.edit_message_text(
                "❌ اطلاعات درخواست نامعتبر است.",
                reply_markup=home_keyboard(
                    user_id
                ),
            )

            return

        category_key = parts[1]
        service_index = parts[2]

        await start_request_from_callback(
            query,
            context,
            category_key,
            service_index,
        )

        return

    # =====================================================
    # ONLINE REGISTRATIONS
    # =====================================================

    if data == "online_registrations":

        await show_online_registrations(
            query
        )

        return

    # =====================================================
    # SINGLE REGISTRATION
    # =====================================================

    if data.startswith("reg|"):

        registration_id = data.split(
            "|",
            1
        )[1]

        await show_registration(
            query,
            registration_id
        )

        return

    # =====================================================
    # START ONLINE REGISTRATION
    # =====================================================

    if data.startswith("reg_start|"):

        registration_id = data.split(
            "|",
            1
        )[1]

        await start_registration_request(
            query,
            context,
            registration_id
        )

        return

    # =====================================================
    # TRACKING
    # =====================================================

    if data == "tracking":

        await ask_tracking_code(
            query,
            context
        )

        return

    # =====================================================
    # MY REQUESTS
    # =====================================================

    if data == "my_requests":

        await show_my_requests(
            query,
            user_id
        )

        return

    # =====================================================
    # SINGLE USER REQUEST
    # =====================================================

    if data.startswith("my_request|"):

        tracking_code = data.split(
            "|",
            1
        )[1]

        await show_my_request(
            query,
            user_id,
            tracking_code
        )

        return

    # =====================================================
    # 🧾 RECEIPT
    # =====================================================

    if data.startswith("receipt|"):

        tracking_code = data.split(
            "|",
            1
        )[1]

        await show_receipt(
            query,
            user_id,
            tracking_code
        )

        return

    # =====================================================
    # SUPPORT
    # =====================================================

    if data == "support":

        await show_support(
            query
        )

        return

    # =====================================================
    # SUPPORT SEND
    # =====================================================

    if data == "support_send":

        await start_support(
            query,
            context
        )

        return

    # =====================================================
    # ADMIN PANEL
    # =====================================================

    if data == "admin_panel":

        if user_id != ADMIN_ID:

            await query.edit_message_text(
                "❌ دسترسی غیرمجاز.",
                reply_markup=home_keyboard(
                    user_id
                ),
            )

            return

        await show_admin_panel(
            query
        )

        return

    # =====================================================
    # ADMIN REQUESTS
    # =====================================================

    if data == "admin_requests":

        if user_id != ADMIN_ID:
            return

        await show_admin_requests(
            query
        )

        return

    # =====================================================
    # ADMIN VIEW REQUEST
    # =====================================================

    if data.startswith("admin_view|"):

        if user_id != ADMIN_ID:
            return

        tracking_code = data.split(
            "|",
            1
        )[1]

        await show_admin_request(
            query,
            tracking_code
        )

        return

    # =====================================================
    # ADMIN STATUS
    # =====================================================

    if data.startswith("status|"):

        if user_id != ADMIN_ID:
            return

        parts = data.split("|")

        if len(parts) != 3:
            return

        status_key = parts[1]
        tracking_code = parts[2]

        await change_request_status(
            query,
            context,
            status_key,
            tracking_code
        )

        return

    # =====================================================
    # ADMIN SEARCH
    # =====================================================

    if data == "admin_search":

        if user_id != ADMIN_ID:
            return

        await start_admin_search(
            query,
            context
        )

        return

    # =====================================================
    # ADMIN ADD REGISTRATION
    # =====================================================

    if data == "admin_add_registration":

        if user_id != ADMIN_ID:
            return

        await start_admin_add_registration(
            query,
            context
        )

        return

    # =====================================================
    # ADMIN REGISTRATIONS
    # =====================================================

    if data == "admin_registrations":

        if user_id != ADMIN_ID:
            return

        await show_admin_registrations(
            query
        )

        return

    # =====================================================
    # ADMIN DELETE REGISTRATION
    # =====================================================

    if data.startswith(
        "admin_delete_reg|"
    ):

        if user_id != ADMIN_ID:
            return

        registration_id = data.split(
            "|",
            1
        )[1]

        await delete_admin_registration(
            query,
            registration_id
        )

        return

    # =====================================================
    # ADMIN STATS
    # =====================================================

    if data == "admin_stats":

        if user_id != ADMIN_ID:
            return

        await show_admin_stats(
            query
        )

        return

    # =====================================================
    # ADMIN BROADCAST
    # =====================================================

    if data == "admin_broadcast":

        if user_id != ADMIN_ID:
            return

        await start_broadcast(
            query,
            context
        )

        return

    # =====================================================
    # ADMIN SETTINGS
    # =====================================================

    if data == "admin_settings":

        if user_id != ADMIN_ID:
            return

        await show_admin_settings(
            query
        )

        return

    # =====================================================
    # UNKNOWN CALLBACK
    # =====================================================

    await query.edit_message_text(
        "❌ این گزینه دیگر معتبر نیست.",
        reply_markup=home_keyboard(
            user_id
        ),
    )


# =========================================================
# TEXT MESSAGE HANDLER
# =========================================================

async def text_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:
        return

    user = update.effective_user
    text = update.message.text.strip()

    # -----------------------------------------------------
    # Save user
    # -----------------------------------------------------

    save_user(user)

    # =====================================================
    # CANCEL
    # =====================================================

    if text in [
        "لغو",
        "/cancel",
        "❌ لغو",
    ]:

        context.user_data.clear()

        await update.message.reply_text(
            "❌ عملیات لغو شد.",
            reply_markup=home_keyboard(
                user.id
            ),
        )

        return

    # =====================================================
    # ADMIN SEARCH
    # =====================================================

    if (
        user.id == ADMIN_ID
        and context.user_data.get("state")
        == STATE_ADMIN_SEARCH
    ):

        await show_admin_search_result(
            update,
            context,
            text
        )

        return

    # =====================================================
    # ADMIN ADD REGISTRATION
    # =====================================================

    if (
        user.id == ADMIN_ID
        and context.user_data.get("state")
        == STATE_ADMIN_ADD_REG
    ):

        await process_admin_add_registration(
            update,
            context,
            text
        )

        return

    # =====================================================
    # ADMIN BROADCAST
    # =====================================================

    if (
        user.id == ADMIN_ID
        and context.user_data.get("state")
        == STATE_BROADCAST
    ):

        await process_broadcast(
            update,
            context,
            text
        )

        return

    # =====================================================
    # SUPPORT
    # =====================================================

    if (
        context.user_data.get("state")
        == STATE_SUPPORT
    ):

        await process_support_message(
            update,
            context,
            text
        )

        return

    # =====================================================
    # TRACKING
    # =====================================================

    if (
        context.user_data.get("state")
        == STATE_TRACKING
    ):

        await process_tracking_code(
            update,
            context,
            text
        )

        return

    # =====================================================
    # ONLINE REGISTRATION FLOW
    # =====================================================

    if context.user_data.get(
        "online_registration"
    ):

        handled = await finish_online_registration_request(
            update,
            context,
            text
        )

        if handled:
            return

    # =====================================================
    # NORMAL REQUEST FLOW
    # =====================================================

    request_data = context.user_data.get(
        "request"
    )

    if request_data:

        state = context.user_data.get(
            "state"
        )

        # -------------------------------------------------
        # NAME
        # -------------------------------------------------

        if state == STATE_NAME:

            await request_name_step(
                update,
                context,
                text
            )

            return

        # -------------------------------------------------
        # PHONE
        # -------------------------------------------------

        if state == STATE_PHONE:

            await request_phone_step(
                update,
                context,
                text
            )

            return

        # -------------------------------------------------
        # TELEGRAM
        # -------------------------------------------------

        if state == STATE_TELEGRAM:

            await request_telegram_step(
                update,
                context,
                text
            )

            return

        # -------------------------------------------------
        # DESCRIPTION
        # -------------------------------------------------

        if state == STATE_DESCRIPTION:

            await request_description_step(
                update,
                context,
                text
            )

            return

    # =====================================================
    # DEFAULT
    # =====================================================

    await update.message.reply_text(
        "ℹ️ از منوی اصلی یک گزینه را انتخاب کنید.",
        reply_markup=home_keyboard(
            user.id
        ),
    )


# =========================================================
# /START
# =========================================================

async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    save_user(user)

    context.user_data.clear()

    # -----------------------------------------------------
    # Working hours
    # -----------------------------------------------------

    if not is_open() and user.id != ADMIN_ID:

        await update.message.reply_text(
            closed_message()
        )

        return

    # -----------------------------------------------------
    # Welcome
    # -----------------------------------------------------

    await update.message.reply_text(
        "🟢 به CafiNetOnline24 خوش آمدید!\n\n"
        "💻 کافی‌نت آنلاین ۲۴\n\n"
        "از طریق این ربات می‌توانید درخواست‌های "
        "خدمات آنلاین خود را ثبت و پیگیری کنید.\n\n"
        "🧾 هر درخواست دارای کد رهگیری و "
        "رسید دیجیتال اختصاصی است.\n\n"
        "👇 یکی از گزینه‌ها را انتخاب کنید:",
        reply_markup=home_keyboard(
            user.id
        ),
    )


# =========================================================
# /ADMIN
# =========================================================

async def admin_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if update.effective_user.id != ADMIN_ID:

        await update.message.reply_text(
            "❌ شما دسترسی مدیر ندارید."
        )

        return

    context.user_data.clear()

    await update.message.reply_text(
        "🛠 پنل مدیریت CafiNetOnline24",
        reply_markup=admin_keyboard(),
    )


# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(
    update,
    context
):

    logger.error(
        "Exception while handling update:",
        exc_info=context.error
    )

    try:

        if (
            update
            and update.effective_message
        ):

            await update.effective_message.reply_text(
                "❌ خطایی رخ داد.\n\n"
                "لطفاً دوباره تلاش کنید."
            )

    except Exception as e:

        logger.error(
            f"Error handler failed: {e}"
        )# =========================================================
# MAIN APPLICATION
# =========================================================

def main():

    # -----------------------------------------------------
    # Check BOT TOKEN
    # -----------------------------------------------------

    if not BOT_TOKEN:

        print(
            "❌ خطا: متغیر محیطی BOT_TOKEN تنظیم نشده است."
        )

        return

    # -----------------------------------------------------
    # Check ADMIN ID
    # -----------------------------------------------------

    if not ADMIN_ID:

        print(
            "❌ خطا: متغیر محیطی ADMIN_ID تنظیم نشده است."
        )

        return

    # -----------------------------------------------------
    # Initialize database
    # -----------------------------------------------------

    init_db()

    print(
        "✅ Database initialized successfully."
    )

    # -----------------------------------------------------
    # Create Telegram application
    # -----------------------------------------------------

    application = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )

    # =====================================================
    # COMMAND HANDLERS
    # =====================================================

    application.add_handler(
        CommandHandler(
            "start",
            start_command
        )
    )

    application.add_handler(
        CommandHandler(
            "admin",
            admin_command
        )
    )

    # =====================================================
    # CALLBACK HANDLER
    # =====================================================

    application.add_handler(
        CallbackQueryHandler(
            callback_handler
        )
    )

    # =====================================================
    # TEXT HANDLER
    # =====================================================

    application.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND,
            text_handler
        )
    )

    # =====================================================
    # ERROR HANDLER
    # =====================================================

    application.add_error_handler(
        error_handler
    )

    # -----------------------------------------------------
    # Start bot
    # -----------------------------------------------------

    print(
        "🟢 CafiNetOnline24 is starting..."
    )

    print(
        "🕐 Working hours: 07:00 - 23:00"
    )

    print(
        "🌐 Timezone: Asia/Tehran"
    )

    print(
        "🤖 Bot is running..."
    )

    # -----------------------------------------------------
    # Polling
    # -----------------------------------------------------

    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


# =========================================================
# PROGRAM ENTRY POINT
# =========================================================

if __name__ == "__main__":

    main()
    )
