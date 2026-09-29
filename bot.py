import os
import sqlite3
import logging
from datetime import datetime, time

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
    raise RuntimeError("BOT_TOKEN is not set.")

if not ADMIN_ID_RAW:
    raise RuntimeError("ADMIN_ID is not set.")

try:
    ADMIN_ID = int(ADMIN_ID_RAW)
except ValueError:
    raise RuntimeError("ADMIN_ID must be a number.")

DB_NAME = "cafinet.db"


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# =========================================================
# WORKING HOURS
# =========================================================

def is_bot_closed():
    current_time = datetime.now().time()

    # تعطیلی از 23:00 تا 07:00
    if current_time >= time(23, 0) or current_time < time(7, 0):
        return True

    return False


def closed_message():
    return (
        "🌙 *کافی‌نت آنلاین ۲۴ در حال حاضر غیرفعال است.*\n\n"
        "🕚 ساعت فعالیت:\n"
        "☀️ ۰۷:۰۰ تا ۲۳:۰۰\n\n"
        "⏰ در حال حاضر امکان ثبت و پیگیری درخواست وجود ندارد.\n\n"
        "🔔 لطفاً بعد از ساعت ۷ صبح دوباره مراجعه کنید.\n\n"
        "🙏 از صبر و شکیبایی شما سپاسگزاریم."
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
            description TEXT,
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

    conn.commit()
    conn.close()


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


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
        now(),
        now(),
    ))

    request_id = cur.lastrowid

    tracking_code = f"CF{10000 + request_id}"

    cur.execute("""
        UPDATE requests
        SET tracking_code = ?
        WHERE id = ?
    """, (tracking_code, request_id))

    conn.commit()

    cur.execute("""
        SELECT *
        FROM requests
        WHERE id = ?
    """, (request_id,))

    row = cur.fetchone()

    conn.close()

    return row


def get_request(code):
    code = code.strip().upper().replace("#", "")

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM requests
        WHERE tracking_code = ?
    """, (code,))

    row = cur.fetchone()

    conn.close()

    return row


def get_user_requests(user_id):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM requests
        WHERE user_id = ?
        ORDER BY id DESC
    """, (user_id,))

    rows = cur.fetchall()

    conn.close()

    return rows


def update_status(code, status):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE requests
        SET status = ?, updated_at = ?
        WHERE tracking_code = ?
    """, (status, now(), code))

    conn.commit()
    conn.close()


def save_message(code, sender_type, sender_id, message):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO messages (
            tracking_code,
            sender_type,
            sender_id,
            message,
            created_at
        )
        VALUES (?, ?, ?, ?, ?)
    """, (
        code,
        sender_type,
        sender_id,
        message,
        now(),
    ))

    conn.commit()
    conn.close()


def get_last_message(code):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM messages
        WHERE tracking_code = ?
        ORDER BY id DESC
        LIMIT 1
    """, (code,))

    row = cur.fetchone()

    conn.close()

    return row


# =========================================================
# SERVICES
# =========================================================

SERVICES = {
    "vehicle": {
        "name": "🚗 خودرو",
        "services": [
            "💳 پرداخت عوارض",
            "🚨 استعلام خلافی خودرو",
            "🚘 تعویض پلاک",
            "🪪 خدمات گواهینامه",
            "📄 خدمات سند خودرو",
            "➕ سایر خدمات خودرو",
        ],
    },

    "insurance": {
        "name": "🛡️ بیمه",
        "services": [
            "📄 استعلام بیمه",
            "🚗 بیمه خودرو",
            "🏥 بیمه درمانی",
            "👤 خدمات بیمه‌ای",
            "➕ سایر خدمات بیمه",
        ],
    },

    "tax": {
        "name": "💰 مالیاتی",
        "services": [
            "📄 خدمات مالیاتی",
            "🧾 اظهارنامه مالیاتی",
            "🔎 استعلام مالیاتی",
            "👤 پرونده مالیاتی",
            "➕ سایر خدمات مالیاتی",
        ],
    },

    "judicial": {
        "name": "⚖️ قضایی",
        "services": [
            "📄 خدمات قضایی",
            "🔎 استعلام قضایی",
            "📋 ثبت درخواست قضایی",
            "➕ سایر خدمات قضایی",
        ],
    },

    "bank": {
        "name": "🏦 بانکی",
        "services": [
            "💳 خدمات بانکی",
            "🏦 افتتاح حساب",
            "🔎 استعلام بانکی",
            "➕ سایر خدمات بانکی",
        ],
    },

    "loan": {
        "name": "💵 وام",
        "services": [
            "💰 ثبت درخواست وام",
            "🔎 پیگیری وام",
            "📄 خدمات مربوط به وام",
            "➕ سایر خدمات وام",
        ],
    },

    "medical": {
        "name": "🏥 درمانی",
        "services": [
            "🩺 خدمات درمانی",
            "📄 نوبت‌دهی",
            "💊 خدمات بیمه درمانی",
            "➕ سایر خدمات درمانی",
        ],
    },

    "education": {
        "name": "🎓 آموزشی",
        "services": [
            "📝 ثبت‌نام آموزشی",
            "🏫 خدمات مدارس",
            "🎓 خدمات دانشگاهی",
            "➕ سایر خدمات آموزشی",
        ],
    },

    "ticket": {
        "name": "🎫 بلیط",
        "services": [
            "🚌 بلیط اتوبوس",
            "🚆 بلیط قطار",
            "✈️ بلیط هواپیما",
            "➕ سایر خدمات بلیط",
        ],
    },

    "bill": {
        "name": "🧾 قبوض",
        "services": [
            "💡 قبض برق",
            "💧 قبض آب",
            "🔥 قبض گاز",
            "📱 قبض تلفن",
            "➕ سایر قبوض",
        ],
    },

    "other": {
        "name": "➕ سایر خدمات",
        "services": [
            "📝 سایر خدمات آنلاین",
        ],
    },
}


# =========================================================
# USER STATES
# =========================================================

USER_STATES = {}

STATE_FULLNAME = "fullname"
STATE_PHONE = "phone"
STATE_TELEGRAM = "telegram"
STATE_DESCRIPTION = "description"

STATE_TRACKING = "tracking"
STATE_USER_SUPPORT_CODE = "user_support_code"
STATE_USER_SUPPORT_MESSAGE = "user_support_message"

STATE_ADMIN_SUPPORT_CODE = "admin_support_code"
STATE_ADMIN_SUPPORT_MESSAGE = "admin_support_message"


# =========================================================
# KEYBOARDS
# =========================================================

def main_keyboard():
    buttons = [
        [
            InlineKeyboardButton("🚗 خودرو", callback_data="cat_vehicle"),
            InlineKeyboardButton("🛡️ بیمه", callback_data="cat_insurance"),
        ],
        [
            InlineKeyboardButton("💰 مالیاتی", callback_data="cat_tax"),
            InlineKeyboardButton("⚖️ قضایی", callback_data="cat_judicial"),
        ],
        [
            InlineKeyboardButton("🏦 بانکی", callback_data="cat_bank"),
            InlineKeyboardButton("💵 وام", callback_data="cat_loan"),
        ],
        [
            InlineKeyboardButton("🏥 درمانی", callback_data="cat_medical"),
            InlineKeyboardButton("🎓 آموزشی", callback_data="cat_education"),
        ],
        [
            InlineKeyboardButton("🎫 بلیط", callback_data="cat_ticket"),
            InlineKeyboardButton("🧾 قبوض", callback_data="cat_bill"),
        ],
        [
            InlineKeyboardButton("➕ سایر خدمات", callback_data="cat_other"),
        ],
        [
            InlineKeyboardButton(
                "🔎 پیگیری درخواست",
                callback_data="tracking"
            ),
            InlineKeyboardButton(
                "📋 درخواست‌های من",
                callback_data="my_requests"
            ),
        ],
        [
            InlineKeyboardButton(
                "💬 پشتیبانی",
                callback_data="support"
            ),
            InlineKeyboardButton(
                "ℹ️ درباره ما",
                callback_data="about"
            ),
        ],
    ]

    return InlineKeyboardMarkup(buttons)


def back_home_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🏠 منوی اصلی",
                callback_data="home"
            )
        ]
    ])


# =========================================================
# START
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    USER_STATES.pop(user.id, None)

    # کاربر عادی در ساعات تعطیلی
    if is_bot_closed() and user.id != ADMIN_ID:
        await update.message.reply_text(
            closed_message(),
            parse_mode="Markdown",
        )
        return

    text = (
        "🌐 *کافی‌نت آنلاین ۲۴*\n\n"
        "به سامانه خدمات آنلاین خوش آمدید.\n\n"
        "📌 خدمت موردنظر خود را از دسته‌بندی‌های زیر انتخاب کنید:"
    )

    await update.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=main_keyboard(),
    )


# =========================================================
# CATEGORY
# =========================================================

async def show_category(query, category):

    data = SERVICES.get(category)

    if not data:
        await query.answer("این خدمت پیدا نشد.")
        return

    buttons = []

    for index, service in enumerate(data["services"]):

        buttons.append([
            InlineKeyboardButton(
                service,
                callback_data=f"service|{category}|{index}",
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            "🔙 بازگشت",
            callback_data="home"
        )
    ])

    await query.edit_message_text(
        f"{data['name']}\n\n"
        "خدمت موردنظر را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


# =========================================================
# SELECT SERVICE
# =========================================================

async def select_service(query, category, index):

    data = SERVICES.get(category)

    if not data:
        return

    try:
        service = data["services"][int(index)]
    except (ValueError, IndexError):
        await query.answer("خطا در انتخاب خدمت.")
        return

    user_id = query.from_user.id

    USER_STATES[user_id] = {
        "state": STATE_FULLNAME,
        "category": data["name"],
        "service": service,
    }

    await query.edit_message_text(
        f"🔧 *{service}*\n\n"
        "برای ثبت درخواست، اطلاعات زیر از شما دریافت می‌شود.\n\n"
        "👤 لطفاً *نام و نام خانوادگی* خود را ارسال کنید:",
        parse_mode="Markdown",
    )


# =========================================================
# TEXT HANDLER
# =========================================================

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user
    user_id = user.id
    text = update.message.text.strip()

    # ادمین همیشه دسترسی دارد
    if is_bot_closed() and user_id != ADMIN_ID:

        USER_STATES.pop(user_id, None)

        await update.message.reply_text(
            closed_message(),
            parse_mode="Markdown",
        )
        return

    state_data = USER_STATES.get(user_id)

    if not state_data:

        await update.message.reply_text(
            "لطفاً یکی از گزینه‌های منوی اصلی را انتخاب کنید.",
            reply_markup=main_keyboard(),
        )
        return

    state = state_data.get("state")

    # -----------------------------------------------------
    # FULL NAME
    # -----------------------------------------------------

    if state == STATE_FULLNAME:

        state_data["full_name"] = text
        state_data["state"] = STATE_PHONE

        await update.message.reply_text(
            "📱 لطفاً شماره همراه خود را ارسال کنید:"
        )

        return

    # -----------------------------------------------------
    # PHONE
    # -----------------------------------------------------

    if state == STATE_PHONE:

        state_data["phone"] = text
        state_data["state"] = STATE_TELEGRAM

        await update.message.reply_text(
            "🔹 آیدی تلگرام خود را ارسال کنید.\n\n"
            "اگر آیدی ندارید یا نمی‌خواهید وارد کنید، "
            "بنویسید: «ندارم»"
        )

        return

    # -----------------------------------------------------
    # TELEGRAM
    # -----------------------------------------------------

    if state == STATE_TELEGRAM:

        if text.lower() in ["ندارم", "ندارم.", "ندارم!"]:
            state_data["telegram_id"] = ""
        else:
            state_data["telegram_id"] = text

        state_data["state"] = STATE_DESCRIPTION

        await update.message.reply_text(
            "📝 اگر توضیح یا درخواست خاصی دارید، ارسال کنید.\n\n"
            "اگر توضیحی ندارید، بنویسید: «ندارم»"
        )

        return

    # -----------------------------------------------------
    # DESCRIPTION
    # -----------------------------------------------------

    if state == STATE_DESCRIPTION:

        if text.lower() in ["ندارم", "ندارم.", "ندارم!"]:
            description = "بدون توضیحات"
        else:
            description = text

        state_data["description"] = description

        request = create_request(
            user_id=user_id,
            username=user.username or "",
            full_name=state_data["full_name"],
            phone=state_data["phone"],
            telegram_id=state_data["telegram_id"],
            description=description,
            category=state_data["category"],
            service=state_data["service"],
        )

        tracking = request["tracking_code"]

        save_message(
            tracking,
            "user",
            user_id,
            description,
        )

        USER_STATES.pop(user_id, None)

        await update.message.reply_text(
            "✅ *درخواست شما با موفقیت ثبت شد.*\n\n"
            f"🎫 *کد رهگیری:* `{tracking}`\n\n"
            f"📂 دسته: {request['category']}\n"
            f"🔧 خدمت: {request['service']}\n"
            "🟡 وضعیت: در انتظار بررسی\n\n"
            "⚠️ کد رهگیری خود را تا پایان درخواست نگه دارید.",
            parse_mode="Markdown",
            reply_markup=back_home_keyboard(),
        )

        admin_text = (
            "🆕 *درخواست جدید*\n\n"
            f"🎫 کد رهگیری: `{tracking}`\n\n"
            f"📂 دسته: {request['category']}\n"
            f"🔧 خدمت: {request['service']}\n\n"
            f"👤 نام: {request['full_name']}\n"
            f"📱 شماره: {request['phone']}\n"
            f"🔹 آیدی تلگرام: "
            f"{request['telegram_id'] or 'ثبت نشده'}\n\n"
            f"📝 توضیحات:\n{request['description']}\n\n"
            "🟡 وضعیت: در انتظار بررسی"
        )

        admin_keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "✅ تأیید",
                    callback_data=f"approve|{tracking}",
                ),
                InlineKeyboardButton(
                    "❌ رد",
                    callback_data=f"reject|{tracking}",
                ),
            ],
            [
                InlineKeyboardButton(
                    "💬 پاسخ به کاربر",
                    callback_data=f"admin_reply|{tracking}",
                ),
            ],
        ])

        try:

            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=admin_text,
                parse_mode="Markdown",
                reply_markup=admin_keyboard,
            )

        except Exception as e:

            logger.error(
                "Could not send request to admin: %s",
                e,
            )

        return

    # -----------------------------------------------------
    # TRACKING
    # -----------------------------------------------------

    if state == STATE_TRACKING:

        code = text.upper().replace("#", "")

        request = get_request(code)

        USER_STATES.pop(user_id, None)

        if not request:

            await update.message.reply_text(
                "❌ درخواست با این کد رهگیری پیدا نشد.\n\n"
                "کد را دوباره بررسی کنید.",
                reply_markup=back_home_keyboard(),
            )

            return

        if request["user_id"] != user_id and user_id != ADMIN_ID:

            await update.message.reply_text(
                "❌ این درخواست متعلق به حساب شما نیست.",
                reply_markup=back_home_keyboard(),
            )

            return

        await send_request_details(
            update.message.chat_id,
            request,
            context,
        )

        return

    # -----------------------------------------------------
    # USER SUPPORT CODE
    # -----------------------------------------------------

    if state == STATE_USER_SUPPORT_CODE:

        code = text.upper().replace("#", "")

        request = get_request(code)

        if not request:

            await update.message.reply_text(
                "❌ کد رهگیری پیدا نشد.\n\n"
                "لطفاً کد را دوباره ارسال کنید."
            )

            return

        if request["user_id"] != user_id:

            await update.message.reply_text(
                "❌ این درخواست متعلق به شما نیست."
            )

            return

        state_data["tracking"] = code
        state_data["state"] = STATE_USER_SUPPORT_MESSAGE

        await update.message.reply_text(
            f"💬 *پشتیبانی درخواست `{code}`*\n\n"
            "پیام خود را برای پشتیبانی ارسال کنید:",
            parse_mode="Markdown",
        )

        return

    # -----------------------------------------------------
    # USER SUPPORT MESSAGE
    # -----------------------------------------------------

    if state == STATE_USER_SUPPORT_MESSAGE:

        code = state_data["tracking"]

        request = get_request(code)

        if not request:

            USER_STATES.pop(user_id, None)

            await update.message.reply_text(
                "❌ درخواست پیدا نشد.",
                reply_markup=back_home_keyboard(),
            )

            return

        save_message(
            code,
            "user",
            user_id,
            text,
        )

        USER_STATES.pop(user_id, None)

        admin_text = (
            "💬 *پیام جدید از کاربر*\n\n"
            f"🎫 کد رهگیری: `{code}`\n"
            f"📂 دسته: {request['category']}\n"
            f"🔧 خدمت: {request['service']}\n\n"
            f"👤 {request['full_name']}\n\n"
            f"📝 پیام:\n{text}"
        )

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "💬 پاسخ",
                    callback_data=f"admin_reply|{code}",
                )
            ],
            [
                InlineKeyboardButton(
                    "📋 مشاهده درخواست",
                    callback_data=f"view_request|{code}",
                )
            ],
        ])

        try:

            await context.bot.send_message(
                ADMIN_ID,
                admin_text,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )

        except Exception as e:

            logger.error(
                "Support message error: %s",
                e,
            )

        await update.message.reply_text(
            "✅ پیام شما برای پشتیبانی ارسال شد.\n\n"
            f"🎫 کد رهگیری: `{code}`",
            parse_mode="Markdown",
            reply_markup=back_home_keyboard(),
        )

        return

    # -----------------------------------------------------
    # ADMIN SUPPORT CODE
    # -----------------------------------------------------

    if state == STATE_ADMIN_SUPPORT_CODE:

        if user_id != ADMIN_ID:

            USER_STATES.pop(user_id, None)
            return

        code = text.upper().replace("#", "")

        request = get_request(code)

        if not request:

            await update.message.reply_text(
                "❌ کد رهگیری پیدا نشد.\n\n"
                "دوباره کد را ارسال کنید."
            )

            return

        state_data["tracking"] = code
        state_data["state"] = STATE_ADMIN_SUPPORT_MESSAGE

        await update.message.reply_text(
            f"💬 *پاسخ به درخواست `{code}`*\n\n"
            f"👤 {request['full_name']}\n"
            f"📂 {request['category']}\n"
            f"🔧 {request['service']}\n\n"
            "پیام خود را ارسال کنید:",
            parse_mode="Markdown",
        )

        return

    # -----------------------------------------------------
    # ADMIN SUPPORT MESSAGE
    # -----------------------------------------------------

    if state == STATE_ADMIN_SUPPORT_MESSAGE:

        if user_id != ADMIN_ID:

            USER_STATES.pop(user_id, None)
            return

        code = state_data["tracking"]

        request = get_request(code)

        if not request:

            USER_STATES.pop(user_id, None)
            return

        save_message(
            code,
            "admin",
            ADMIN_ID,
            text,
        )

        USER_STATES.pop(user_id, None)

        update_status(
            code,
            "در حال انجام"
        )

        try:

            await context.bot.send_message(
                request["user_id"],
                "💬 *پیام پشتیبانی*\n\n"
                f"🎫 کد رهگیری: `{code}`\n\n"
                f"{text}\n\n"
                "برای پاسخ دادن، از گزینه "
                "«💬 پشتیبانی» استفاده کنید.",
                parse_mode="Markdown",
                reply_markup=back_home_keyboard(),
            )

            await update.message.reply_text(
                "✅ پیام شما برای کاربر ارسال شد.",
                reply_markup=back_home_keyboard(),
            )

        except Exception as e:

            logger.error(
                "Could not send admin reply: %s",
                e,
            )

            await update.message.reply_text(
                "❌ ارسال پیام انجام نشد."
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

    last_message = get_last_message(
        request["tracking_code"]
    )

    last_message_text = ""

    if last_message:

        sender = (
            "کاربر"
            if last_message["sender_type"] == "user"
            else "پشتیبانی"
        )

        last_message_text = (
            f"\n\n💬 آخرین پیام ({sender}):\n"
            f"{last_message['message']}"
        )

    text = (
        "📋 *جزئیات درخواست*\n\n"
        f"🎫 کد رهگیری: `{request['tracking_code']}`\n\n"
        f"📂 دسته: {request['category']}\n"
        f"🔧 خدمت: {request['service']}\n\n"
        f"👤 نام: {request['full_name']}\n"
        f"📱 شماره: {request['phone']}\n\n"
        f"📝 توضیحات:\n{request['description']}\n\n"
        f"📌 وضعیت: {request['status']}"
        f"{last_message_text}"
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "💬 پشتیبانی",
                callback_data=(
                    f"user_support|"
                    f"{request['tracking_code']}"
                ),
            )
        ],
        [
            InlineKeyboardButton(
                "🏠 منوی اصلی",
                callback_data="home",
            )
        ],
    ])

    await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


# =========================================================
# CALLBACK HANDLER
# =========================================================

async def callback_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    user = query.from_user
    user_id = user.id

    # کاربران عادی در ساعات تعطیلی
    if is_bot_closed() and user_id != ADMIN_ID:

        await query.answer()

        await query.edit_message_text(
            closed_message(),
            parse_mode="Markdown",
        )

        return

    await query.answer()

    data = query.data

    # -----------------------------------------------------
    # HOME
    # -----------------------------------------------------

    if data == "home":

        USER_STATES.pop(user_id, None)

        await query.edit_message_text(
            "🌐 *کافی‌نت آنلاین ۲۴*\n\n"
            "📌 خدمت موردنظر خود را انتخاب کنید:",
            parse_mode="Markdown",
            reply_markup=main_keyboard(),
        )

        return

    # -----------------------------------------------------
    # CATEGORY
    # -----------------------------------------------------

    if data.startswith("cat_"):

        category = data.replace(
            "cat_",
            "",
            1
        )

        await show_category(
            query,
            category
        )

        return

    # -----------------------------------------------------
    # SERVICE
    # -----------------------------------------------------

    if data.startswith("service|"):

        parts = data.split("|")

        if len(parts) != 3:
            return

        category = parts[1]
        index = parts[2]

        await select_service(
            query,
            category,
            index,
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
            "🔎 *پیگیری درخواست*\n\n"
            "کد رهگیری خود را ارسال کنید.\n\n"
            "مثال:\n"
            "`CF10248`",
            parse_mode="Markdown",
        )

        return

    # -----------------------------------------------------
    # MY REQUESTS
    # -----------------------------------------------------

    if data == "my_requests":

        requests = get_user_requests(user_id)

        if not requests:

            await query.edit_message_text(
                "📋 شما هنوز هیچ درخواستی ثبت نکرده‌اید.",
                reply_markup=back_home_keyboard(),
            )

            return

        buttons = []

        for request in requests:

            buttons.append([
                InlineKeyboardButton(
                    (
                        f"🎫 {request['tracking_code']} | "
                        f"{request['service']}"
                    ),
                    callback_data=(
                        f"view_request|"
                        f"{request['tracking_code']}"
                    ),
                )
            ])

        buttons.append([
            InlineKeyboardButton(
                "🏠 منوی اصلی",
                callback_data="home",
            )
        ])

        await query.edit_message_text(
            "📋 *درخواست‌های من*\n\n"
            "یکی از درخواست‌ها را انتخاب کنید:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(buttons),
        )

        return

    # -----------------------------------------------------
    # VIEW REQUEST
    # -----------------------------------------------------

    if data.startswith("view_request|"):

        code = data.split(
            "|",
            1
        )[1]

        request = get_request(code)

        if not request:

            await query.edit_message_text(
                "❌ درخواست پیدا نشد.",
                reply_markup=back_home_keyboard(),
            )

            return

        if (
            request["user_id"] != user_id
            and user_id != ADMIN_ID
        ):

            await query.answer(
                "این درخواست متعلق به شما نیست.",
                show_alert=True,
            )

            return

        await send_request_details(
            query.message.chat_id,
            request,
            context,
        )

        return

    # -----------------------------------------------------
    # USER SUPPORT
    # -----------------------------------------------------

    if data == "support":

        USER_STATES[user_id] = {
            "state": STATE_USER_SUPPORT_CODE
        }

        await query.edit_message_text(
            "💬 *پشتیبانی*\n\n"
            "کد رهگیری درخواست خود را ارسال کنید.\n\n"
            "مثال:\n"
            "`CF10248`",
            parse_mode="Markdown",
        )

        return

    # -----------------------------------------------------
    # USER SUPPORT FROM REQUEST
    # -----------------------------------------------------

    if data.startswith("user_support|"):

        code = data.split(
            "|",
            1
        )[1]

        request = get_request(code)

        if not request:

            await query.answer(
                "درخواست پیدا نشد.",
                show_alert=True,
            )

            return

        if request["user_id"] != user_id:

            await query.answer(
                "این درخواست متعلق به شما نیست.",
                show_alert=True,
            )

            return

        USER_STATES[user_id] = {
            "state": STATE_USER_SUPPORT_MESSAGE,
            "tracking": code,
        }

        await query.edit_message_text(
            f"💬 *پشتیبانی درخواست `{code}`*\n\n"
            "پیام خود را ارسال کنید:",
            parse_mode="Markdown",
        )

        return

    # -----------------------------------------------------
    # ABOUT
    # -----------------------------------------------------

    if data == "about":

        await query.edit_message_text(
            "🌐 *کافی‌نت آنلاین ۲۴*\n\n"
            "ارائه خدمات و ثبت درخواست‌های آنلاین.\n\n"
            "📌 درخواست خود را ثبت کنید و با استفاده از "
            "کد رهگیری، وضعیت آن را پیگیری کنید.\n\n"
            "🕚 ساعت فعالیت:\n"
            "۰۷:۰۰ تا ۲۳:۰۰",
            parse_mode="Markdown",
            reply_markup=back_home_keyboard(),
        )

        return

    # -----------------------------------------------------
    # ADMIN ONLY
    # -----------------------------------------------------

    if user_id != ADMIN_ID:
        return

    # -----------------------------------------------------
    # APPROVE
    # -----------------------------------------------------

    if data.startswith("approve|"):

        code = data.split(
            "|",
            1
        )[1]

        request = get_request(code)

        if not request:

            await query.answer(
                "درخواست پیدا نشد.",
                show_alert=True,
            )

            return

        update_status(
            code,
            "تأیید شده"
        )

        try:

            await context.bot.send_message(
                request["user_id"],
                "✅ *درخواست شما تأیید شد.*\n\n"
                f"🎫 کد رهگیری: `{code}`\n\n"
                "🔄 در حال برقراری ارتباط با پشتیبانی...",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "💬 ارتباط با پشتیبانی",
                            callback_data=(
                                f"user_support|{code}"
                            ),
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "📋 مشاهده درخواست",
                            callback_data=(
                                f"view_request|{code}"
                            ),
                        )
                    ],
                ]),
            )

        except Exception as e:

            logger.error(
                "Approve notification error: %s",
                e,
            )

        await query.edit_message_reply_markup(
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🟢 تأیید شد",
                        callback_data="noop",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "💬 پاسخ به کاربر",
                        callback_data=(
                            f"admin_reply|{code}"
                        ),
                    )
                ],
            ])
        )

        return

    # -----------------------------------------------------
    # REJECT
    # -----------------------------------------------------

    if data.startswith("reject|"):

        code = data.split(
            "|",
            1
        )[1]

        request = get_request(code)

        if not request:
            return

        update_status(
            code,
            "رد شده"
        )

        try:

            await context.bot.send_message(
                request["user_id"],
                "❌ *درخواست شما رد شد.*\n\n"
                f"🎫 کد رهگیری: `{code}`\n\n"
                "برای دریافت اطلاعات بیشتر می‌توانید "
                "با پشتیبانی در ارتباط باشید.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "💬 پشتیبانی",
                            callback_data=(
                                f"user_support|{code}"
                            ),
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "🏠 منوی اصلی",
                            callback_data="home",
                        )
                    ],
                ]),
            )

        except Exception as e:

            logger.error(
                "Reject notification error: %s",
                e,
            )

        await query.edit_message_reply_markup(
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔴 رد شد",
                        callback_data="noop",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "💬 پاسخ به کاربر",
                        callback_data=(
                            f"admin_reply|{code}"
                        ),
                    )
                ],
            ])
        )

        return

    # -----------------------------------------------------
    # ADMIN REPLY
    # -----------------------------------------------------

    if data.startswith("admin_reply|"):

        code = data.split(
            "|",
            1
        )[1]

        request = get_request(code)

        if not request:

            await query.answer(
                "درخواست پیدا نشد.",
                show_alert=True,
            )

            return

        USER_STATES[user_id] = {
            "state": STATE_ADMIN_SUPPORT_MESSAGE,
            "tracking": code,
        }

        await query.message.reply_text(
            f"💬 *پاسخ به درخواست `{code}`*\n\n"
            f"👤 {request['full_name']}\n"
            f"📂 {request['category']}\n"
            f"🔧 {request['service']}\n\n"
            "پیام خود را ارسال کنید:",
            parse_mode="Markdown",
        )

        return

    # -----------------------------------------------------
    # NOOP
    # -----------------------------------------------------

    if data == "noop":

        await query.answer()

        return


# =========================================================
# ADMIN COMMAND
# =========================================================

async def admin(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if update.effective_user.id != ADMIN_ID:

        await update.message.reply_text(
            "❌ دسترسی ندارید."
        )

        return

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🔎 جستجوی درخواست",
                callback_data="admin_search",
            )
        ],
        [
            InlineKeyboardButton(
                "💬 پاسخ به کاربر",
                callback_data="admin_support",
            )
        ],
    ])

    await update.message.reply_text(
        "👨‍💻 *پنل مدیریت*\n\n"
        "مدیریت درخواست‌ها و پشتیبانی:",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


# =========================================================
# ADMIN BUTTONS
# =========================================================

async def admin_button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    user_id = query.from_user.id

    if user_id != ADMIN_ID:

        await query.answer(
            "دسترسی ندارید.",
            show_alert=True,
        )

        return

    if query.data == "admin_search":

        USER_STATES[user_id] = {
            "state": STATE_ADMIN_SUPPORT_CODE
        }

        await query.message.reply_text(
            "🔎 کد رهگیری درخواست را ارسال کنید:"
        )

        await query.answer()

        return

    if query.data == "admin_support":

        USER_STATES[user_id] = {
            "state": STATE_ADMIN_SUPPORT_CODE
        }

        await query.message.reply_text(
            "💬 برای پاسخ به کاربر، "
            "کد رهگیری را ارسال کنید:"
        )

        await query.answer()

        return


# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
):

    logger.error(
        "Exception while handling update:",
        exc_info=context.error,
    )


# =========================================================
# MAIN
# =========================================================

def main():

    init_db()

    application = (
        Application.builder()
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
            admin,
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            admin_button_handler,
            pattern=r"^admin_(search|support)$",
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
        "CafiNet Online 24 bot is starting..."
    )

    application.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
