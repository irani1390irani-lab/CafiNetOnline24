import os
import sqlite3
import logging
from datetime import datetime, time
from zoneinfo import ZoneInfo

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
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
            InlineKeyboardButton("⚖️ قضایی", callback_data="service|judicial"),
            InlineKeyboardButton("🚗 خودرو", callback_data="service|vehicle"),
        ],
        [
            InlineKeyboardButton("🎓 آموزشی و دانشگاهی", callback_data="service|education"),
        ],
        [
            InlineKeyboardButton("💰 وام و تسهیلات", callback_data="service|loan"),
            InlineKeyboardButton("🏠 مسکن و املاک", callback_data="service|housing"),
        ],
        [
            InlineKeyboardButton("📊 مالی و مالیاتی", callback_data="service|tax"),
            InlineKeyboardButton("🛡 بیمه", callback_data="service|insurance"),
        ],
        [
            InlineKeyboardButton("🏛 خدمات دولتی", callback_data="service|government"),
            InlineKeyboardButton("🏦 بانکی", callback_data="service|bank"),
        ],
        [
            InlineKeyboardButton("✈️ سفر و بلیت", callback_data="service|travel"),
        ],
        [
            InlineKeyboardButton("🔎 پیگیری درخواست", callback_data="tracking"),
        ],
        [
            InlineKeyboardButton("📋 درخواست‌های من", callback_data="my_requests"),
        ],
        [
            InlineKeyboardButton("💬 پشتیبانی", callback_data="support"),
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
# Fixed service catalogue for the "ثبت‌نام‌های آنلاین" section.
# Each service opens the existing request form and gets its own category/service name.
ONLINE_CATEGORIES = {
    "judicial": ("⚖️ قضایی و حقوقی", [
        "ثبت‌نام و احراز هویت ثنا",
        "دریافت ابلاغیه قضایی",
        "درخواست گواهی عدم سوءپیشینه",
        "بازیابی اطلاعات ثنا",
        "نوبت‌دهی خدمات قضایی",
        "ثبت دادخواست و درخواست قضایی",
    ]),
    "vehicle": ("🚗 خودرو و پلیس", [
        "ثبت‌نام ایران‌خودرو",
        "ثبت‌نام سایپا",
        "ثبت‌نام طرح‌های فروش خودرو",
        "ثبت‌نام خودروهای فرسوده",
        "نوبت تعویض پلاک خودرو",
        "نوبت تعویض پلاک موتورسیکلت",
        "خدمات کارت سوخت",
        "خدمات سامانه سخا",
    ]),
    "education": ("🎓 آموزشی و دانشگاهی", [
        "ثبت‌نام کنکور",
        "خرید سریال و کارت آزمون",
        "ثبت‌نام آزمون‌های استخدامی",
        "ثبت‌نام آزمون‌های سازمان سنجش",
        "ثبت‌نام آزمون‌های فنی‌وحرفه‌ای",
        "ثبت‌نام مدارس",
        "ثبت‌نام مدارس نمونه دولتی و سمپاد",
        "ثبت‌نام کتاب درسی",
        "ثبت‌نام دانشگاه",
        "انتخاب رشته دانشگاه",
        "انتخاب واحد دانشگاه",
        "دریافت تأییدیه تحصیلی",
    ]),
    "loans": ("💰 وام و تسهیلات", [
        "ثبت‌نام وام ازدواج",
        "ثبت‌نام وام فرزندآوری",
        "ثبت‌نام وام ودیعه مسکن",
        "ثبت درخواست وام مسکن",
        "ثبت درخواست تسهیلات حمایتی",
    ]),
    "housing": ("🏠 مسکن و املاک", [
        "ثبت‌نام طرح‌های حمایتی مسکن",
        "ثبت اطلاعات سامانه املاک و اسکان",
        "ثبت قرارداد اجاره در سامانه خودنویس",
        "دریافت کد رهگیری اجاره",
        "خدمات سامانه ثبت من",
    ]),
    "finance": ("📊 مالی و مالیاتی", [
        "ثبت‌نام سجام",
        "احراز هویت سجام",
        "دریافت و ثبت کد مالیاتی",
        "ارسال اظهارنامه مالیاتی",
        "پرداخت مالیات",
        "اعتراض مالیاتی",
        "دریافت ابلاغیه مالیاتی",
    ]),
    "insurance": ("🛡️ بیمه", [
        "خدمات تأمین اجتماعی",
        "دریافت سوابق بیمه",
        "دریافت فیش و اطلاعات بیمه",
        "ثبت‌نام بیمه ورزشی",
        "خدمات بیمه خودرو",
    ]),
    "government": ("🏛️ خدمات دولتی", [
        "ثبت‌نام و پیگیری یارانه",
        "اعتراض به دهک‌بندی",
        "خدمات ثبت احوال",
        "خدمات کارت ملی",
        "خدمات سامانه‌های دولتی",
        "خدمات سامانه میخک",
    ]),
    "travel": ("✈️ سفر و بلیت", [
        "خرید بلیت هواپیما",
        "خرید بلیت قطار",
        "خرید بلیت اتوبوس",
        "رزرو اقامتگاه",
        "نوبت‌دهی پزشکی",
    ]),
}


def online_categories_keyboard():
    rows = []
    for key, (title, _) in ONLINE_CATEGORIES.items():
        rows.append([InlineKeyboardButton(title, callback_data=f"online_cat|{key}")])

    rows.append([InlineKeyboardButton("📅 ثبت‌نام‌های ویژه امروز", callback_data="today_regs")])
    rows.append([InlineKeyboardButton("➕ سایر ثبت‌نام‌ها", callback_data="other_reg")])
    rows.append([InlineKeyboardButton("🏠 بازگشت", callback_data="home")])
    return InlineKeyboardMarkup(rows)


def online_services_keyboard(category_key):
    title, services = ONLINE_CATEGORIES[category_key]
    rows = []
    for index, service in enumerate(services):
        rows.append([InlineKeyboardButton("📝 " + service, callback_data=f"online_service|{category_key}|{index}")])
    rows.append([InlineKeyboardButton("🔙 دسته‌بندی‌ها", callback_data="online_regs")])
    rows.append([InlineKeyboardButton("🏠 منوی اصلی", callback_data="home")])
    return InlineKeyboardMarkup(rows)


def service_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📨 ثبت درخواست این خدمت", callback_data="start_request")],
        [InlineKeyboardButton("🏠 منوی اصلی", callback_data="home")],
    ])


# =========================
# MAIN SERVICE CATEGORIES
# =========================
# These menus belong to the main keyboard.
# The separate "ثبت‌نام‌های آنلاین" section above is intentionally unchanged.
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
    "education": ("🎓 خدمات آموزشی و دانشگاهی", [
        "📝 ثبت‌نام کنکور",
        "💼 آزمون استخدامی",
        "📚 آزمون فنی‌وحرفه‌ای",
        "🏫 ثبت‌نام مدارس",
        "📖 ثبت‌نام کتاب درسی",
        "🎓 ثبت‌نام دانشگاه",
        "🔎 انتخاب رشته",
    ]),
    "housing": ("🏠 خدمات مسکن و املاک", [
        "🏠 طرح‌های حمایتی مسکن",
        "🏢 سامانه املاک و اسکان",
        "📝 ثبت قرارداد اجاره",
        "🔎 دریافت کد رهگیری اجاره",
        "🏡 خدمات املاک",
    ]),
    "government": ("🏛 خدمات دولتی", [
        "💳 خدمات یارانه",
        "📊 اعتراض به دهک‌بندی",
        "🪪 خدمات ثبت احوال",
        "🆔 خدمات کارت ملی",
        "🏛 سایر خدمات دولتی",
    ]),
    "travel": ("✈️ خدمات سفر و بلیت", [
        "✈️ بلیت هواپیما",
        "🚆 بلیت قطار",
        "🚌 بلیت اتوبوس",
        "🏨 رزرو اقامتگاه",
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
    return (
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
    }

    await query.edit_message_text(
        f"📝 ثبت درخواست\n\n"
        f"📂 دسته: {category}\n"
        f"🔧 خدمت: {service}\n\n"
        "👤 لطفاً نام و نام خانوادگی خود را ارسال کنید:"
    )


# =========================
# START
# =========================

# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_user(user)
    USER_STATES.pop(user.id, None)

    if is_bot_closed() and user.id != ADMIN_ID:
        await update.message.reply_text(closed_text())
        return

    # Remove any old Reply Keyboard from previous bot versions.
    # Telegram cannot show ReplyKeyboardRemove and InlineKeyboardMarkup
    # in the same message, so we send the removal first and the real
    # inline menu immediately afterwards.
    await update.message.reply_text(
        "🔄 منوی قبلی حذف شد.",
        reply_markup=ReplyKeyboardRemove(),
    )

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
        "⚡️ کافی‌نت آنلاین 24\n"
        "سامانه هوشمند ثبت و پیگیری خدمات آنلاین\n\n"
        "📝 ثبت درخواست‌های آنلاین\n"
        "🔎 پیگیری آسان با کد رهگیری\n"
        "💬 ارتباط مستقیم با پشتیبانی\n"
        "🚀 خدمات سریع و ساده\n\n"
        f"📢 کانال رسمی:\n{CHANNEL_LINK}\n\n"
        f"🤖 ربات خدمات:\n{BOT_LINK}\n\n"
        "🤖 فعالیت ربات: ۰۷:۰۰ تا ۲۳:۰۰\n"
        "🌙 از ۲۳:۰۰ تا ۰۷:۰۰ ربات غیرفعال است.",
        reply_markup=home_keyboard(),
    )


# =========================
# ONLINE REGISTRATIONS
# =========================
async def show_online_registrations(query):
    await query.edit_message_text(
        "📝 ثبت‌نام‌های آنلاین\n\n"
        "دسته‌بندی موردنظر را انتخاب کنید:\n\n"
        "هر خدمت بعد از انتخاب، مستقیماً به فرم ثبت درخواست متصل می‌شود.",
        reply_markup=online_categories_keyboard(),
    )


async def show_online_category(query, category_key):
    if category_key not in ONLINE_CATEGORIES:
        await query.answer("این دسته‌بندی موجود نیست.", show_alert=True)
        return

    title, services = ONLINE_CATEGORIES[category_key]
    await query.edit_message_text(
        f"{title}\n\n"
        f"خدمت موردنظر را انتخاب کنید:\n\n"
        f"📌 تعداد خدمات: {len(services)}",
        reply_markup=online_services_keyboard(category_key),
    )


async def select_online_service(query, category_key, service_index):
    if category_key not in ONLINE_CATEGORIES:
        await query.answer("این دسته‌بندی موجود نیست.", show_alert=True)
        return

    title, services = ONLINE_CATEGORIES[category_key]
    try:
        service = services[service_index]
    except (IndexError, TypeError):
        await query.answer("این خدمت موجود نیست.", show_alert=True)
        return

    await query.edit_message_text(
        f"📝 {service}\n\n"
        f"📂 دسته: {title}\n\n"
        "برای ثبت این خدمت، دکمه زیر را بزنید.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📨 ثبت درخواست این خدمت", callback_data=f"online_start|{category_key}|{service_index}")],
            [InlineKeyboardButton("🔙 بازگشت به خدمات", callback_data=f"online_cat|{category_key}")],
            [InlineKeyboardButton("🏠 منوی اصلی", callback_data="home")],
        ]),
    )


async def start_online_service_request(query, category_key, service_index):
    if category_key not in ONLINE_CATEGORIES:
        await query.answer("این دسته‌بندی موجود نیست.", show_alert=True)
        return

    title, services = ONLINE_CATEGORIES[category_key]
    try:
        service = services[service_index]
    except (IndexError, TypeError):
        await query.answer("این خدمت موجود نیست.", show_alert=True)
        return

    await begin_request(query, title, service)


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

    # Closed hours
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
            "📋 درخواست\n\n"
            f"🎫 {request['tracking_code']}\n"
            f"👤 {request['full_name']}\n"
            f"📱 {request['phone']}\n"
            f"🔧 {request['service']}\n"
            f"📝 {request['description'] or 'بدون توضیح'}\n\n"
            f"📌 وضعیت:\n{request['status']}\n"
            f"🕐 ثبت: {request['created_at']}",
            reply_markup=status_keyboard(code),
        )
        return

    # STATUS CHANGE
    if user_id == ADMIN_ID and "|" in data:
        action, code = data.split("|", 1)

        status_map = {
            "doing": "🔵 در حال انجام",
            "done": "🟢 انجام شد",
            "reject": "🔴 رد شد",
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
                logger.exception("Could not notify user %s", request["user_id"])

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
    # REQUEST NAME
    # =====================
    if current_state == STATE_NAME:
        state["full_name"] = text
        state["state"] = STATE_PHONE
        USER_STATES[uid] = state

        await update.message.reply_text(
            "📱 لطفاً شماره موبایل خود را ارسال کنید:"
        )
        return

    # =====================
    # REQUEST PHONE
    # =====================
    if current_state == STATE_PHONE:
        cleaned = text.replace(" ", "").replace("-", "")

        if not cleaned.isdigit() or len(cleaned) < 10:
            await update.message.reply_text(
                "❌ شماره موبایل معتبر نیست.\n"
                "لطفاً دوباره شماره خود را ارسال کنید."
            )
            return

        state["phone"] = text
        state["state"] = STATE_TELEGRAM
        USER_STATES[uid] = state

        await update.message.reply_text(
            "🆔 آیدی تلگرام خود را ارسال کنید.\n\n"
            "اگر ندارید، فقط بنویسید: ندارم"
        )
        return

    # =====================
    # REQUEST TELEGRAM ID
    # =====================
    if current_state == STATE_TELEGRAM:
        state["telegram_id"] = "" if text == "ندارم" else text
        state["state"] = STATE_DESCRIPTION
        USER_STATES[uid] = state

        await update.message.reply_text(
            "📝 توضیحات درخواست را ارسال کنید.\n\n"
            "اگر توضیح خاصی ندارید، بنویسید: ندارم"
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
            f"🎫 کد رهگیری: {request['tracking_code']}\n"
            f"📌 وضعیت: {request['status']}\n\n"
            "این کد را نزد خود نگه دارید تا بتوانید وضعیت درخواست "
            "را پیگیری کنید.",
            reply_markup=home_keyboard(),
        )

        # Notify admin
        try:
            await context.bot.send_message(
                ADMIN_ID,
                "🔔 درخواست جدید ثبت شد.\n\n"
                f"🎫 {request['tracking_code']}\n"
                f"👤 {request['full_name']}\n"
                f"📱 {request['phone']}\n"
                f"🔧 {request['service']}\n"
                f"📝 {request['description'] or 'بدون توضیح'}\n\n"
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
