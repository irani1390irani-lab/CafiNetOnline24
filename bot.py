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

# =========================
# CONFIG
# =========================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID_RAW = os.getenv("ADMIN_ID")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is not set.")

if not ADMIN_ID_RAW:
    raise RuntimeError("ADMIN_ID environment variable is not set.")

ADMIN_ID = int(ADMIN_ID_RAW)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, "cafinet.db")

IRAN_TZ = ZoneInfo("Asia/Tehran")

CHANNEL_LINK = "https://t.me/CafiNetOnlin24"
BOT_LINK = "https://t.me/CafiNetOnlinBot"

OPEN_HOUR = 7
CLOSE_HOUR = 23

# =========================
# PAYMENT CONFIG
# =========================
PAYMENT_CARD_NUMBER = os.getenv(
    "PAYMENT_CARD_NUMBER",
    "شماره کارت را اینجا قرار دهید"
)

PAYMENT_CARD_NAME = os.getenv(
    "PAYMENT_CARD_NAME",
    "نام صاحب کارت"
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger("CafiNetOnline24")


# =========================
# TIME
# =========================
def iran_now():
    return datetime.now(IRAN_TZ)


def now_text():
    return iran_now().strftime("%Y-%m-%d %H:%M:%S")


def today_text():
    return iran_now().strftime("%Y-%m-%d")


def is_bot_closed():
    now = iran_now().time()
    return now >= time(CLOSE_HOUR, 0) or now < time(OPEN_HOUR, 0)


def closed_text():
    return (
        "🌙 ربات در حال حاضر غیرفعال است.\n\n"
        "🤖 ساعت فعالیت ربات: ۰۷:۰۰ تا ۲۳:۰۰\n"
        "⏰ لطفاً در ساعات فعالیت دوباره مراجعه کنید."
    )


# =========================
# DATABASE
# =========================
def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS requests(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tracking_code TEXT UNIQUE,
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
        """
    )

    # =========================
    # PAYMENT COLUMNS
    # =========================
    existing_columns = [
        row["name"]
        for row in cur.execute(
            "PRAGMA table_info(requests)"
        ).fetchall()
    ]

    payment_columns = {
        "payment_status": "TEXT DEFAULT '⚪ پرداخت درخواست نشده'",
        "payment_amount": "INTEGER DEFAULT 0",
        "payment_card": "TEXT DEFAULT ''",
        "payment_card_name": "TEXT DEFAULT ''",
        "receipt_file_id": "TEXT DEFAULT ''",
        "receipt_type": "TEXT DEFAULT ''",
        "payment_sent_at": "TEXT DEFAULT ''",
        "receipt_sent_at": "TEXT DEFAULT ''",
        "payment_verified_at": "TEXT DEFAULT ''",
    }

    for column, definition in payment_columns.items():
        if column not in existing_columns:
            cur.execute(
                f"ALTER TABLE requests ADD COLUMN {column} {definition}"
            )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS registrations(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            registration_date TEXT,
            active INTEGER DEFAULT 1,
            created_at TEXT
        )
        """
    )

    # Users table makes broadcast work even for users
    # who have not submitted a service request.
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            created_at TEXT,
            updated_at TEXT
        )
        """
    )

    # Support messages are stored so the admin can reply later.
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS support_messages(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            message TEXT,
            created_at TEXT,
            replied INTEGER DEFAULT 0
        )
        """
    )

    conn.commit()
    conn.close()


def save_user(user):
    if not user:
        return

    conn = get_db()

    conn.execute(
        """
        INSERT INTO users(
            user_id,
            username,
            full_name,
            created_at,
            updated_at
        )
        VALUES(?,?,?,?,?)

        ON CONFLICT(user_id) DO UPDATE SET
            username=excluded.username,
            full_name=excluded.full_name,
            updated_at=excluded.updated_at
        """,
        (
            user.id,
            user.username or "",
            user.full_name or "",
            now_text(),
            now_text(),
        ),
    )

    conn.commit()
    conn.close()


# =========================
# STATES
# =========================
USER_STATES = {}

STATE_NAME = "name"
STATE_PHONE = "phone"
STATE_TELEGRAM = "telegram"
STATE_DESCRIPTION = "description"
STATE_TRACKING = "tracking"

STATE_ADMIN_SEARCH = "admin_search"
STATE_ADMIN_ADD_REG = "admin_add_reg"
STATE_BROADCAST = "broadcast"
STATE_SUPPORT = "support"

# =========================
# PAYMENT STATES
# =========================
STATE_ADMIN_PAYMENT_AMOUNT = "admin_payment_amount"
STATE_USER_RECEIPT = "user_receipt"

PAYMENT_WAITING = "🟡 در انتظار پرداخت"
PAYMENT_RECEIPT_REVIEW = "🔎 در انتظار بررسی رسید"
PAYMENT_CONFIRMED = "🟢 پرداخت تأیید شد"
PAYMENT_REJECTED = "🔴 رسید رد شد"


# =========================
# REQUEST FUNCTIONS
# =========================
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

    cur.execute(
        """
        INSERT INTO requests(
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
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
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
            now_text(),
            now_text(),
        ),
    )

    request_id = cur.lastrowid
    tracking_code = f"CF{10000 + request_id}"

    cur.execute(
        "UPDATE requests SET tracking_code=? WHERE id=?",
        (tracking_code, request_id),
    )

    conn.commit()

    row = cur.execute(
        "SELECT * FROM requests WHERE id=?",
        (request_id,),
    ).fetchone()

    conn.close()
    return row


def get_request(code):
    if not code:
        return None

    code = code.upper().replace("#", "").strip()

    conn = get_db()

    row = conn.execute(
        "SELECT * FROM requests WHERE tracking_code=?",
        (code,),
    ).fetchone()

    conn.close()

    return row


def update_status(code, status):
    conn = get_db()

    conn.execute(
        """
        UPDATE requests
        SET status=?, updated_at=?
        WHERE tracking_code=?
        """,
        (
            status,
            now_text(),
            code,
        ),
    )

    conn.commit()
    conn.close()


def get_user_requests(user_id, limit=20):
    conn = get_db()

    rows = conn.execute(
        """
        SELECT *
        FROM requests
        WHERE user_id=?
        ORDER BY id DESC
        LIMIT ?
        """,
        (
            user_id,
            limit,
        ),
    ).fetchall()

    conn.close()

    return rows


def get_stats():
    conn = get_db()

    total = conn.execute(
        "SELECT COUNT(*) AS c FROM requests"
    ).fetchone()["c"]

    waiting = conn.execute(
        "SELECT COUNT(*) AS c FROM requests WHERE status=?",
        ("🟡 در انتظار بررسی",),
    ).fetchone()["c"]

    doing = conn.execute(
        "SELECT COUNT(*) AS c FROM requests WHERE status=?",
        ("🔵 در حال انجام",),
    ).fetchone()["c"]

    done = conn.execute(
        "SELECT COUNT(*) AS c FROM requests WHERE status=?",
        ("🟢 انجام شد",),
    ).fetchone()["c"]

    rejected = conn.execute(
        "SELECT COUNT(*) AS c FROM requests WHERE status=?",
        ("🔴 رد شد",),
    ).fetchone()["c"]

    users = conn.execute(
        "SELECT COUNT(*) AS c FROM users"
    ).fetchone()["c"]

    conn.close()

    return {
        "total": total,
        "waiting": waiting,
        "doing": doing,
        "done": done,
        "rejected": rejected,
        "users": users,
    }


# =========================
# PAYMENT FUNCTIONS
# =========================
def set_payment_request(code, amount):
    conn = get_db()

    conn.execute(
        """
        UPDATE requests
        SET
            payment_status=?,
            payment_amount=?,
            payment_card=?,
            payment_card_name=?,
            payment_sent_at=?,
            updated_at=?
        WHERE tracking_code=?
        """,
        (
            PAYMENT_WAITING,
            amount,
            PAYMENT_CARD_NUMBER,
            PAYMENT_CARD_NAME,
            now_text(),
            now_text(),
            code,
        ),
    )

    conn.commit()
    conn.close()


def save_receipt(code, file_id, receipt_type):
    conn = get_db()

    conn.execute(
        """
        UPDATE requests
        SET
            payment_status=?,
            receipt_file_id=?,
            receipt_type=?,
            receipt_sent_at=?,
            updated_at=?
        WHERE tracking_code=?
        """,
        (
            PAYMENT_RECEIPT_REVIEW,
            file_id,
            receipt_type,
            now_text(),
            now_text(),
            code,
        ),
    )

    conn.commit()
    conn.close()


def confirm_payment(code):
    conn = get_db()

    conn.execute(
        """
        UPDATE requests
        SET
            payment_status=?,
            payment_verified_at=?,
            updated_at=?
        WHERE tracking_code=?
        """,
        (
            PAYMENT_CONFIRMED,
            now_text(),
            now_text(),
            code,
        ),
    )

    conn.commit()
    conn.close()


def reject_payment(code):
    conn = get_db()

    conn.execute(
        """
        UPDATE requests
        SET
            payment_status=?,
            updated_at=?
        WHERE tracking_code=?
        """,
        (
            PAYMENT_REJECTED,
            now_text(),
            code,
        ),
    )

    conn.commit()
    conn.close()


def format_amount(amount):
    try:
        return f"{int(amount):,}"
    except (TypeError, ValueError):
        return "0"# =========================================================
# REGISTRATION FUNCTIONS
# =========================================================

def add_registration(title, registration_date=None):
    conn = get_db()

    if registration_date is None:
        registration_date = now_text()

    cursor = conn.execute(
        """
        INSERT INTO registrations
        (title, registration_date, active, created_at)
        VALUES (?, ?, 1, ?)
        """,
        (
            title,
            registration_date,
            now_text(),
        ),
    )

    registration_id = cursor.lastrowid

    conn.commit()
    conn.close()

    return registration_id


def get_today_registrations():
    conn = get_db()

    today = datetime.now(IRAN_TZ).strftime("%Y-%m-%d")

    rows = conn.execute(
        """
        SELECT *
        FROM registrations
        WHERE active=1
        AND substr(registration_date, 1, 10)=?
        ORDER BY id DESC
        """,
        (today,),
    ).fetchall()

    conn.close()

    return rows


def get_registration(registration_id):
    conn = get_db()

    row = conn.execute(
        """
        SELECT *
        FROM registrations
        WHERE id=?
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
        SET active=0
        WHERE id=?
        """,
        (registration_id,),
    )

    conn.commit()
    conn.close()


def get_all_active_registrations():
    conn = get_db()

    rows = conn.execute(
        """
        SELECT *
        FROM registrations
        WHERE active=1
        ORDER BY id DESC
        """
    ).fetchall()

    conn.close()

    return rows


# =========================================================
# KEYBOARDS
# =========================================================

def main_keyboard(user_id=None):
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
                callback_data="track_request"
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
        keyboard.append(
            [
                InlineKeyboardButton(
                    "🛠 پنل مدیریت",
                    callback_data="admin_panel"
                )
            ]
        )

    return InlineKeyboardMarkup(keyboard)


def admin_keyboard():
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "📋 درخواست‌های جدید",
                    callback_data="admin_requests"
                )
            ],
            [
                InlineKeyboardButton(
                    "🔎 جستجوی درخواست",
                    callback_data="admin_search"
                ),
                InlineKeyboardButton(
                    "📝 افزودن ثبت‌نام امروز",
                    callback_data="admin_add_registration"
                )
            ],
            [
                InlineKeyboardButton(
                    "📑 لیست ثبت‌نام‌ها",
                    callback_data="admin_registrations"
                )
            ],
            [
                InlineKeyboardButton(
                    "📊 آمار ربات",
                    callback_data="admin_stats"
                ),
                InlineKeyboardButton(
                    "📢 ارسال پیام همگانی",
                    callback_data="broadcast"
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
            ],
        ]
    )


# =========================================================
# STATUS KEYBOARD
# =========================================================

def status_keyboard(code):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "💳 ارسال مشخصات پرداخت",
                    callback_data=f"send_payment|{code}"
                )
            ],
            [
                InlineKeyboardButton(
                    "🔵 در حال انجام",
                    callback_data=f"status|doing|{code}"
                ),
                InlineKeyboardButton(
                    "🟢 انجام شد",
                    callback_data=f"status|done|{code}"
                )
            ],
            [
                InlineKeyboardButton(
                    "🔴 رد شد",
                    callback_data=f"status|reject|{code}"
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 پنل مدیریت",
                    callback_data="admin_panel"
                )
            ],
        ]
    )


# =========================================================
# ONLINE REGISTRATION MENU
# =========================================================

def online_registration_keyboard():
    rows = []

    registrations = get_today_registrations()

    for registration in registrations:
        rows.append(
            [
                InlineKeyboardButton(
                    registration["title"],
                    callback_data=f"online_service|{registration['id']}"
                )
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(
                "🔙 بازگشت",
                callback_data="home"
            )
        ]
    )

    return InlineKeyboardMarkup(rows)


# =========================================================
# SERVICE CATEGORIES
# =========================================================

SERVICE_CATEGORIES = {
    "vehicle": [
        "🚘 ثبت‌نام ایران‌خودرو",
        "🚘 ثبت‌نام سایپا",
        "♻️ ثبت‌نام خودروهای فرسوده",
        "📋 نوبت تعویض پلاک",
        "🏍️ تعویض پلاک موتورسیکلت",
        "⛽ خدمات کارت سوخت",
        "💳 استعلام و پرداخت خلافی",
        "🚗 سایر خدمات خودرو",
    ],

    "insurance": [
        "🚗 بیمه شخص ثالث",
        "🚘 بیمه بدنه",
        "🏥 بیمه درمان",
        "👤 بیمه تأمین اجتماعی",
        "📄 سوابق بیمه",
        "💳 فیش بیمه",
        "🏃 بیمه ورزشی",
        "🛡️ سایر خدمات بیمه",
    ],

    "tax": [
        "🧾 تشکیل پرونده مالیاتی",
        "🔢 دریافت کد مالیاتی",
        "📄 اظهارنامه مالیاتی",
        "💳 پرداخت مالیات",
        "⚖️ اعتراض مالیاتی",
        "📨 دریافت ابلاغیه مالیاتی",
        "📊 خدمات مالیاتی",
    ],

    "judicial": [
        "🪪 ثبت‌نام و احراز هویت ثنا",
        "📄 گواهی عدم سوءپیشینه",
        "📨 دریافت ابلاغیه قضایی",
        "🏛️ نوبت‌دهی قضایی",
        "⚖️ ثبت دادخواست",
        "👮 سامانه سخا",
        "⚖️ سایر خدمات قضایی",
    ],

    "bank": [
        "📝 ثبت چک صیادی",
        "🔎 استعلام چک",
        "🔄 انتقال چک",
        "🏦 افتتاح حساب",
        "💳 خدمات کارت بانکی",
        "🔢 دریافت شماره شبا",
        "📄 دریافت گواهی بانکی",
        "🏦 سایر خدمات بانکی",
    ],

    "loan": [
        "💍 ثبت‌نام وام ازدواج",
        "👶 ثبت‌نام وام فرزندآوری",
        "🏠 وام ودیعه مسکن",
        "🏡 وام مسکن",
        "💼 وام اشتغال",
        "💰 سایر تسهیلات حمایتی",
    ],
}


CATEGORY_TITLES = {
    "vehicle": "🚗 خدمات خودرو",
    "insurance": "🛡 خدمات بیمه",
    "tax": "💰 خدمات مالیاتی",
    "judicial": "⚖️ خدمات قضایی",
    "bank": "🏦 خدمات بانکی",
    "loan": "💵 خدمات وام",
}


def category_keyboard(category):
    services = SERVICE_CATEGORIES.get(category, [])

    rows = []

    for index, service in enumerate(services):
        rows.append(
            [
                InlineKeyboardButton(
                    service,
                    callback_data=f"service|{category}|{index}"
                )
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(
                "🔙 بازگشت",
                callback_data="home"
            )
        ]
    )

    return InlineKeyboardMarkup(rows)


def get_service(category, index):
    services = SERVICE_CATEGORIES.get(category, [])

    try:
        index = int(index)
    except (TypeError, ValueError):
        return None

    if index < 0 or index >= len(services):
        return None

    return services[index]


# =========================================================
# REQUEST DISPLAY
# =========================================================

def format_request(request):
    if not request:
        return "❌ درخواست پیدا نشد."

    payment_status = request["payment_status"] or "⚪ پرداخت درخواست نشده"

    text = (
        f"🎫 کد پیگیری: {request['tracking_code']}\n\n"
        f"👤 نام و نام خانوادگی: {request['full_name']}\n"
        f"📱 شماره موبایل: {request['phone']}\n"
        f"💬 آیدی تلگرام: {request['telegram_id'] or 'ندارد'}\n"
        f"🔧 خدمت: {request['service']}\n"
        f"📂 دسته‌بندی: {request['category']}\n\n"
        f"📝 توضیحات:\n"
        f"{request['description'] or 'ندارد'}\n\n"
        f"📌 وضعیت درخواست: {request['status']}\n"
        f"💳 وضعیت پرداخت: {payment_status}\n"
    )

    if request["payment_amount"]:
        text += (
            f"💰 مبلغ پرداخت: "
            f"{format_amount(request['payment_amount'])} ریال\n"
        )

    text += (
        f"\n🕐 زمان ثبت: {request['created_at']}\n"
        f"🔄 آخرین بروزرسانی: {request['updated_at']}"
    )

    return text


# =========================================================
# BEGIN REQUEST
# =========================================================

async def begin_request(update, context, category, service):
    user = update.effective_user
    uid = user.id

    save_user(user)

    USER_STATES[uid] = {
        "state": STATE_NAME,
        "category": category,
        "service": service,
    }

    await update.callback_query.message.edit_text(
        f"🔧 خدمت انتخاب‌شده:\n{service}\n\n"
        "👤 لطفاً نام و نام خانوادگی خود را ارسال کنید:"
    )


# =========================================================
# START
# =========================================================

async def start(update, context):
    user = update.effective_user

    save_user(user)

    USER_STATES.pop(user.id, None)

    if is_bot_closed() and user.id != ADMIN_ID:
        await update.message.reply_text(
            closed_text()
        )
        return

    await update.message.reply_text(
        "👋 سلام!\n\n"
        "به «کافی‌نت آنلاین 24» خوش آمدید.\n\n"
        "خدمات آنلاین موردنیاز خود را از منوی زیر انتخاب کنید:",
        reply_markup=main_keyboard(user.id)
    )


# =========================================================
# ABOUT
# =========================================================

async def about_message(update, context):
    text = (
        "ℹ️ درباره کافی‌نت آنلاین 24\n\n"
        "ارائه خدمات و ثبت‌نام‌های آنلاین به‌صورت غیرحضوری.\n\n"
        "📌 خدمات:\n"
        "🚗 خودرو\n"
        "🛡 بیمه\n"
        "💰 مالیاتی\n"
        "⚖️ قضایی\n"
        "🏦 بانکی\n"
        "💵 وام\n"
        "📝 ثبت‌نام‌های آنلاین\n\n"
        "🕐 ساعات فعالیت:\n"
        "هر روز از ساعت 07:00 تا 23:00\n\n"
        "📢 پس از ثبت درخواست، کد پیگیری اختصاصی برای شما صادر می‌شود."
    )

    return text


# =========================================================
# ONLINE REGISTRATION TEXT
# =========================================================

async def online_registrations_message(update, context):
    registrations = get_today_registrations()

    if not registrations:
        return (
            "📝 ثبت‌نام‌های آنلاین\n\n"
            "در حال حاضر ثبت‌نام فعالی برای امروز وجود ندارد.\n\n"
            "🔙 از منوی اصلی می‌توانید سایر خدمات را انتخاب کنید."
        )

    text = (
        "📝 ثبت‌نام‌های آنلاین\n\n"
        "لطفاً ثبت‌نام موردنظر خود را انتخاب کنید:"
    )

    return text


# =========================================================
# ADMIN REQUEST LIST
# =========================================================

def get_recent_requests(limit=10):
    conn = get_db()

    rows = conn.execute(
        """
        SELECT *
        FROM requests
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    conn.close()

    return rows


def admin_requests_keyboard():
    rows = []

    requests = get_recent_requests(10)

    for request in requests:
        rows.append(
            [
                InlineKeyboardButton(
                    f"{request['tracking_code']} | "
                    f"{request['status']}",
                    callback_data=f"admin_view|{request['tracking_code']}"
                )
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(
                "🔙 پنل مدیریت",
                callback_data="admin_panel"
            )
        ]
    )

    return InlineKeyboardMarkup(rows)


# =========================================================
# REQUEST OWNER CHECK
# =========================================================

def is_request_owner(request, user_id):
    if not request:
        return False

    return int(request["user_id"]) == int(user_id)


# =========================================================
# USER REQUEST LIST
# =========================================================

def get_user_requests(user_id):
    conn = get_db()

    rows = conn.execute(
        """
        SELECT *
        FROM requests
        WHERE user_id=?
        ORDER BY id DESC
        LIMIT 20
        """,
        (user_id,),
    ).fetchall()

    conn.close()

    return rows


def user_requests_keyboard(user_id):
    rows = []

    requests = get_user_requests(user_id)

    for request in requests:
        rows.append(
            [
                InlineKeyboardButton(
                    f"{request['tracking_code']} | {request['status']}",
                    callback_data=f"user_request|{request['tracking_code']}"
                )
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(
                "🔙 منوی اصلی",
                callback_data="home"
            )
        ]
    )

    return InlineKeyboardMarkup(rows)


# =========================================================
# SUPPORT
# =========================================================

async def start_support(update, context):
    user = update.effective_user

    USER_STATES[user.id] = {
        "state": STATE_SUPPORT
    }

    await update.callback_query.message.edit_text(
        "💬 پشتیبانی\n\n"
        "پیام خود را ارسال کنید.\n"
        "پس از بررسی، مدیریت با شما ارتباط خواهد گرفت.\n\n"
        "🔙 برای لغو، /start را ارسال کنید."
    )


# =========================================================
# ADMIN PANEL TEXT
# =========================================================

def admin_panel_text():
    return (
        "🛠 پنل مدیریت کافی‌نت آنلاین 24\n\n"
        "از منوی زیر بخش موردنظر را انتخاب کنید:"
    )


# =========================================================
# CLOSED BOT TEXT
# =========================================================

def closed_text():
    return (
        "⏰ در حال حاضر ربات خارج از ساعات فعالیت است.\n\n"
        "🕐 ساعات فعالیت:\n"
        "07:00 تا 23:00\n\n"
        "لطفاً در ساعات فعالیت مجدداً مراجعه کنید."
    )# =========================================================
# CALLBACK HANDLER
# =========================================================

async def callback_handler(update, context):
    query = update.callback_query
    user = update.effective_user
    uid = user.id

    await query.answer()

    data = query.data or ""

    save_user(user)

    # =====================================================
    # HOME
    # =====================================================

    if data == "home":
        USER_STATES.pop(uid, None)

        await query.message.edit_text(
            "🏠 منوی اصلی\n\n"
            "لطفاً یکی از خدمات زیر را انتخاب کنید:",
            reply_markup=main_keyboard(uid)
        )
        return

    # =====================================================
    # ADMIN PANEL
    # =====================================================

    if data == "admin_panel":
        if uid != ADMIN_ID:
            await query.answer(
                "⛔ دسترسی غیرمجاز",
                show_alert=True
            )
            return

        USER_STATES.pop(uid, None)

        await query.message.edit_text(
            admin_panel_text(),
            reply_markup=admin_keyboard()
        )
        return

    # =====================================================
    # ONLINE REGISTRATIONS
    # =====================================================

    if data == "online_registrations":
        USER_STATES.pop(uid, None)

        text = await online_registrations_message(
            update,
            context
        )

        await query.message.edit_text(
            text,
            reply_markup=online_registration_keyboard()
        )
        return

    # =====================================================
    # SERVICE CATEGORY
    # =====================================================

    if data.startswith("category|"):
        category = data.split("|", 1)[1]

        if category not in SERVICE_CATEGORIES:
            await query.answer(
                "❌ دسته‌بندی نامعتبر است.",
                show_alert=True
            )
            return

        USER_STATES.pop(uid, None)

        title = CATEGORY_TITLES.get(
            category,
            "🛠 خدمات"
        )

        await query.message.edit_text(
            f"{title}\n\n"
            "لطفاً خدمت موردنظر را انتخاب کنید:",
            reply_markup=category_keyboard(category)
        )
        return

    # =====================================================
    # SERVICE SELECTION
    # =====================================================

    if data.startswith("service|"):
        parts = data.split("|")

        if len(parts) != 3:
            await query.answer(
                "❌ اطلاعات خدمت نامعتبر است.",
                show_alert=True
            )
            return

        category = parts[1]
        index = parts[2]

        service = get_service(
            category,
            index
        )

        if not service:
            await query.answer(
                "❌ خدمت پیدا نشد.",
                show_alert=True
            )
            return

        await begin_request(
            update,
            context,
            category,
            service
        )
        return

    # =====================================================
    # ONLINE REGISTRATION SERVICE
    # =====================================================

    if data.startswith("online_service|"):
        parts = data.split("|")

        if len(parts) != 2:
            await query.answer(
                "❌ اطلاعات ثبت‌نام نامعتبر است.",
                show_alert=True
            )
            return

        registration_id = parts[1]

        registration = get_registration(
            registration_id
        )

        if not registration or not registration["active"]:
            await query.answer(
                "❌ این ثبت‌نام دیگر فعال نیست.",
                show_alert=True
            )
            return

        USER_STATES[uid] = {
            "state": STATE_NAME,
            "category": "ثبت‌نام آنلاین",
            "service": registration["title"],
            "registration_id": registration["id"],
        }

        await query.message.edit_text(
            f"📝 ثبت‌نام آنلاین\n\n"
            f"📌 مورد انتخابی:\n"
            f"{registration['title']}\n\n"
            "👤 لطفاً نام و نام خانوادگی خود را ارسال کنید:"
        )
        return

    # =====================================================
    # ONLINE REGISTRATION START
    # =====================================================

    if data.startswith("online_start|"):
        parts = data.split("|")

        if len(parts) != 2:
            await query.answer(
                "❌ اطلاعات نامعتبر است.",
                show_alert=True
            )
            return

        registration_id = parts[1]

        registration = get_registration(
            registration_id
        )

        if not registration or not registration["active"]:
            await query.answer(
                "❌ این ثبت‌نام دیگر فعال نیست.",
                show_alert=True
            )
            return

        USER_STATES[uid] = {
            "state": STATE_NAME,
            "category": "ثبت‌نام آنلاین",
            "service": registration["title"],
            "registration_id": registration["id"],
        }

        await query.message.edit_text(
            f"📝 ثبت‌نام آنلاین\n\n"
            f"📌 {registration['title']}\n\n"
            "👤 لطفاً نام و نام خانوادگی خود را ارسال کنید:"
        )
        return

    # =====================================================
    # TRACK REQUEST
    # =====================================================

    if data == "track_request":
        USER_STATES[uid] = {
            "state": STATE_TRACKING
        }

        await query.message.edit_text(
            "🔎 پیگیری درخواست\n\n"
            "کد پیگیری خود را ارسال کنید:"
        )
        return

    # =====================================================
    # MY REQUESTS
    # =====================================================

    if data == "my_requests":
        requests = get_user_requests(uid)

        if not requests:
            await query.message.edit_text(
                "📋 درخواست‌های من\n\n"
                "هنوز هیچ درخواستی ثبت نکرده‌اید.",
                reply_markup=InlineKeyboardMarkup(
                    [[
                        InlineKeyboardButton(
                            "🔙 منوی اصلی",
                            callback_data="home"
                        )
                    ]]
                )
            )
            return

        await query.message.edit_text(
            "📋 درخواست‌های من\n\n"
            "برای مشاهده جزئیات، درخواست موردنظر را انتخاب کنید:",
            reply_markup=user_requests_keyboard(uid)
        )
        return

    # =====================================================
    # USER REQUEST VIEW
    # =====================================================

    if data.startswith("user_request|"):
        code = data.split("|", 1)[1]

        request = get_request(code)

        if not request or not is_request_owner(
            request,
            uid
        ):
            await query.answer(
                "❌ این درخواست متعلق به شما نیست.",
                show_alert=True
            )
            return

        text = format_request(request)

        rows = []

        if (
            request["payment_status"]
            in (
                PAYMENT_WAITING,
                PAYMENT_REJECTED,
            )
            and request["payment_amount"]
        ):
            rows.append(
                [
                    InlineKeyboardButton(
                        "📤 ارسال رسید پرداخت",
                        callback_data=f"send_receipt|{code}"
                    )
                ]
            )

        rows.append(
            [
                InlineKeyboardButton(
                    "🔙 درخواست‌های من",
                    callback_data="my_requests"
                )
            ]
        )

        await query.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(rows)
        )
        return

    # =====================================================
    # SUPPORT
    # =====================================================

    if data == "support":
        await start_support(
            update,
            context
        )
        return

    # =====================================================
    # ABOUT
    # =====================================================

    if data == "about":
        await query.message.edit_text(
            await about_message(
                update,
                context
            ),
            reply_markup=InlineKeyboardMarkup(
                [[
                    InlineKeyboardButton(
                        "🔙 منوی اصلی",
                        callback_data="home"
                    )
                ]]
            )
        )
        return

    # =====================================================
    # ADMIN REQUESTS
    # =====================================================

    if data == "admin_requests":
        if uid != ADMIN_ID:
            await query.answer(
                "⛔ دسترسی غیرمجاز",
                show_alert=True
            )
            return

        requests = get_recent_requests(10)

        if not requests:
            await query.message.edit_text(
                "📋 در حال حاضر هیچ درخواستی ثبت نشده است.",
                reply_markup=InlineKeyboardMarkup(
                    [[
                        InlineKeyboardButton(
                            "🔙 پنل مدیریت",
                            callback_data="admin_panel"
                        )
                    ]]
                )
            )
            return

        await query.message.edit_text(
            "📋 آخرین درخواست‌ها:",
            reply_markup=admin_requests_keyboard()
        )
        return

    # =====================================================
    # ADMIN VIEW REQUEST
    # =====================================================

    if data.startswith("admin_view|"):
        if uid != ADMIN_ID:
            await query.answer(
                "⛔ دسترسی غیرمجاز",
                show_alert=True
            )
            return

        code = data.split("|", 1)[1]

        request = get_request(code)

        if not request:
            await query.answer(
                "❌ درخواست پیدا نشد.",
                show_alert=True
            )
            return

        text = (
            "🛠 جزئیات درخواست\n\n"
            + format_request(request)
        )

        await query.message.edit_text(
            text,
            reply_markup=status_keyboard(code)
        )
        return

    # =====================================================
    # SEND PAYMENT DETAILS
    # =====================================================

    if data.startswith("send_payment|"):
        if uid != ADMIN_ID:
            await query.answer(
                "⛔ فقط مدیریت می‌تواند مشخصات پرداخت را ارسال کند.",
                show_alert=True
            )
            return

        code = data.split("|", 1)[1]

        request = get_request(code)

        if not request:
            await query.answer(
                "❌ درخواست پیدا نشد.",
                show_alert=True
            )
            return

        USER_STATES[uid] = {
            "state": STATE_ADMIN_PAYMENT_AMOUNT,
            "request_code": code,
        }

        await query.message.reply_text(
            f"💳 ارسال مشخصات پرداخت\n\n"
            f"🎫 کد درخواست: {code}\n\n"
            "💰 مبلغ پرداخت را به ریال ارسال کنید.\n\n"
            "مثال:\n"
            "1500000"
        )

        return

    # =====================================================
    # SEND RECEIPT
    # =====================================================

    if data.startswith("send_receipt|"):
        code = data.split("|", 1)[1]

        request = get_request(code)

        if not request:
            await query.answer(
                "❌ درخواست پیدا نشد.",
                show_alert=True
            )
            return

        if not is_request_owner(
            request,
            uid
        ):
            await query.answer(
                "⛔ این درخواست متعلق به شما نیست.",
                show_alert=True
            )
            return

        if not request["payment_amount"]:
            await query.answer(
                "❌ هنوز مبلغ پرداخت برای این درخواست تعیین نشده است.",
                show_alert=True
            )
            return

        if request["payment_status"] == PAYMENT_CONFIRMED:
            await query.answer(
                "✅ پرداخت این درخواست قبلاً تأیید شده است.",
                show_alert=True
            )
            return

        USER_STATES[uid] = {
            "state": STATE_USER_RECEIPT,
            "request_code": code,
        }

        await query.message.reply_text(
            "📤 ارسال رسید پرداخت\n\n"
            f"💰 مبلغ: "
            f"{format_amount(request['payment_amount'])} ریال\n\n"
            "لطفاً تصویر یا فایل رسید پرداخت را ارسال کنید."
        )

        return

    # =====================================================
    # APPROVE PAYMENT
    # =====================================================

    if data.startswith("approve_payment|"):
        if uid != ADMIN_ID:
            await query.answer(
                "⛔ فقط مدیریت می‌تواند پرداخت را تأیید کند.",
                show_alert=True
            )
            return

        code = data.split("|", 1)[1]

        request = get_request(code)

        if not request:
            await query.answer(
                "❌ درخواست پیدا نشد.",
                show_alert=True
            )
            return

        if request["payment_status"] == PAYMENT_CONFIRMED:
            await query.answer(
                "✅ این پرداخت قبلاً تأیید شده است.",
                show_alert=True
            )
            return

        # ثبت تأیید پرداخت
        confirm_payment(code)

        # بعد از تأیید پرداخت، درخواست وارد مرحله انجام می‌شود
        update_status(
            code,
            "🔵 در حال انجام"
        )

        await query.message.reply_text(
            f"✅ پرداخت درخواست {code} تأیید شد.\n\n"
            "🔵 وضعیت درخواست به «در حال انجام» تغییر کرد."
        )

        try:
            await context.bot.send_message(
                chat_id=request["user_id"],
                text=(
                    "✅ پرداخت شما تأیید شد.\n\n"
                    f"🎫 کد درخواست: {code}\n"
                    f"💰 مبلغ: "
                    f"{format_amount(request['payment_amount'])} ریال\n\n"
                    "🔵 درخواست شما اکنون در حال انجام است."
                ),
                reply_markup=main_keyboard(
                    request["user_id"]
                )
            )
        except Exception:
            logger.exception(
                "Could not notify user about payment approval"
            )

        return

    # =====================================================
    # REJECT PAYMENT
    # =====================================================

    if data.startswith("reject_payment|"):
        if uid != ADMIN_ID:
            await query.answer(
                "⛔ فقط مدیریت می‌تواند رسید را رد کند.",
                show_alert=True
            )
            return

        code = data.split("|", 1)[1]

        request = get_request(code)

        if not request:
            await query.answer(
                "❌ درخواست پیدا نشد.",
                show_alert=True
            )
            return

        reject_payment(code)

        await query.message.reply_text(
            f"❌ رسید پرداخت درخواست {code} رد شد."
        )

        try:
            await context.bot.send_message(
                chat_id=request["user_id"],
                text=(
                    "❌ رسید پرداخت شما تأیید نشد.\n\n"
                    f"🎫 کد درخواست: {code}\n"
                    f"💰 مبلغ: "
                    f"{format_amount(request['payment_amount'])} ریال\n\n"
                    "لطفاً رسید صحیح را مجدداً ارسال کنید."
                ),
                reply_markup=InlineKeyboardMarkup(
                    [[
                        InlineKeyboardButton(
                            "📤 ارسال رسید جدید",
                            callback_data=f"send_receipt|{code}"
                        )
                    ]]
                )
            )
        except Exception:
            logger.exception(
                "Could not notify user about rejected receipt"
            )

        return

    # =====================================================
    # REQUEST STATUS
    # =====================================================

    if data.startswith("status|"):
        if uid != ADMIN_ID:
            await query.answer(
                "⛔ دسترسی غیرمجاز",
                show_alert=True
            )
            return

        parts = data.split("|")

        if len(parts) != 3:
            await query.answer(
                "❌ اطلاعات وضعیت نامعتبر است.",
                show_alert=True
            )
            return

        action = parts[1]
        code = parts[2]

        request = get_request(code)

        if not request:
            await query.answer(
                "❌ درخواست پیدا نشد.",
                show_alert=True
            )
            return

        # -------------------------------------------------
        # جلوگیری از شروع کار قبل از تأیید پرداخت
        # -------------------------------------------------

        if action == "doing":
            if request["payment_status"] != PAYMENT_CONFIRMED:
                await query.answer(
                    "⛔ ابتدا باید پرداخت توسط مدیریت تأیید شود.",
                    show_alert=True
                )

                await query.message.reply_text(
                    "⛔ امکان تغییر وضعیت به «🔵 در حال انجام» وجود ندارد.\n\n"
                    "ابتدا مبلغ را برای مشتری ارسال کنید، "
                    "رسید را دریافت و پس از بررسی حساب بانکی "
                    "پرداخت را تأیید کنید."
                )

                return

        status_map = {
            "doing": "🔵 در حال انجام",
            "done": "🟢 انجام شد",
            "reject": "🔴 رد شد",
        }

        new_status = status_map.get(action)

        if not new_status:
            await query.answer(
                "❌ وضعیت نامعتبر است.",
                show_alert=True
            )
            return

        update_status(
            code,
            new_status
        )

        await query.message.reply_text(
            f"✅ وضعیت درخواست {code} تغییر کرد:\n"
            f"{new_status}"
        )

        try:
            await context.bot.send_message(
                chat_id=request["user_id"],
                text=(
                    "🔔 بروزرسانی درخواست\n\n"
                    f"🎫 کد پیگیری: {code}\n"
                    f"📌 وضعیت جدید: {new_status}"
                )
            )
        except Exception:
            logger.exception(
                "Could not notify user about status change"
            )

        return

    # =====================================================
    # ADMIN SEARCH
    # =====================================================

    if data == "admin_search":
        if uid != ADMIN_ID:
            await query.answer(
                "⛔ دسترسی غیرمجاز",
                show_alert=True
            )
            return

        USER_STATES[uid] = {
            "state": STATE_ADMIN_SEARCH
        }

        await query.message.edit_text(
            "🔎 جستجوی درخواست\n\n"
            "کد پیگیری، شماره موبایل یا نام کاربر را ارسال کنید:"
        )
        return

    # =====================================================
    # ADMIN ADD REGISTRATION
    # =====================================================

    if data == "admin_add_registration":
        if uid != ADMIN_ID:
            await query.answer(
                "⛔ دسترسی غیرمجاز",
                show_alert=True
            )
            return

        USER_STATES[uid] = {
            "state": STATE_ADMIN_ADD_REG
        }

        await query.message.edit_text(
            "📝 افزودن ثبت‌نام امروز\n\n"
            "عنوان ثبت‌نام را ارسال کنید:"
        )
        return

    # =====================================================
    # ADMIN REGISTRATIONS
    # =====================================================

    if data == "admin_registrations":
        if uid != ADMIN_ID:
            await query.answer(
                "⛔ دسترسی غیرمجاز",
                show_alert=True
            )
            return

        registrations = get_all_active_registrations()

        if not registrations:
            await query.message.edit_text(
                "📑 ثبت‌نام فعالی وجود ندارد.",
                reply_markup=InlineKeyboardMarkup(
                    [[
                        InlineKeyboardButton(
                            "🔙 پنل مدیریت",
                            callback_data="admin_panel"
                        )
                    ]]
                )
            )
            return

        rows = []

        for registration in registrations:
            rows.append(
                [
                    InlineKeyboardButton(
                        f"❌ غیرفعال کردن | "
                        f"{registration['title']}",
                        callback_data=(
                            f"deactivate_reg|"
                            f"{registration['id']}"
                        )
                    )
                ]
            )

        rows.append(
            [
                InlineKeyboardButton(
                    "🔙 پنل مدیریت",
                    callback_data="admin_panel"
                )
            ]
        )

        await query.message.edit_text(
            "📑 لیست ثبت‌نام‌های فعال:",
            reply_markup=InlineKeyboardMarkup(rows)
        )
        return

    # =====================================================
    # DEACTIVATE REGISTRATION
    # =====================================================

    if data.startswith("deactivate_reg|"):
        if uid != ADMIN_ID:
            await query.answer(
                "⛔ دسترسی غیرمجاز",
                show_alert=True
            )
            return

        registration_id = data.split("|", 1)[1]

        registration = get_registration(
            registration_id
        )

        if not registration:
            await query.answer(
                "❌ ثبت‌نام پیدا نشد.",
                show_alert=True
            )
            return

        deactivate_registration(
            registration_id
        )

        await query.answer(
            "✅ ثبت‌نام غیرفعال شد."
        )

        await query.message.edit_text(
            f"✅ ثبت‌نام زیر غیرفعال شد:\n\n"
            f"{registration['title']}",
            reply_markup=InlineKeyboardMarkup(
                [[
                    InlineKeyboardButton(
                        "🔙 لیست ثبت‌نام‌ها",
                        callback_data="admin_registrations"
                    )
                ]]
            )
        )
        return

    # =====================================================
    # ADMIN STATS
    # =====================================================

    if data == "admin_stats":
        if uid != ADMIN_ID:
            await query.answer(
                "⛔ دسترسی غیرمجاز",
                show_alert=True
            )
            return

        conn = get_db()

        total_requests = conn.execute(
            "SELECT COUNT(*) FROM requests"
        ).fetchone()[0]

        waiting = conn.execute(
            """
            SELECT COUNT(*)
            FROM requests
            WHERE status='🟡 در انتظار بررسی'
            """
        ).fetchone()[0]

        doing = conn.execute(
            """
            SELECT COUNT(*)
            FROM requests
            WHERE status='🔵 در حال انجام'
            """
        ).fetchone()[0]

        done = conn.execute(
            """
            SELECT COUNT(*)
            FROM requests
            WHERE status='🟢 انجام شد'
            """
        ).fetchone()[0]

        rejected = conn.execute(
            """
            SELECT COUNT(*)
            FROM requests
            WHERE status='🔴 رد شد'
            """
        ).fetchone()[0]

        users_count = conn.execute(
            "SELECT COUNT(*) FROM users"
        ).fetchone()[0]

        payment_confirmed = conn.execute(
            """
            SELECT COUNT(*)
            FROM requests
            WHERE payment_status=?
            """,
            (PAYMENT_CONFIRMED,),
        ).fetchone()[0]

        payment_review = conn.execute(
            """
            SELECT COUNT(*)
            FROM requests
            WHERE payment_status=?
            """,
            (PAYMENT_RECEIPT_REVIEW,),
        ).fetchone()[0]

        conn.close()

        text = (
            "📊 آمار ربات\n\n"
            f"👥 کاربران: {users_count}\n"
            f"📋 کل درخواست‌ها: {total_requests}\n\n"
            f"🟡 در انتظار بررسی: {waiting}\n"
            f"🔵 در حال انجام: {doing}\n"
            f"🟢 انجام‌شده: {done}\n"
            f"🔴 ردشده: {rejected}\n\n"
            f"💳 پرداخت‌های تأییدشده: {payment_confirmed}\n"
            f"🔎 رسیدهای در انتظار بررسی: {payment_review}"
        )

        await query.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(
                [[
                    InlineKeyboardButton(
                        "🔙 پنل مدیریت",
                        callback_data="admin_panel"
                    )
                ]]
            )
        )
        return

    # =====================================================
    # BROADCAST
    # =====================================================

    if data == "broadcast":
        if uid != ADMIN_ID:
            await query.answer(
                "⛔ دسترسی غیرمجاز",
                show_alert=True
            )
            return

        USER_STATES[uid] = {
            "state": STATE_BROADCAST
        }

        await query.message.edit_text(
            "📢 ارسال پیام همگانی\n\n"
            "متن پیام را ارسال کنید:"
        )
        return

    # =====================================================
    # ADMIN SETTINGS
    # =====================================================

    if data == "admin_settings":
        if uid != ADMIN_ID:
            await query.answer(
                "⛔ دسترسی غیرمجاز",
                show_alert=True
            )
            return

        await query.message.edit_text(
            "⚙️ تنظیمات ربات\n\n"
            "🕐 ساعات فعالیت:\n"
            "07:00 تا 23:00\n\n"
            "💳 سیستم پرداخت:\n"
            "فعال\n\n"
            "🔎 تأیید پرداخت:\n"
            "دستی توسط مدیریت",
            reply_markup=InlineKeyboardMarkup(
                [[
                    InlineKeyboardButton(
                        "🔙 پنل مدیریت",
                        callback_data="admin_panel"
                    )
                ]]
            )
        )
        return# =========================================================
# TEXT HANDLER
# =========================================================

async def text_handler(update, context):
    user = update.effective_user
    uid = user.id
    text = (update.message.text or "").strip()

    save_user(user)

    # -----------------------------------------------------
    # CHECK BOT HOURS
    # -----------------------------------------------------

    if is_bot_closed() and uid != ADMIN_ID:
        await update.message.reply_text(
            closed_text()
        )
        return

    state_data = USER_STATES.get(uid)

    if not state_data:
        await update.message.reply_text(
            "❌ لطفاً از منوی اصلی یک گزینه را انتخاب کنید.",
            reply_markup=main_keyboard(uid)
        )
        return

    state = state_data.get("state")

    # =====================================================
    # ADMIN PAYMENT AMOUNT
    # =====================================================

    if state == STATE_ADMIN_PAYMENT_AMOUNT:

        if uid != ADMIN_ID:
            USER_STATES.pop(uid, None)

            await update.message.reply_text(
                "⛔ دسترسی غیرمجاز.",
                reply_markup=main_keyboard(uid)
            )
            return

        code = state_data.get("request_code")

        request = get_request(code)

        if not request:
            USER_STATES.pop(uid, None)

            await update.message.reply_text(
                "❌ درخواست پیدا نشد.",
                reply_markup=admin_keyboard()
            )
            return

        # حذف جداکننده‌های رایج عدد
        clean_amount = (
            text
            .replace(",", "")
            .replace("٬", "")
            .replace(" ", "")
        )

        if not clean_amount.isdigit():
            await update.message.reply_text(
                "❌ مبلغ نامعتبر است.\n\n"
                "لطفاً فقط عدد وارد کنید.\n\n"
                "مثال:\n"
                "1500000"
            )
            return

        amount = int(clean_amount)

        if amount <= 0:
            await update.message.reply_text(
                "❌ مبلغ باید بیشتر از صفر باشد.\n\n"
                "مثال:\n"
                "1500000"
            )
            return

        # ذخیره مشخصات پرداخت
        set_payment_request(
            code,
            amount
        )

        USER_STATES.pop(uid, None)

        # -------------------------------------------------
        # PAYMENT MESSAGE FOR USER
        # -------------------------------------------------

        payment_text = (
            "💳 مشخصات پرداخت\n\n"
            f"🎫 کد درخواست: {code}\n\n"
            f"💰 مبلغ قابل پرداخت:\n"
            f"{format_amount(amount)} ریال\n\n"
            f"💳 شماره کارت:\n"
            f"{PAYMENT_CARD_NUMBER}\n\n"
            f"👤 به نام:\n"
            f"{PAYMENT_CARD_NAME}\n\n"
            "📌 لطفاً مبلغ دقیق را به شماره کارت بالا "
            "واریز کنید.\n\n"
            "⚠️ پس از پرداخت، تصویر یا فایل رسید را "
            "از طریق دکمه زیر ارسال کنید.\n\n"
            "🔎 پرداخت پس از بررسی مدیریت تأیید خواهد شد."
        )

        try:
            await context.bot.send_message(
                chat_id=request["user_id"],
                text=payment_text,
                reply_markup=InlineKeyboardMarkup(
                    [[
                        InlineKeyboardButton(
                            "📤 ارسال رسید پرداخت",
                            callback_data=f"send_receipt|{code}"
                        )
                    ]]
                )
            )

            await update.message.reply_text(
                "✅ مشخصات پرداخت برای کاربر ارسال شد.\n\n"
                f"🎫 کد درخواست: {code}\n"
                f"💰 مبلغ: {format_amount(amount)} ریال",
                reply_markup=status_keyboard(code)
            )

        except Exception:
            logger.exception(
                "Could not send payment details to user"
            )

            await update.message.reply_text(
                "⚠️ مبلغ ذخیره شد، اما ارسال پیام پرداخت "
                "برای کاربر با خطا مواجه شد.\n\n"
                "لطفاً دوباره بررسی کنید.",
                reply_markup=status_keyboard(code)
            )

        return

    # =====================================================
    # USER NAME
    # =====================================================

    if state == STATE_NAME:

        if len(text) < 3:
            await update.message.reply_text(
                "❌ لطفاً نام و نام خانوادگی معتبر وارد کنید."
            )
            return

        state_data["full_name"] = text
        state_data["state"] = STATE_PHONE

        USER_STATES[uid] = state_data

        await update.message.reply_text(
            "📱 لطفاً شماره موبایل خود را ارسال کنید:"
        )

        return

    # =====================================================
    # USER PHONE
    # =====================================================

    if state == STATE_PHONE:

        phone = (
            text
            .replace(" ", "")
            .replace("-", "")
        )

        if phone.startswith("+98"):
            phone = "0" + phone[3:]

        if not phone.isdigit() or len(phone) != 11:
            await update.message.reply_text(
                "❌ شماره موبایل معتبر نیست.\n\n"
                "مثال:\n"
                "09123456789"
            )
            return

        state_data["phone"] = phone
        state_data["state"] = STATE_TELEGRAM

        USER_STATES[uid] = state_data

        await update.message.reply_text(
            "💬 آیدی تلگرام خود را ارسال کنید.\n\n"
            "اگر آیدی ندارید، عبارت «ندارم» را ارسال کنید."
        )

        return

    # =====================================================
    # TELEGRAM ID
    # =====================================================

    if state == STATE_TELEGRAM:

        telegram_id = text

        if telegram_id == "ندارم":
            telegram_id = ""

        state_data["telegram_id"] = telegram_id
        state_data["state"] = STATE_DESCRIPTION

        USER_STATES[uid] = state_data

        await update.message.reply_text(
            "📝 اگر توضیحی درباره درخواست دارید ارسال کنید.\n\n"
            "در غیر این صورت «ندارم» را ارسال کنید."
        )

        return

    # =====================================================
    # DESCRIPTION
    # =====================================================

    if state == STATE_DESCRIPTION:

        description = text

        if description == "ندارم":
            description = ""

        category = state_data.get(
            "category",
            ""
        )

        service = state_data.get(
            "service",
            ""
        )

        full_name = state_data.get(
            "full_name",
            ""
        )

        phone = state_data.get(
            "phone",
            ""
        )

        telegram_id = state_data.get(
            "telegram_id",
            ""
        )

        # ثبت درخواست
        code = create_request(
            user_id=uid,
            username=user.username or "",
            full_name=full_name,
            phone=phone,
            telegram_id=telegram_id,
            description=description,
            category=category,
            service=service,
        )

        USER_STATES.pop(uid, None)

        await update.message.reply_text(
            "✅ درخواست شما با موفقیت ثبت شد.\n\n"
            f"🎫 کد پیگیری:\n"
            f"{code}\n\n"
            "📌 کد پیگیری را برای پیگیری درخواست خود نگه دارید.\n\n"
            "⏳ درخواست شما ابتدا توسط مدیریت بررسی می‌شود.",
            reply_markup=main_keyboard(uid)
        )

        # اطلاع به مدیریت
        request = get_request(code)

        admin_text = (
            "📥 درخواست جدید\n\n"
            f"🎫 کد پیگیری: {code}\n"
            f"👤 نام: {request['full_name']}\n"
            f"📱 موبایل: {request['phone']}\n"
            f"💬 تلگرام: {request['telegram_id'] or 'ندارد'}\n"
            f"📂 دسته‌بندی: {request['category']}\n"
            f"🔧 خدمت: {request['service']}\n\n"
            f"📝 توضیحات:\n"
            f"{request['description'] or 'ندارد'}\n\n"
            f"📌 وضعیت: {request['status']}"
        )

        try:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=admin_text,
                reply_markup=status_keyboard(code)
            )
        except Exception:
            logger.exception(
                "Could not notify admin about new request"
            )

        return

    # =====================================================
    # TRACKING
    # =====================================================

    if state == STATE_TRACKING:

        code = text.upper()

        request = get_request(code)

        if not request:
            await update.message.reply_text(
                "❌ درخواست با این کد پیدا نشد.\n\n"
                "لطفاً کد پیگیری را صحیح وارد کنید."
            )
            return

        if not is_request_owner(
            request,
            uid
        ) and uid != ADMIN_ID:

            await update.message.reply_text(
                "⛔ این درخواست متعلق به حساب شما نیست.",
                reply_markup=main_keyboard(uid)
            )

            USER_STATES.pop(uid, None)

            return

        USER_STATES.pop(uid, None)

        await update.message.reply_text(
            format_request(request),
            reply_markup=main_keyboard(uid)
        )

        return

    # =====================================================
    # ADMIN SEARCH
    # =====================================================

    if state == STATE_ADMIN_SEARCH:

        if uid != ADMIN_ID:
            USER_STATES.pop(uid, None)
            return

        search_value = text

        conn = get_db()

        rows = conn.execute(
            """
            SELECT *
            FROM requests
            WHERE tracking_code=?
               OR phone=?
               OR full_name LIKE ?
            ORDER BY id DESC
            LIMIT 20
            """,
            (
                search_value,
                search_value,
                f"%{search_value}%",
            ),
        ).fetchall()

        conn.close()

        USER_STATES.pop(uid, None)

        if not rows:
            await update.message.reply_text(
                "❌ هیچ درخواستی پیدا نشد.",
                reply_markup=admin_keyboard()
            )
            return

        buttons = []

        for request in rows:
            buttons.append(
                [
                    InlineKeyboardButton(
                        f"{request['tracking_code']} | "
                        f"{request['full_name']}",
                        callback_data=(
                            f"admin_view|"
                            f"{request['tracking_code']}"
                        )
                    )
                ]
            )

        buttons.append(
            [
                InlineKeyboardButton(
                    "🔙 پنل مدیریت",
                    callback_data="admin_panel"
                )
            ]
        )

        await update.message.reply_text(
            f"🔎 {len(rows)} نتیجه پیدا شد:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

        return

    # =====================================================
    # ADMIN ADD REGISTRATION
    # =====================================================

    if state == STATE_ADMIN_ADD_REG:

        if uid != ADMIN_ID:
            USER_STATES.pop(uid, None)
            return

        if len(text) < 2:
            await update.message.reply_text(
                "❌ عنوان ثبت‌نام معتبر نیست."
            )
            return

        registration_id = add_registration(
            title=text
        )

        USER_STATES.pop(uid, None)

        await update.message.reply_text(
            "✅ ثبت‌نام با موفقیت اضافه شد.\n\n"
            f"📝 {text}\n"
            f"🆔 شناسه: {registration_id}",
            reply_markup=admin_keyboard()
        )

        return

    # =====================================================
    # BROADCAST
    # =====================================================

    if state == STATE_BROADCAST:

        if uid != ADMIN_ID:
            USER_STATES.pop(uid, None)
            return

        USER_STATES.pop(uid, None)

        conn = get_db()

        users = conn.execute(
            "SELECT user_id FROM users"
        ).fetchall()

        conn.close()

        sent = 0
        failed = 0

        await update.message.reply_text(
            "📢 ارسال پیام همگانی شروع شد..."
        )

        for row in users:

            target_id = row["user_id"]

            try:
                await context.bot.send_message(
                    chat_id=target_id,
                    text=text
                )

                sent += 1

            except Exception:
                failed += 1

        await update.message.reply_text(
            "✅ ارسال پیام همگانی انجام شد.\n\n"
            f"📤 ارسال موفق: {sent}\n"
            f"❌ ناموفق: {failed}",
            reply_markup=admin_keyboard()
        )

        return

    # =====================================================
    # SUPPORT MESSAGE
    # =====================================================

    if state == STATE_SUPPORT:

        USER_STATES.pop(uid, None)

        conn = get_db()

        conn.execute(
            """
            INSERT INTO support_messages
            (user_id, message, created_at, replied)
            VALUES (?, ?, ?, 0)
            """,
            (
                uid,
                text,
                now_text(),
            ),
        )

        conn.commit()
        conn.close()

        await update.message.reply_text(
            "✅ پیام شما برای پشتیبانی ارسال شد.\n\n"
            "📞 پس از بررسی، مدیریت با شما ارتباط خواهد گرفت.",
            reply_markup=main_keyboard(uid)
        )

        try:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    "💬 پیام جدید پشتیبانی\n\n"
                    f"👤 نام: {user.full_name}\n"
                    f"🆔 User ID: {uid}\n"
                    f"💬 Username: "
                    f"@{user.username if user.username else 'ندارد'}\n\n"
                    f"📝 پیام:\n{text}"
                )
            )

        except Exception:
            logger.exception(
                "Could not notify admin about support message"
            )

        return

    # =====================================================
    # UNKNOWN STATE
    # =====================================================

    await update.message.reply_text(
        "❌ این مرحله معتبر نیست.\n\n"
        "لطفاً از منوی اصلی دوباره شروع کنید.",
        reply_markup=main_keyboard(uid)
    )

    USER_STATES.pop(uid, None)


# =========================================================
# RECEIPT HANDLER
# =========================================================

async def receipt_handler(update, context):

    user = update.effective_user
    uid = user.id

    save_user(user)

    # -----------------------------------------------------
    # CHECK BOT HOURS
    # -----------------------------------------------------

    if is_bot_closed() and uid != ADMIN_ID:

        await update.message.reply_text(
            closed_text()
        )

        return

    state_data = USER_STATES.get(uid)

    if not state_data:
        return

    if state_data.get("state") != STATE_USER_RECEIPT:
        return

    code = state_data.get(
        "request_code"
    )

    request = get_request(code)

    # -----------------------------------------------------
    # VALIDATE REQUEST
    # -----------------------------------------------------

    if not request:

        USER_STATES.pop(uid, None)

        await update.message.reply_text(
            "❌ درخواست معتبر پیدا نشد.",
            reply_markup=main_keyboard(uid)
        )

        return

    if not is_request_owner(
        request,
        uid
    ):

        USER_STATES.pop(uid, None)

        await update.message.reply_text(
            "⛔ این درخواست متعلق به شما نیست.",
            reply_markup=main_keyboard(uid)
        )

        return

    # -----------------------------------------------------
    # CHECK PAYMENT
    # -----------------------------------------------------

    if not request["payment_amount"]:

        USER_STATES.pop(uid, None)

        await update.message.reply_text(
            "❌ هنوز مبلغ پرداخت برای این درخواست تعیین نشده است.",
            reply_markup=main_keyboard(uid)
        )

        return

    # -----------------------------------------------------
    # GET RECEIPT FILE
    # -----------------------------------------------------

    if update.message.photo:

        file_id = update.message.photo[-1].file_id
        receipt_type = "photo"

    elif update.message.document:

        file_id = update.message.document.file_id
        receipt_type = "document"

    else:

        await update.message.reply_text(
            "❌ لطفاً رسید پرداخت را به صورت "
            "تصویر یا فایل ارسال کنید."
        )

        return

    # -----------------------------------------------------
    # SAVE RECEIPT
    # -----------------------------------------------------

    save_receipt(
        code,
        file_id,
        receipt_type
    )

    USER_STATES.pop(uid, None)

    # -----------------------------------------------------
    # USER CONFIRMATION
    # -----------------------------------------------------

    await update.message.reply_text(
        "✅ رسید پرداخت شما دریافت شد.\n\n"
        f"🎫 کد درخواست: {code}\n"
        f"💰 مبلغ: "
        f"{format_amount(request['payment_amount'])} ریال\n\n"
        "🔎 رسید برای مدیریت ارسال شد.\n"
        "⏳ پس از بررسی حساب بانکی، نتیجه اعلام می‌شود.",
        reply_markup=main_keyboard(uid)
    )

    # -----------------------------------------------------
    # ADMIN MESSAGE
    # -----------------------------------------------------

    admin_text = (
        "💳 رسید پرداخت جدید\n\n"
        f"🎫 کد درخواست: {code}\n"
        f"👤 نام: {request['full_name']}\n"
        f"📱 شماره: {request['phone']}\n"
        f"💬 تلگرام: "
        f"{request['telegram_id'] or 'ندارد'}\n"
        f"🔧 خدمت: {request['service']}\n\n"
        f"💰 مبلغ: "
        f"{format_amount(request['payment_amount'])} ریال\n\n"
        "🔎 لطفاً ابتدا حساب بانکی را بررسی کنید.\n"
        "سپس نتیجه را انتخاب کنید:"
    )

    keyboard = InlineKeyboardMarkup(
        [[
            InlineKeyboardButton(
                "✅ تأیید پرداخت",
                callback_data=f"approve_payment|{code}"
            ),
            InlineKeyboardButton(
                "❌ رد رسید",
                callback_data=f"reject_payment|{code}"
            )
        ]]
    )

    try:

        if receipt_type == "photo":

            await context.bot.send_photo(
                chat_id=ADMIN_ID,
                photo=file_id,
                caption=admin_text,
                reply_markup=keyboard
            )

        else:

            await context.bot.send_document(
                chat_id=ADMIN_ID,
                document=file_id,
                caption=admin_text,
                reply_markup=keyboard
            )

    except Exception:

        logger.exception(
            "Could not forward receipt to admin"
        )

        try:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    "⚠️ رسید ثبت شد، اما ارسال فایل "
                    "برای مدیریت با خطا مواجه شد.\n\n"
                    f"🎫 کد درخواست: {code}\n"
                    f"💰 مبلغ: "
                    f"{format_amount(request['payment_amount'])} ریال"
                )
            )

        except Exception:
            logger.exception(
                "Could not send receipt error to admin"
            )


# =========================================================
# COMMAND: /ADMIN
# =========================================================

async def admin_command(update, context):

    user = update.effective_user

    save_user(user)

    if user.id != ADMIN_ID:

        await update.message.reply_text(
            "⛔ دسترسی غیرمجاز."
        )

        return

    USER_STATES.pop(
        user.id,
        None
    )

    await update.message.reply_text(
        admin_panel_text(),
        reply_markup=admin_keyboard()
    )


# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(update, context):

    logger.exception(
        "Unhandled exception:",
        exc_info=context.error
    )

    try:

        if update and update.effective_message:

            await update.effective_message.reply_text(
                "⚠️ خطایی در پردازش درخواست رخ داد.\n"
                "لطفاً دوباره تلاش کنید."
            )

    except Exception:

        logger.exception(
            "Could not send error message"
        )


# =========================================================
# MAIN
# =========================================================

def main():

    logging.basicConfig(
        format=(
            "%(asctime)s - "
            "%(name)s - "
            "%(levelname)s - "
            "%(message)s"
        ),
        level=logging.INFO,
    )

    global logger

    logger = logging.getLogger(__name__)

    # -----------------------------------------------------
    # DATABASE
    # -----------------------------------------------------

    init_db()

    # -----------------------------------------------------
    # APPLICATION
    # -----------------------------------------------------

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # -----------------------------------------------------
    # COMMANDS
    # -----------------------------------------------------

    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    app.add_handler(
        CommandHandler(
            "admin",
            admin_command
        )
    )

    # -----------------------------------------------------
    # CALLBACKS
    # -----------------------------------------------------

    app.add_handler(
        CallbackQueryHandler(
            callback_handler
        )
    )

    # -----------------------------------------------------
    # RECEIPTS
    # IMPORTANT:
    # This must be BEFORE the text handler.
    # -----------------------------------------------------

    app.add_handler(
        MessageHandler(
            filters.PHOTO | filters.Document.ALL,
            receipt_handler
        )
    )

    # -----------------------------------------------------
    # TEXT
    # -----------------------------------------------------

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_handler
        )
    )

    # -----------------------------------------------------
    # ERRORS
    # -----------------------------------------------------

    app.add_error_handler(
        error_handler
    )

    # -----------------------------------------------------
    # RUN BOT
    # -----------------------------------------------------

    logger.info(
        "CafiNetOnline24 bot started."
    )

    app.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


# =========================================================
# START
# =========================================================

if __name__ == "__main__":
    main()
