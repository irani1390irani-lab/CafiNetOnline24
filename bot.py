import os
import sqlite3
import logging
from datetime import datetime, time
from zoneinfo import ZoneInfo

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
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
SUPPORT_USERNAME = "@CafiNetOnlin_Support"

OPEN_HOUR = 7
CLOSE_HOUR = 23

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

    # اضافه کردن ستون دلیل رد شدن در صورت نبودن آن
    try:
        cur.execute(
            "ALTER TABLE requests ADD COLUMN admin_reason TEXT DEFAULT ''"
        )
    except sqlite3.OperationalError:
        pass

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
        INSERT INTO users(user_id, username, full_name, created_at, updated_at)
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

# حالت‌های جدید سایر خدمات
STATE_OTHER_TITLE = "other_title"
STATE_OTHER_DESCRIPTION = "other_description"

# حالت دلیل رد درخواست توسط ادمین
STATE_ADMIN_REJECT_REASON = "admin_reject_reason"


# =========================
# KEYBOARDS FOR INPUT
# =========================
def phone_keyboard():
    return ReplyKeyboardMarkup(
        [
            [
                KeyboardButton(
                    "📱 ارسال شماره همراه",
                    request_contact=True,
                )
            ]
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def telegram_keyboard():
    return ReplyKeyboardMarkup(
        [
            [
                KeyboardButton("⏭ رد کردن")
            ]
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def reject_keyboard(code):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "❌ رد بدون توضیح",
                    callback_data=f"reject_no_reason|{code}",
                )
            ],
            [
                InlineKeyboardButton(
                    "📝 وارد کردن دلیل",
                    callback_data=f"reject_reason|{code}",
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 بازگشت",
                    callback_data=f"admin_view|{code}",
                )
            ],
        ]
    )


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
        (status, now_text(), code),
    )
    conn.commit()
    conn.close()


def update_rejection(code, reason=""):
    conn = get_db()

    conn.execute(
        """
        UPDATE requests
        SET status=?,
            admin_reason=?,
            updated_at=?
        WHERE tracking_code=?
        """,
        (
            "🔴 رد شد",
            reason,
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
        (user_id, limit),
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
# REGISTRATION FUNCTIONS
# =========================
def add_registration(title):
    conn = get_db()
    conn.execute(
        """
        INSERT INTO registrations(
            title, registration_date, active, created_at
        )
        VALUES(?,?,1,?)
        """,
        (title, today_text(), now_text()),
    )
    conn.commit()
    conn.close()


def get_today_registrations():
    conn = get_db()
    rows = conn.execute(
        """
        SELECT *
        FROM registrations
        WHERE registration_date=? AND active=1
        ORDER BY id ASC
        """,
        (today_text(),),
    ).fetchall()
    conn.close()
    return rows


def get_registration(reg_id):
    conn = get_db()
    row = conn.execute(
        """
        SELECT *
        FROM registrations
        WHERE id=? AND active=1
        """,
        (reg_id,),
    ).fetchone()
    conn.close()
    return row


def deactivate_registration(reg_id):
    conn = get_db()
    conn.execute(
        "UPDATE registrations SET active=0 WHERE id=?",
        (reg_id,),
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
        LIMIT 50
        """
    ).fetchall()
    conn.close()
    return rows


# =========================
# KEYBOARDS
# =========================
def main_keyboard(user_id=None):
    buttons = [
        [
            InlineKeyboardButton(
                "📝 ثبت‌نام‌های آنلاین",
                callback_data="online_regs",
            )
        ],
        [
            InlineKeyboardButton("🚗 خودرو", callback_data="service|vehicle"),
            InlineKeyboardButton("🛡 بیمه", callback_data="service|insurance"),
        ],
        [
            InlineKeyboardButton("💰 مالیاتی", callback_data="service|tax"),
            InlineKeyboardButton("⚖️ قضایی", callback_data="service|judicial"),
        ],
        [
            InlineKeyboardButton("🏦 بانکی", callback_data="service|bank"),
            InlineKeyboardButton("💵 وام", callback_data="service|loan"),
        ],
        [
            InlineKeyboardButton(
                "🧩 سایر خدمات",
                callback_data="other_services",
            )
        ],
        [
            InlineKeyboardButton("🔎 پیگیری درخواست", callback_data="tracking"),
        ],
        [
            InlineKeyboardButton("📋 درخواست‌های من", callback_data="my_requests"),
        ],
        [
            InlineKeyboardButton("💬 پشتیبانی", url="https://t.me/CafiNetOnlin_Support"),
            InlineKeyboardButton("ℹ️ درباره ما", callback_data="about"),
        ],
    ]

    if user_id == ADMIN_ID:
        buttons.append(
            [
                InlineKeyboardButton(
                    "🛠 پنل مدیریت",
                    callback_data="admin_panel",
                )
            ]
        )

    return InlineKeyboardMarkup(buttons)


def admin_keyboard():
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "📋 درخواست‌های جدید",
                    callback_data="admin_requests",
                )
            ],
            [
                InlineKeyboardButton(
                    "🔎 جستجوی درخواست",
                    callback_data="admin_search",
                )
            ],
            [
                InlineKeyboardButton(
                    "📝 افزودن ثبت‌نام امروز",
                    callback_data="admin_add_reg",
                )
            ],
            [
                InlineKeyboardButton(
                    "📑 لیست ثبت‌نام‌ها",
                    callback_data="admin_regs",
                )
            ],
            [
                InlineKeyboardButton(
                    "📊 آمار ربات",
                    callback_data="stats",
                )
            ],
            [
                InlineKeyboardButton(
                    "📢 ارسال پیام همگانی",
                    callback_data="broadcast",
                )
            ],
            [
                InlineKeyboardButton(
                    "⚙️ تنظیمات",
                    callback_data="settings",
                )
            ],
            [
                InlineKeyboardButton(
                    "🏠 منوی اصلی",
                    callback_data="home",
                )
            ],
        ]
    )


def home_keyboard():
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🏠 منوی اصلی",
                    callback_data="home",
                )
            ]
        ]
    )


def registrations_keyboard():
    rows = []

    for item in get_today_registrations():
        rows.append(
            [
                InlineKeyboardButton(
                    "📝 " + item["title"],
                    callback_data=f"reg|{item['id']}",
                )
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(
                "➕ سایر ثبت‌نام‌ها",
                callback_data="other_reg",
            )
        ]
    )

    rows.append(
        [
            InlineKeyboardButton(
                "🏠 بازگشت",
                callback_data="home",
            )
        ]
    )

    return InlineKeyboardMarkup(rows)


def status_keyboard(code):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🟢 پذیرفتن درخواست",
                    callback_data=f"accept|{code}",
                )
            ],
            [
                InlineKeyboardButton(
                    "🔵 در حال انجام",
                    callback_data=f"doing|{code}",
                )
            ],
            [
                InlineKeyboardButton(
                    "🟢 انجام شد",
                    callback_data=f"done|{code}",
                )
            ],
            [
                InlineKeyboardButton(
                    "🔴 رد شد",
                    callback_data=f"reject|{code}",
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 پنل مدیریت",
                    callback_data="admin_panel",
                )
            ],
        ]
    )


# =========================
# ONLINE REGISTRATION MENU
# =========================
def online_categories_keyboard():
    return registrations_keyboard()


# =========================
# MAIN SERVICE CATEGORIES
# =========================
SERVICE_CATEGORIES = {
    "vehicle": ("🚗 خدمات خودرو", [
        "🚘 ثبت‌نام ایران‌خودرو",
        "🚘 ثبت‌نام سایپا",
        "♻️ ثبت‌نام خودروهای فرسوده",
        "📋 نوبت تعویض پلاک",
        "🏍️ تعویض پلاک موتورسیکلت",
        "⛽ خدمات کارت سوخت",
        "💳 استعلام و پرداخت خلافی",
        "🚗 سایر خدمات خودرو",
    ]),
    "insurance": ("🛡️ خدمات بیمه", [
        "🚗 بیمه شخص ثالث",
        "🚘 بیمه بدنه",
        "🏥 بیمه درمان",
        "👤 بیمه تأمین اجتماعی",
        "📄 سوابق بیمه",
        "💳 فیش بیمه",
        "🏃 بیمه ورزشی",
        "🛡️ سایر خدمات بیمه",
    ]),
    "tax": ("💰 خدمات مالی و مالیاتی", [
        "🧾 تشکیل پرونده مالیاتی",
        "🔢 دریافت کد مالیاتی",
        "📄 اظهارنامه مالیاتی",
        "💳 پرداخت مالیات",
        "⚖️ اعتراض مالیاتی",
        "📨 دریافت ابلاغیه مالیاتی",
        "📊 خدمات مالیاتی",
    ]),
    "judicial": ("⚖️ خدمات قضایی", [
        "🪪 ثبت‌نام و احراز هویت ثنا",
        "📄 گواهی عدم سوءپیشینه",
        "📨 دریافت ابلاغیه قضایی",
        "🏛️ نوبت‌دهی قضایی",
        "⚖️ ثبت دادخواست",
        "👮 سامانه سخا",
        "⚖️ سایر خدمات قضایی",
    ]),
    "bank": ("🏦 خدمات بانکی", [
        "📝 ثبت چک صیادی",
        "🔎 استعلام چک",
        "🔄 انتقال چک",
        "🏦 افتتاح حساب",
        "💳 خدمات کارت بانکی",
        "🔢 دریافت شماره شبا",
        "📄 دریافت گواهی بانکی",
        "🏦 سایر خدمات بانکی",
    ]),
    "loan": ("💵 خدمات وام و تسهیلات", [
        "💍 ثبت‌نام وام ازدواج",
        "👶 ثبت‌نام وام فرزندآوری",
        "🏠 وام ودیعه مسکن",
        "🏡 وام مسکن",
        "💼 وام اشتغال",
        "💰 سایر تسهیلات حمایتی",
    ]),
}


def service_category_keyboard(category_key):
    title, services = SERVICE_CATEGORIES[category_key]
    rows = []

    for index, service in enumerate(services):
        rows.append([
            InlineKeyboardButton(
                service,
                callback_data=f"service_item|{category_key}|{index}",
            )
        ])

    rows.append([
        InlineKeyboardButton("🔙 منوی اصلی", callback_data="home")
    ])

    return InlineKeyboardMarkup(rows)


async def show_main_service_category(query, category_key):
    if category_key not in SERVICE_CATEGORIES:
        await query.answer("این بخش موجود نیست.", show_alert=True)
        return

    title, services = SERVICE_CATEGORIES[category_key]

    await query.edit_message_text(
        f"{title}\n\n"
        "خدمت موردنظر را انتخاب کنید:",
        reply_markup=service_category_keyboard(category_key),
    )


async def select_main_service(query, category_key, service_index):
    if category_key not in SERVICE_CATEGORIES:
        await query.answer("این بخش موجود نیست.", show_alert=True)
        return

    title, services = SERVICE_CATEGORIES[category_key]

    try:
        service = services[service_index]
    except (IndexError, TypeError):
        await query.answer("این خدمت موجود نیست.", show_alert=True)
        return

    await query.edit_message_text(
        f"{service}\n\n"
        f"📂 دسته: {title}\n\n"
        "برای ثبت درخواست این خدمت، دکمه زیر را بزنید.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "📨 ثبت درخواست این خدمت",
                callback_data=f"service_start|{category_key}|{service_index}",
            )],
            [InlineKeyboardButton(
                "🔙 بازگشت به خدمات",
                callback_data=f"service|{category_key}",
            )],
            [InlineKeyboardButton(
                "🏠 منوی اصلی",
                callback_data="home",
            )],
        ]),
    )


async def start_main_service_request(query, category_key, service_index):
    if category_key not in SERVICE_CATEGORIES:
        await query.answer("این بخش موجود نیست.", show_alert=True)
        return

    title, services = SERVICE_CATEGORIES[category_key]

    try:
        service = services[service_index]
    except (IndexError, TypeError):
        await query.answer("این خدمت موجود نیست.", show_alert=True)
        return

    await begin_request(query, title, service)


def format_request_details(request):
    reason = ""
    try:
        reason = request["admin_reason"] or ""
    except (IndexError, KeyError):
        reason = ""

    result = (
        "📋 جزئیات درخواست\n\n"
        f"🎫 کد رهگیری: {request['tracking_code']}\n"
        f"📂 دسته: {request['category']}\n"
        f"🔧 خدمت: {request['service']}\n"
        f"👤 نام: {request['full_name']}\n"
        f"📱 شماره: {request['phone']}\n"
        f"🆔 تلگرام: {request['telegram_id'] or 'ثبت نشده'}\n"
        f"📝 توضیحات: {request['description'] or 'بدون توضیح'}\n\n"
        f"📌 وضعیت: {request['status']}\n"
        f"🕐 زمان ثبت: {request['created_at']}\n"
        f"🔄 آخرین بروزرسانی: {request['updated_at']}"
    )

    if reason:
        result += f"\n\n📝 دلیل رد:\n{reason}"

    return result


async def send_request_details(chat_id, request, context, include_home=True):
    await context.bot.send_message(
        chat_id=chat_id,
        text=format_request_details(request),
        reply_markup=home_keyboard() if include_home else None,
    )


async def begin_request(query, category, service):
    USER_STATES[query.from_user.id] = {
        "state": STATE_NAME,
        "category": category,
        "service": service,
        "other_service": False,
    }

    await query.edit_message_text(
        f"📝 ثبت درخواست\n\n"
        f"📂 دسته: {category}\n"
        f"🔧 خدمت: {service}\n\n"
        "👤 لطفاً نام و نام خانوادگی خود را ارسال کنید:"
    )


# =========================
# OTHER SERVICES
# =========================
async def start_other_services(query):
    USER_STATES[query.from_user.id] = {
        "state": STATE_OTHER_TITLE,
        "category": "🧩 سایر خدمات",
        "service": "",
        "other_service": True,
    }

    await query.edit_message_text(
        "🧩 سایر خدمات\n\n"
        "اگر خدمت موردنظر شما در منو وجود ندارد، می‌توانید درخواست خود را ثبت کنید.\n\n"
        "📝 لطفاً عنوان خدمت موردنظر را ارسال کنید:"
    )


async def show_other_summary(update, state):
    telegram_id = state.get("telegram_id", "")

    await update.message.reply_text(
        "📋 بررسی اطلاعات درخواست\n\n"
        f"🧩 عنوان خدمت:\n{state.get('service', '')}\n\n"
        f"📄 توضیحات:\n{state.get('description', '') or 'بدون توضیح'}\n\n"
        f"👤 نام و نام خانوادگی:\n{state.get('full_name', '')}\n\n"
        f"📱 شماره همراه:\n{state.get('phone', '')}\n\n"
        f"🆔 آیدی تلگرام:\n{telegram_id or 'ثبت نشده'}\n\n"
        "آیا اطلاعات بالا صحیح است؟",
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "✅ تأیید",
                        callback_data="other_confirm",
                    ),
                    InlineKeyboardButton(
                        "❌ لغو",
                        callback_data="other_cancel",
                    ),
                ]
            ]
        ),
    )


async def create_other_request(update, context):
    user = update.effective_user
    uid = user.id
    state = USER_STATES.get(uid)

    if not state:
        return

    request = create_request(
        user_id=uid,
        username=user.username or "",
        full_name=state.get("full_name", ""),
        phone=state.get("phone", ""),
        telegram_id=state.get("telegram_id", ""),
        description=state.get("description", ""),
        category=state.get("category", "🧩 سایر خدمات"),
        service=state.get("service", ""),
    )

    USER_STATES.pop(uid, None)

    await context.bot.send_message(
        uid,
        "✅ درخواست شما با موفقیت ثبت شد.\n\n"
        "📩 درخواست شما برای پشتیبانی ارسال شد.\n"
        "⏳ لطفاً منتظر پیام پشتیبانی باشید.\n\n"
        f"🆔 پشتیبانی:\n{SUPPORT_USERNAME}\n\n"
        "⚠️ لطفاً به پشتیبانی پیام ندهید؛\n"
        "پشتیبانی پس از بررسی درخواست، خودش با شما ارتباط خواهد گرفت.\n\n"
        f"🎫 کد پیگیری: {request['tracking_code']}",
        reply_markup=home_keyboard(),
    )

    try:
        await context.bot.send_message(
            ADMIN_ID,
            "🔔 درخواست جدید ثبت شد.\n\n"
            f"🎫 {request['tracking_code']}\n"
            f"📂 دسته: {request['category']}\n"
            f"🔧 خدمت: {request['service']}\n"
            f"👤 نام: {request['full_name']}\n"
            f"📱 شماره: {request['phone']}\n"
            f"🆔 تلگرام: {request['telegram_id'] or 'ثبت نشده'}\n"
            f"📝 توضیحات:\n{request['description'] or 'بدون توضیح'}\n\n"
            "برای مدیریت درخواست از پنل مدیریت استفاده کنید.",
        )
    except Exception:
        logger.exception("Could not notify admin about other service request")


# =========================
# START
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_user(user)
    USER_STATES.pop(user.id, None)

    if is_bot_closed() and user.id != ADMIN_ID:
        await update.message.reply_text(closed_text())
        return

    await update.message.reply_text(
        "🌐 کافی‌نت آنلاین ۲۴\n"
        "به سامانه هوشمند خدمات آنلاین خوش آمدید.\n\n"
        "📌 خدمت موردنظر خود را انتخاب کنید:",
        reply_markup=main_keyboard(user.id),
    )


# =========================
# ABOUT
# =========================
async def about_page(query):
    await query.edit_message_text(
        "ℹ️ درباره ما\n\n"
        "🖥️ کافی‌نت آنلاین ۲۴\n\n"
        "ارائه خدمات و ثبت درخواست‌های آنلاین به‌صورت غیرحضوری.\n\n"
        f"📩 پشتیبانی:\n{SUPPORT_USERNAME}\n\n"
        f"📢 کانال رسمی:\n{CHANNEL_LINK}\n\n"
        f"🤖 ربات خدمات:\n{BOT_LINK}\n\n"
        "⏰ ساعات فعالیت:\n"
        "هر روز از ۰۷:۰۰ تا ۲۳:۰۰\n\n"
        "⚠️ برای پیگیری درخواست، لطفاً منتظر پیام پشتیبانی باشید.",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "💬 ارتباط با پشتیبانی",
                    url="https://t.me/CafiNetOnlin_Support"
                )
            ],
            [
                InlineKeyboardButton(
                    "🏠 منوی اصلی",
                    callback_data="home"
                )
            ],
        ]),
    )


# =========================
# ONLINE REGISTRATIONS
# =========================
async def show_online_registrations(query):
    registrations = get_today_registrations()

    if registrations:
        text = "📝 ثبت‌نام‌های آنلاین\n\nثبت‌نام موردنظر را انتخاب کنید:"
    else:
        text = (
            "📝 ثبت‌نام‌های آنلاین\n\n"
            "فعلاً ثبت‌نامی برای امروز ثبت نشده است.\n\n"
            "برای افزودن ثبت‌نام، از پنل مدیریت استفاده کنید."
        )

    await query.edit_message_text(text, reply_markup=registrations_keyboard())


async def show_today_registrations(query):
    registrations = get_today_registrations()

    if registrations:
        text = "📅 ثبت‌نام‌های ویژه امروز\n\nثبت‌نام موردنظر را انتخاب کنید:"
    else:
        text = (
            "📅 ثبت‌نام‌های ویژه امروز\n\n"
            "فعلاً ثبت‌نام ویژه‌ای برای امروز ثبت نشده است.\n\n"
            "از دسته‌بندی‌های بالا می‌توانید خدمت موردنظر را انتخاب کنید."
        )

    await query.edit_message_text(text, reply_markup=registrations_keyboard())


async def select_registration(query, reg_id):
    registration = get_registration(reg_id)
    if not registration:
        await query.answer("این ثبت‌نام فعال نیست.", show_alert=True)
        return

    USER_STATES[query.from_user.id] = {
        "state": STATE_NAME,
        "category": "📅 ثبت‌نام‌های ویژه امروز",
        "service": registration["title"],
        "other_service": False,
    }

    await query.edit_message_text(
        f"📝 ثبت‌نام: {registration['title']}\n\n"
        "👤 لطفاً نام و نام خانوادگی خود را ارسال کنید:"
    )


async def other_registration(query):
    USER_STATES[query.from_user.id] = {
        "state": STATE_NAME,
        "category": "📝 سایر ثبت‌نام‌ها",
        "service": "➕ سایر ثبت‌نام‌ها",
        "other_service": False,
    }

    await query.edit_message_text(
        "➕ سایر ثبت‌نام‌ها\n\n"
        "ثبت‌نام موردنظر شما در فهرست نیست.\n\n"
        "👤 لطفاً نام و نام خانوادگی خود را ارسال کنید:"
    )


# =========================
# CALLBACK HANDLER
# =========================
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = query.from_user
    save_user(user)

    user_id = user.id
    data = query.data or ""

    if (
        is_bot_closed()
        and user_id != ADMIN_ID
        and data not in ("about",)
    ):
        await query.edit_message_text(
            closed_text(),
            reply_markup=home_keyboard(),
        )
        return

    # HOME
    if data == "home":
        USER_STATES.pop(user_id, None)
        await query.edit_message_text(
            "🌐 منوی اصلی کافی‌نت آنلاین ۲۴\n\n"
            "📌 خدمت موردنظر خود را انتخاب کنید:",
            reply_markup=main_keyboard(user_id),
        )
        return

    # ABOUT
    if data == "about":
        await about_page(query)
        return

    # OTHER SERVICES
    if data == "other_services":
        await start_other_services(query)
        return

    if data == "other_cancel":
        USER_STATES.pop(user_id, None)

        await query.edit_message_text(
            "❌ ثبت درخواست لغو شد.",
            reply_markup=main_keyboard(user_id),
        )
        return

    if data == "other_confirm":
        if user_id not in USER_STATES:
            await query.answer(
                "اطلاعات درخواست پیدا نشد.",
                show_alert=True,
            )
            return

        state = USER_STATES[user_id]

        if not state.get("other_service"):
            await query.answer(
                "درخواست نامعتبر است.",
                show_alert=True,
            )
            return

        await create_other_request(update, context)
        return

    # ONLINE REGISTRATION CATALOGUE
    if data == "online_regs":
        await show_online_registrations(query)
        return

    if data.startswith("online_cat|"):
        category_key = data.split("|", 1)[1]
        await show_online_category(query, category_key)
        return

    if data.startswith("online_service|"):
        parts = data.split("|")
        if len(parts) != 3:
            await query.answer("درخواست نامعتبر است.", show_alert=True)
            return
        try:
            service_index = int(parts[2])
        except ValueError:
            await query.answer("شناسه خدمت نامعتبر است.", show_alert=True)
            return
        await select_online_service(query, parts[1], service_index)
        return

    if data.startswith("online_start|"):
        parts = data.split("|")
        if len(parts) != 3:
            await query.answer("درخواست نامعتبر است.", show_alert=True)
            return
        try:
            service_index = int(parts[2])
        except ValueError:
            await query.answer("شناسه خدمت نامعتبر است.", show_alert=True)
            return
        await start_online_service_request(query, parts[1], service_index)
        return

    if data == "today_regs":
        await show_today_registrations(query)
        return

    if data.startswith("reg|"):
        try:
            reg_id = int(data.split("|", 1)[1])
        except ValueError:
            await query.answer("شناسه نامعتبر است.", show_alert=True)
            return
        await select_registration(query, reg_id)
        return

    if data == "other_reg":
        await other_registration(query)
        return

    # MAIN SERVICE CATEGORIES
    if data.startswith("service_start|"):
        parts = data.split("|")
        if len(parts) != 3:
            await query.answer("درخواست نامعتبر است.", show_alert=True)
            return
        try:
            service_index = int(parts[2])
        except ValueError:
            await query.answer("شناسه خدمت نامعتبر است.", show_alert=True)
            return
        await start_main_service_request(query, parts[1], service_index)
        return

    if data.startswith("service_item|"):
        parts = data.split("|")
        if len(parts) != 3:
            await query.answer("درخواست نامعتبر است.", show_alert=True)
            return
        try:
            service_index = int(parts[2])
        except ValueError:
            await query.answer("شناسه خدمت نامعتبر است.", show_alert=True)
            return
        await select_main_service(query, parts[1], service_index)
        return

    if data.startswith("service|"):
        category_key = data.split("|", 1)[1]
        if category_key not in SERVICE_CATEGORIES:
            await query.answer("این بخش موجود نیست.", show_alert=True)
            return
        await show_main_service_category(query, category_key)
        return

    # TRACKING
    if data == "tracking":
        USER_STATES[user_id] = {"state": STATE_TRACKING}

        await query.edit_message_text(
            "🔎 پیگیری درخواست\n\n"
            "کد رهگیری خود را ارسال کنید:\n\n"
            "مثال: CF10001"
        )
        return

    # MY REQUESTS
    if data == "my_requests":
        rows = get_user_requests(user_id)

        if not rows:
            await query.edit_message_text(
                "📋 درخواست‌های من\n\n"
                "هنوز درخواستی برای شما ثبت نشده است.",
                reply_markup=home_keyboard(),
            )
            return

        buttons = []
        text = "📋 درخواست‌های من\n\n"

        for row in rows:
            text += (
                f"🎫 {row['tracking_code']} | "
                f"{row['service']}\n"
                f"📌 {row['status']}\n\n"
            )
            buttons.append(
                [
                    InlineKeyboardButton(
                        row["tracking_code"],
                        callback_data=f"my_request|{row['tracking_code']}",
                    )
                ]
            )

        buttons.append(
            [
                InlineKeyboardButton(
                    "🏠 منوی اصلی",
                    callback_data="home",
                )
            ]
        )

        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        return

    if data.startswith("my_request|"):
        code = data.split("|", 1)[1]
        request = get_request(code)

        if not request or request["user_id"] != user_id:
            await query.answer(
                "این درخواست متعلق به شما نیست.",
                show_alert=True,
            )
            return

        await query.edit_message_text(
            format_request_details(request),
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🔙 درخواست‌های من",
                            callback_data="my_requests",
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "🏠 منوی اصلی",
                            callback_data="home",
                        )
                    ],
                ]
            ),
        )
        return

    # SUPPORT
    if data == "support":
        USER_STATES[user_id] = {"state": STATE_SUPPORT}

        await query.edit_message_text(
            "💬 پشتیبانی کافی‌نت آنلاین ۲۴\n\n"
            "پیام خود را ارسال کنید تا برای پشتیبانی فرستاده شود.\n"
            "لطفاً موضوع درخواست را هم در پیام بنویسید."
        )
        return

    # ADMIN PANEL
    if data == "admin_panel":
        if user_id != ADMIN_ID:
            return

        USER_STATES.pop(user_id, None)

        await query.edit_message_text(
            "🛠 پنل مدیریت کافی‌نت آنلاین ۲۴\n\n"
            "بخش موردنظر را انتخاب کنید:",
            reply_markup=admin_keyboard(),
        )
        return

    # ADMIN ADD REG
    if data == "admin_add_reg":
        if user_id != ADMIN_ID:
            return

        USER_STATES[user_id] = {"state": STATE_ADMIN_ADD_REG}

        await query.edit_message_text(
            "📝 افزودن ثبت‌نام امروز\n\n"
            "نام ثبت‌نام را ارسال کنید:"
        )
        return

    # ADMIN SEARCH
    if data == "admin_search":
        if user_id != ADMIN_ID:
            return

        USER_STATES[user_id] = {"state": STATE_ADMIN_SEARCH}

        await query.edit_message_text(
            "🔎 جستجوی درخواست\n\n"
            "کد رهگیری را ارسال کنید:\n"
            "مثال: CF10001"
        )
        return

    # ADMIN REQUEST LIST
    if data == "admin_requests":
        if user_id != ADMIN_ID:
            return

        conn = get_db()
        rows = conn.execute(
            """
            SELECT *
            FROM requests
            ORDER BY id DESC
            LIMIT 10
            """
        ).fetchall()
        conn.close()

        if not rows:
            await query.edit_message_text(
                "📋 درخواستی وجود ندارد.",
                reply_markup=admin_keyboard(),
            )
            return

        text = "📋 آخرین درخواست‌ها:\n\n"
        buttons = []

        for r in rows:
            text += (
                f"🎫 {r['tracking_code']}\n"
                f"🔧 {r['service']}\n"
                f"👤 {r['full_name']}\n"
                f"📌 {r['status']}\n\n"
            )
            buttons.append(
                [
                    InlineKeyboardButton(
                        r["tracking_code"],
                        callback_data=f"admin_view|{r['tracking_code']}",
                    )
                ]
            )

        buttons.append(
            [
                InlineKeyboardButton(
                    "🔙 پنل مدیریت",
                    callback_data="admin_panel",
                )
            ]
        )

        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        return

    # ADMIN VIEW REQUEST
    if data.startswith("admin_view|"):
        if user_id != ADMIN_ID:
            return

        code = data.split("|", 1)[1]
        request = get_request(code)

        if not request:
            await query.edit_message_text(
                "❌ درخواست پیدا نشد.",
                reply_markup=admin_keyboard(),
            )
            return

        await query.edit_message_text(
            format_request_details(request),
            reply_markup=status_keyboard(code),
        )
        return

    # ACCEPT REQUEST
    if data.startswith("accept|"):
        if user_id != ADMIN_ID:
            return

        code = data.split("|", 1)[1]
        request = get_request(code)

        if not request:
            await query.edit_message_text(
                "❌ درخواست پیدا نشد.",
                reply_markup=admin_keyboard(),
            )
            return

        # پذیرفته شدن درخواست = در حال انجام
        update_status(code, "🔵 در حال انجام")
        request = get_request(code)

        try:
            await context.bot.send_message(
                request["user_id"],
                "🟢 درخواست شما توسط پشتیبانی پذیرفته شد.\n\n"
                "⏳ به‌زودی پشتیبانی با شما ارتباط خواهد گرفت.\n\n"
                f"🎫 کد پیگیری: {code}",
            )
        except Exception:
            logger.exception(
                "Could not notify user about accepted request %s",
                code,
            )

        await query.edit_message_text(
            "✅ درخواست پذیرفته شد.\n\n"
            f"🎫 {code}\n"
            "📌 وضعیت: 🔵 در حال انجام",
            reply_markup=admin_keyboard(),
        )
        return

    # REJECT REQUEST MENU
    if data.startswith("reject|"):
        if user_id != ADMIN_ID:
            return

        code = data.split("|", 1)[1]
        request = get_request(code)

        if not request:
            await query.edit_message_text(
                "❌ درخواست پیدا نشد.",
                reply_markup=admin_keyboard(),
            )
            return

        await query.edit_message_text(
            "🔴 رد درخواست\n\n"
            f"🎫 کد پیگیری: {code}\n\n"
            "آیا می‌خواهید دلیل رد برای کاربر ارسال شود؟",
            reply_markup=reject_keyboard(code),
        )
        return

    # REJECT WITHOUT REASON
    if data.startswith("reject_no_reason|"):
        if user_id != ADMIN_ID:
            return

        code = data.split("|", 1)[1]
        request = get_request(code)

        if not request:
            await query.edit_message_text(
                "❌ درخواست پیدا نشد.",
                reply_markup=admin_keyboard(),
            )
            return

        update_rejection(code, "")
        request = get_request(code)

        try:
            await context.bot.send_message(
                request["user_id"],
                "🔴 درخواست شما توسط پشتیبانی رد شد.\n\n"
                f"🎫 کد پیگیری: {code}",
            )
        except Exception:
            logger.exception(
                "Could not notify user about rejected request %s",
                code,
            )

        await query.edit_message_text(
            "✅ درخواست رد شد.\n\n"
            f"🎫 {code}\n"
            "📌 وضعیت: 🔴 رد شد",
            reply_markup=admin_keyboard(),
        )
        return

    # REJECT WITH REASON
    if data.startswith("reject_reason|"):
        if user_id != ADMIN_ID:
            return

        code = data.split("|", 1)[1]
        request = get_request(code)

        if not request:
            await query.edit_message_text(
                "❌ درخواست پیدا نشد.",
                reply_markup=admin_keyboard(),
            )
            return

        USER_STATES[user_id] = {
            "state": STATE_ADMIN_REJECT_REASON,
            "code": code,
        }

        await query.edit_message_text(
            "📝 دلیل رد درخواست\n\n"
            f"🎫 کد پیگیری: {code}\n\n"
            "لطفاً دلیل رد درخواست را ارسال کنید."
        )
        return

    # STATUS CHANGE
    if user_id == ADMIN_ID and "|" in data:
        action, code = data.split("|", 1)

        status_map = {
            "doing": "🔵 در حال انجام",
            "done": "🟢 انجام شد",
        }

        status = status_map.get(action)

        if status:
            request_before = get_request(code)

            if not request_before:
                await query.edit_message_text(
                    "❌ درخواست پیدا نشد.",
                    reply_markup=admin_keyboard(),
                )
                return

            update_status(code, status)
            request = get_request(code)

            try:
                await context.bot.send_message(
                    request["user_id"],
                    "🔔 بروزرسانی درخواست\n\n"
                    f"🎫 کد رهگیری: {code}\n"
                    f"📌 وضعیت جدید: {status}\n\n"
                    "برای مشاهده جزئیات، از گزینه «🔎 پیگیری درخواست» "
                    "استفاده کنید.",
                )
            except Exception:
                logger.exception(
                    "Could not notify user %s",
                    request["user_id"],
                )

            await query.edit_message_text(
                "✅ وضعیت درخواست بروزرسانی شد.\n\n"
                f"🎫 {code}\n"
                f"📌 وضعیت جدید: {status}",
                reply_markup=admin_keyboard(),
            )
            return

    # ADMIN REGISTRATIONS
    if data == "admin_regs":
        if user_id != ADMIN_ID:
            return

        rows = get_all_active_registrations()

        if not rows:
            await query.edit_message_text(
                "📑 ثبت‌نام فعالی وجود ندارد.",
                reply_markup=admin_keyboard(),
            )
            return

        text = "📑 ثبت‌نام‌های فعال:\n\n"
        buttons = []

        for row in rows:
            text += (
                f"📝 {row['title']}\n"
                f"📅 {row['registration_date']}\n\n"
            )
            buttons.append(
                [
                    InlineKeyboardButton(
                        f"❌ حذف {row['title']}",
                        callback_data=f"delreg|{row['id']}",
                    )
                ]
            )

        buttons.append(
            [
                InlineKeyboardButton(
                    "🔙 پنل مدیریت",
                    callback_data="admin_panel",
                )
            ]
        )

        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        return

    # DELETE REGISTRATION
    if data.startswith("delreg|"):
        if user_id != ADMIN_ID:
            return

        try:
            reg_id = int(data.split("|", 1)[1])
        except ValueError:
            return

        deactivate_registration(reg_id)

        await query.edit_message_text(
            "✅ ثبت‌نام غیرفعال شد.",
            reply_markup=admin_keyboard(),
        )
        return

    # STATS
    if data == "stats":
        if user_id != ADMIN_ID:
            return

        s = get_stats()

        await query.edit_message_text(
            "📊 آمار کافی‌نت آنلاین ۲۴\n\n"
            f"👥 کاربران: {s['users']}\n"
            f"📋 کل درخواست‌ها: {s['total']}\n\n"
            f"🟡 در انتظار بررسی: {s['waiting']}\n"
            f"🔵 در حال انجام: {s['doing']}\n"
            f"🟢 انجام‌شده: {s['done']}\n"
            f"🔴 ردشده: {s['rejected']}",
            reply_markup=admin_keyboard(),
        )
        return

    # BROADCAST
    if data == "broadcast":
        if user_id != ADMIN_ID:
            return

        USER_STATES[user_id] = {"state": STATE_BROADCAST}

        await query.edit_message_text(
            "📢 ارسال پیام همگانی\n\n"
            "متن پیام را ارسال کنید.\n"
            "این پیام برای کاربرانی که ربات را شروع کرده‌اند ارسال می‌شود."
        )
        return

    # SETTINGS
    if data == "settings":
        if user_id != ADMIN_ID:
            return

        await query.edit_message_text(
            "⚙️ تنظیمات ربات\n\n"
            "🤖 ساعت فعالیت: ۰۷:۰۰ تا ۲۳:۰۰\n"
            "🌙 ساعت غیرفعال: ۲۳:۰۰ تا ۰۷:۰۰\n\n"
            "برای تغییر تنظیمات اصلی، فایل bot.py یا متغیرهای محیطی "
            "موردنیاز را ویرایش کنید.",
            reply_markup=admin_keyboard(),
        )
        return


# =========================
# CONTACT HANDLER
# =========================
async def contact_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = user.id

    save_user(user)

    if is_bot_closed() and uid != ADMIN_ID:
        await update.message.reply_text(closed_text())
        return

    state = USER_STATES.get(uid)

    if not state or state.get("state") != STATE_PHONE:
        return

    contact = update.message.contact

    # فقط شماره خود کاربر پذیرفته شود
    if contact.user_id and contact.user_id != uid:
        await update.message.reply_text(
            "❌ لطفاً شماره موبایل خودتان را با دکمه ارسال شماره همراه بفرستید."
        )
        return

    state["phone"] = contact.phone_number
    state["state"] = STATE_TELEGRAM
    USER_STATES[uid] = state

    await update.message.reply_text(
        "🆔 آیدی تلگرام خود را ارسال کنید.\n\n"
        "اگر ندارید، روی «⏭ رد کردن» بزنید.",
        reply_markup=telegram_keyboard(),
    )


# =========================
# TEXT HANDLER
# =========================
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = user.id
    text = (update.message.text or "").strip()

    save_user(user)

    state = USER_STATES.get(uid)

    if is_bot_closed() and uid != ADMIN_ID:
        await update.message.reply_text(closed_text())
        return

    if not state:
        return

    current_state = state.get("state")

    # =====================
    # SUPPORT
    # =====================
    if current_state == STATE_SUPPORT:
        USER_STATES.pop(uid, None)

        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO support_messages(user_id, message, created_at, replied)
            VALUES(?,?,?,0)
            """,
            (uid, text, now_text()),
        )
        support_id = cur.lastrowid
        conn.commit()
        conn.close()

        username = f"@{user.username}" if user.username else "بدون یوزرنیم"

        try:
            await context.bot.send_message(
                ADMIN_ID,
                "💬 پیام جدید پشتیبانی\n\n"
                f"🎫 شماره پیام: #{support_id}\n"
                f"👤 کاربر: {user.full_name}\n"
                f"🆔 آیدی عددی: {uid}\n"
                f"📱 یوزرنیم: {username}\n\n"
                f"📝 پیام:\n{text}\n\n"
                "برای پاسخ، می‌توانید از پیام‌رسانی مستقیم با کاربر "
                "در تلگرام استفاده کنید.",
            )
        except Exception:
            logger.exception("Could not send support message to admin")

        await update.message.reply_text(
            "✅ پیام شما برای پشتیبانی ارسال شد.\n\n"
            "در صورت نیاز، پشتیبانی با شما ارتباط می‌گیرد.",
            reply_markup=home_keyboard(),
        )
        return

    # =====================
    # ADMIN ADD REG
    # =====================
    if current_state == STATE_ADMIN_ADD_REG:
        if uid != ADMIN_ID:
            return

        add_registration(text)
        USER_STATES.pop(uid, None)

        await update.message.reply_text(
            "✅ ثبت‌نام اضافه شد.\n\n"
            f"📝 {text}",
            reply_markup=admin_keyboard(),
        )
        return

    # =====================
    # ADMIN SEARCH
    # =====================
    if current_state == STATE_ADMIN_SEARCH:
        if uid != ADMIN_ID:
            return

        request = get_request(text)

        if not request:
            await update.message.reply_text(
                "❌ درخواست پیدا نشد.\n\n"
                "کد رهگیری را مثل CF10001 ارسال کنید."
            )
            return

        USER_STATES.pop(uid, None)

        await update.message.reply_text(
            format_request_details(request),
            reply_markup=status_keyboard(request["tracking_code"]),
        )
        return

    # =====================
    # ADMIN REJECT REASON
    # =====================
    if current_state == STATE_ADMIN_REJECT_REASON:
        if uid != ADMIN_ID:
            return

        code = state.get("code")

        if not code:
            USER_STATES.pop(uid, None)
            await update.message.reply_text(
                "❌ کد درخواست پیدا نشد.",
                reply_markup=admin_keyboard(),
            )
            return

        request = get_request(code)

        if not request:
            USER_STATES.pop(uid, None)
            await update.message.reply_text(
                "❌ درخواست پیدا نشد.",
                reply_markup=admin_keyboard(),
            )
            return

        reason = text

        update_rejection(code, reason)
        request = get_request(code)

        USER_STATES.pop(uid, None)

        try:
            await context.bot.send_message(
                request["user_id"],
                "🔴 درخواست شما توسط پشتیبانی رد شد.\n\n"
                "📝 توضیحات پشتیبانی:\n"
                f"{reason}\n\n"
                f"🎫 کد پیگیری: {code}",
            )
        except Exception:
            logger.exception(
                "Could not notify user about rejected request %s",
                code,
            )

        await update.message.reply_text(
            "✅ درخواست رد شد و دلیل برای کاربر ارسال شد.\n\n"
            f"🎫 {code}",
            reply_markup=admin_keyboard(),
        )
        return

    # =====================
    # TRACKING
    # =====================
    if current_state == STATE_TRACKING:
        request = get_request(text)

        if not request:
            await update.message.reply_text(
                "❌ کد رهگیری اشتباه است.\n"
                "مثال: CF10001"
            )
            return

        if request["user_id"] != uid and uid != ADMIN_ID:
            await update.message.reply_text(
                "❌ این درخواست متعلق به شما نیست."
            )
            return

        USER_STATES.pop(uid, None)

        await send_request_details(
            uid,
            request,
            context,
        )
        return

    # =====================
    # BROADCAST
    # =====================
    if current_state == STATE_BROADCAST:
        if uid != ADMIN_ID:
            return

        USER_STATES.pop(uid, None)

        conn = get_db()
        users = conn.execute(
            "SELECT user_id FROM users"
        ).fetchall()
        conn.close()

        sent = 0
        failed = 0

        for row in users:
            try:
                await context.bot.send_message(
                    row["user_id"],
                    "📢 پیام مدیریت\n\n" + text,
                )
                sent += 1
            except Exception:
                failed += 1

        await update.message.reply_text(
            "✅ پیام همگانی ارسال شد.\n\n"
            f"📨 موفق: {sent}\n"
            f"❌ ناموفق: {failed}",
            reply_markup=admin_keyboard(),
        )
        return

    # =====================
    # OTHER SERVICE TITLE
    # =====================
    if current_state == STATE_OTHER_TITLE:
        if not text:
            await update.message.reply_text(
                "❌ عنوان خدمت نمی‌تواند خالی باشد.\n\n"
                "📝 لطفاً عنوان خدمت را ارسال کنید:"
            )
            return

        state["service"] = text
        state["state"] = STATE_OTHER_DESCRIPTION
        USER_STATES[uid] = state

        await update.message.reply_text(
            "📄 لطفاً توضیحات و شرح درخواست خود را ارسال کنید:"
        )
        return

    # =====================
    # OTHER SERVICE DESCRIPTION
    # =====================
    if current_state == STATE_OTHER_DESCRIPTION:
        if not text:
            await update.message.reply_text(
                "❌ توضیحات نمی‌تواند خالی باشد.\n\n"
                "📄 لطفاً توضیحات درخواست را ارسال کنید:"
            )
            return

        state["description"] = text
        state["state"] = STATE_NAME
        USER_STATES[uid] = state

        await update.message.reply_text(
            "👤 لطفاً نام و نام خانوادگی خود را ارسال کنید:"
        )
        return

    # =====================
    # REQUEST NAME
    # =====================
    if current_state == STATE_NAME:
        if not text:
            await update.message.reply_text(
                "❌ نام و نام خانوادگی نمی‌تواند خالی باشد.\n"
                "لطفاً دوباره ارسال کنید:"
            )
            return

        state["full_name"] = text
        state["state"] = STATE_PHONE
        USER_STATES[uid] = state

        await update.message.reply_text(
            "📱 لطفاً شماره موبایل خود را ارسال کنید.\n\n"
            "می‌توانید شماره را دستی وارد کنید یا روی دکمه "
            "«📱 ارسال شماره همراه» بزنید.",
            reply_markup=phone_keyboard(),
        )
        return

    # =====================
    # REQUEST PHONE
    # =====================
    if current_state == STATE_PHONE:
        cleaned = (
            text
            .replace(" ", "")
            .replace("-", "")
            .replace("(", "")
            .replace(")", "")
        )

        if cleaned.startswith("+"):
            cleaned = cleaned[1:]

        if not cleaned.isdigit() or len(cleaned) < 10:
            await update.message.reply_text(
                "❌ شماره موبایل معتبر نیست.\n"
                "لطفاً دوباره شماره خود را ارسال کنید یا از دکمه "
                "«📱 ارسال شماره همراه» استفاده کنید.",
                reply_markup=phone_keyboard(),
            )
            return

        state["phone"] = text
        state["state"] = STATE_TELEGRAM
        USER_STATES[uid] = state

        await update.message.reply_text(
            "🆔 آیدی تلگرام خود را ارسال کنید.\n\n"
            "اگر ندارید، روی «⏭ رد کردن» بزنید.",
            reply_markup=telegram_keyboard(),
        )
        return

    # =====================
    # REQUEST TELEGRAM ID
    # =====================
    if current_state == STATE_TELEGRAM:
        if text == "⏭ رد کردن" or text == "ندارم":
            state["telegram_id"] = ""
        else:
            state["telegram_id"] = text

        # برای سایر خدمات، بعد از آیدی تلگرام خلاصه و تأیید نمایش داده می‌شود
        if state.get("other_service"):
            USER_STATES[uid] = state

            await update.message.reply_text(
                "⏳ در حال آماده‌سازی اطلاعات درخواست...",
                reply_markup=ReplyKeyboardRemove(),
            )

            await show_other_summary(update, state)
            return

        state["state"] = STATE_DESCRIPTION
        USER_STATES[uid] = state

        await update.message.reply_text(
            "📝 توضیحات درخواست را ارسال کنید.\n\n"
            "اگر توضیح خاصی ندارید، بنویسید: ندارم",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    # =====================
    # REQUEST DESCRIPTION
    # =====================
    if current_state == STATE_DESCRIPTION:
        description = "" if text == "ندارم" else text

        request = create_request(
            user_id=uid,
            username=user.username or "",
            full_name=state.get("full_name", ""),
            phone=state.get("phone", ""),
            telegram_id=state.get("telegram_id", ""),
            description=description,
            category=state.get("category", ""),
            service=state.get("service", ""),
        )

        USER_STATES.pop(uid, None)

        await update.message.reply_text(
            "✅ درخواست شما با موفقیت ثبت شد.\n\n"
            "📩 درخواست شما برای پشتیبانی ارسال شد.\n"
            "⏳ لطفاً منتظر پیام پشتیبانی باشید.\n\n"
            f"🆔 پشتیبانی:\n{SUPPORT_USERNAME}\n\n"
            "⚠️ لطفاً به پشتیبانی پیام ندهید؛\n"
            "پشتیبانی پس از بررسی درخواست، خودش با شما ارتباط خواهد گرفت.\n\n"
            f"🎫 کد پیگیری: {request['tracking_code']}",
            reply_markup=home_keyboard(),
        )

        # Notify admin
        try:
            await context.bot.send_message(
                ADMIN_ID,
                "🔔 درخواست جدید ثبت شد.\n\n"
                f"🎫 {request['tracking_code']}\n"
                f"📂 دسته: {request['category']}\n"
                f"🔧 خدمت: {request['service']}\n"
                f"👤 نام: {request['full_name']}\n"
                f"📱 شماره: {request['phone']}\n"
                f"🆔 تلگرام: {request['telegram_id'] or 'ثبت نشده'}\n"
                f"📝 توضیحات:\n{request['description'] or 'بدون توضیح'}\n\n"
                "برای مدیریت درخواست از پنل مدیریت استفاده کنید.",
            )
        except Exception:
            logger.exception("Could not notify admin about new request")

        return


# =========================
# ADMIN COMMAND
# =========================
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_user(update.effective_user)

    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ دسترسی ندارید.")
        return

    USER_STATES.pop(update.effective_user.id, None)

    await update.message.reply_text(
        "🛠 پنل مدیریت کافی‌نت آنلاین ۲۴",
        reply_markup=admin_keyboard(),
    )


# =========================
# ERROR HANDLER
# =========================
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.exception("Unhandled exception:", exc_info=context.error)


# =========================
# MAIN
# =========================
def main():
    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        CommandHandler("admin", admin_command)
    )

    app.add_handler(
        CallbackQueryHandler(callback_handler)
    )

    # دریافت شماره از دکمه تماس
    app.add_handler(
        MessageHandler(
            filters.CONTACT,
            contact_handler,
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_handler,
        )
    )

    app.add_error_handler(error_handler)

    logger.info("CafiNetOnline24 Started")
    app.run_polling()


if __name__ == "__main__":
    main()
