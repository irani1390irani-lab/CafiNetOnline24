import os
import sqlite3
import logging
from datetime import datetime, time
from zoneinfo import ZoneInfo

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
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


ADMIN_ID = int(ADMIN_ID_RAW)


CHANNEL_LINK = "https://t.me/CafiNetOnlin24"
BOT_LINK = "https://t.me/CafiNetOnlinBot"


BASE_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

DB_NAME = os.path.join(
    BASE_DIR,
    "cafinet.db"
)


IRAN_TZ = ZoneInfo(
    "Asia/Tehran"
)


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

logger = logging.getLogger(
    "CafiNetOnline24"
)



# =========================================================
# TIME
# =========================================================


def iran_now():

    return datetime.now(
        IRAN_TZ
    )



def now_text():

    return iran_now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )



def today_text():

    return iran_now().strftime(
        "%Y-%m-%d"
    )



def is_bot_closed():

    current = iran_now().time()

    return (
        current >= time(23,0)
        or current < time(7,0)
    )



def closed_message():

    return """
🌙 کافی‌نت آنلاین ۲۴

در حال حاضر خارج از ساعت فعالیت هستیم.

🕖 ساعت فعالیت:
۰۷:۰۰ تا ۲۳:۰۰

لطفاً در ساعات کاری مراجعه کنید.
"""



# =========================================================
# DATABASE
# =========================================================


def get_db():

    conn = sqlite3.connect(
        DB_NAME
    )

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

        active INTEGER DEFAULT 1,

        created_at TEXT NOT NULL
    )
    """)



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
    service
):

    conn = get_db()

    cur = conn.cursor()


    cur.execute("""
    INSERT INTO requests

    (
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

    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
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
        now_text()
    ))



    rid = cur.lastrowid


    code = f"CF{10000 + rid}"



    cur.execute(
        """
        UPDATE requests

        SET tracking_code=?

        WHERE id=?
        """,
        (
            code,
            rid
        )
    )


    conn.commit()


    row = cur.execute(
        """
        SELECT *

        FROM requests

        WHERE id=?
        """,
        (
            rid,
        )
    ).fetchone()


    conn.close()


    return row# =========================================================
# REQUEST DATABASE FUNCTIONS
# =========================================================


def get_request(tracking_code):

    if not tracking_code:
        return None


    tracking_code = (
        tracking_code
        .strip()
        .upper()
        .replace("#","")
    )


    conn = get_db()


    row = conn.execute(
        """
        SELECT *

        FROM requests

        WHERE tracking_code=?
        """,
        (
            tracking_code,
        )
    ).fetchone()


    conn.close()


    return row



def get_user_requests(user_id):

    conn = get_db()


    rows = conn.execute(
        """
        SELECT *

        FROM requests

        WHERE user_id=?

        ORDER BY id DESC
        """,
        (
            user_id,
        )
    ).fetchall()


    conn.close()


    return rows



def update_status(
    tracking_code,
    status
):

    conn = get_db()


    conn.execute(
        """
        UPDATE requests

        SET status=?,
            updated_at=?

        WHERE tracking_code=?
        """,
        (
            status,
            now_text(),
            tracking_code
        )
    )


    conn.commit()

    conn.close()



def save_message(
    tracking_code,
    sender_type,
    sender_id,
    message
):

    conn = get_db()


    conn.execute(
        """
        INSERT INTO messages

        (
        tracking_code,
        sender_type,
        sender_id,
        message,
        created_at
        )

        VALUES (?,?,?,?,?)
        """,

        (
            tracking_code,
            sender_type,
            sender_id,
            message,
            now_text()
        )
    )


    conn.commit()

    conn.close()



# =========================================================
# ONLINE REGISTRATIONS
# =========================================================


def add_registration(
    title,
    registration_date=None
):

    if registration_date is None:
        registration_date = today_text()



    conn = get_db()


    conn.execute(
        """
        INSERT INTO registrations

        (
        title,
        registration_date,
        active,
        created_at
        )

        VALUES (?,?,1,?)
        """,

        (
            title,
            registration_date,
            now_text()
        )
    )


    conn.commit()

    conn.close()



def get_today_registrations():

    conn = get_db()


    rows = conn.execute(
        """
        SELECT *

        FROM registrations

        WHERE registration_date=?

        AND active=1

        ORDER BY id ASC
        """,

        (
            today_text(),
        )
    ).fetchall()


    conn.close()


    return rows



def get_registration(
    reg_id
):

    conn = get_db()


    row = conn.execute(
        """
        SELECT *

        FROM registrations

        WHERE id=?

        AND active=1
        """,

        (
            reg_id,
        )
    ).fetchone()


    conn.close()


    return row



def deactivate_registration(
    reg_id
):

    conn = get_db()


    conn.execute(
        """
        UPDATE registrations

        SET active=0

        WHERE id=?
        """,
        (
            reg_id,
        )
    )


    conn.commit()

    conn.close()



# =========================================================
# SERVICES
# =========================================================


UPDATING_SERVICES = {

    "vehicle":
    "🚗 خودرو",

    "insurance":
    "🛡️ بیمه",

    "tax":
    "💰 مالیاتی",

    "judicial":
    "⚖️ قضایی",

    "bank":
    "🏦 بانکی",

    "loan":
    "💵 وام",

    "medical":
    "🏥 درمانی",

    "education":
    "🎓 آموزشی",

    "ticket":
    "🎫 بلیط",

    "bill":
    "🧾 قبوض",

    "other":
    "➕ سایر خدمات"

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


STATE_ADMIN_ADD_REG = "admin_add_reg"

STATE_ADMIN_REPLY = "admin_reply"# =========================================================
# KEYBOARDS
# =========================================================


def main_keyboard(user_id=None):

    rows = [

        [
            InlineKeyboardButton(
                "📝 ثبت‌نام‌های آنلاین",
                callback_data="online_regs"
            )
        ],


        [
            InlineKeyboardButton(
                "🚗 خودرو",
                callback_data="updating|vehicle"
            ),

            InlineKeyboardButton(
                "🛡️ بیمه",
                callback_data="updating|insurance"
            )
        ],


        [
            InlineKeyboardButton(
                "💰 مالیاتی",
                callback_data="updating|tax"
            ),

            InlineKeyboardButton(
                "⚖️ قضایی",
                callback_data="updating|judicial"
            )
        ],


        [
            InlineKeyboardButton(
                "🏦 بانکی",
                callback_data="updating|bank"
            ),

            InlineKeyboardButton(
                "💵 وام",
                callback_data="updating|loan"
            )
        ],


        [
            InlineKeyboardButton(
                "🏥 درمانی",
                callback_data="updating|medical"
            ),

            InlineKeyboardButton(
                "🎓 آموزشی",
                callback_data="updating|education"
            )
        ],


        [
            InlineKeyboardButton(
                "🎫 بلیط",
                callback_data="updating|ticket"
            ),

            InlineKeyboardButton(
                "🧾 قبوض",
                callback_data="updating|bill"
            )
        ],


        [
            InlineKeyboardButton(
                "➕ سایر خدمات",
                callback_data="updating|other"
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
        ]

    ]


    # فقط برای صاحب ربات

    if user_id == ADMIN_ID:

        rows.append(
            [
                InlineKeyboardButton(
                    "🛠 پنل مدیریت",
                    callback_data="admin_panel"
                )
            ]
        )


    return InlineKeyboardMarkup(rows)




def home_keyboard():

    return InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "🏠 منوی اصلی",
                callback_data="home"
            )
        ]

    ])




def admin_keyboard():

    return InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "📝 افزودن ثبت‌نام امروز",
                callback_data="admin_add_reg"
            )
        ],


        [
            InlineKeyboardButton(
                "📋 ثبت‌نام‌های امروز",
                callback_data="admin_regs"
            )
        ],


        [
            InlineKeyboardButton(
                "🔎 جستجوی درخواست",
                callback_data="admin_find"
            )
        ],


        [
            InlineKeyboardButton(
                "🏠 بازگشت",
                callback_data="home"
            )
        ]

    ])




def registrations_keyboard():

    rows = []


    registrations = get_today_registrations()


    for reg in registrations:

        rows.append(
            [
                InlineKeyboardButton(
                    "📝 " + reg["title"],
                    callback_data=f"registration|{reg['id']}"
                )
            ]
        )



    rows.append(
        [
            InlineKeyboardButton(
                "➕ سایر ثبت‌نام‌ها",
                callback_data="other_registration"
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
# ABOUT PAGE
# =========================================================


async def about_page(query):

    await query.edit_message_text(

f"""
⚡️ کافی‌نت آنلاین ۲۴

سامانه هوشمند خدمات آنلاین

📝 ثبت درخواست‌های آنلاین
🔎 پیگیری با کد رهگیری
💬 ارتباط مستقیم با پشتیبانی
🚀 انجام خدمات سریع و ساده

📢 کانال رسمی:
{CHANNEL_LINK}

🤖 ربات:
{BOT_LINK}
""",

        reply_markup=home_keyboard()
    )# =========================================================
# START
# =========================================================


async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user


    USER_STATES.pop(
        user.id,
        None
    )


    if is_bot_closed() and user.id != ADMIN_ID:

        await update.message.reply_text(
            closed_message()
        )

        return



    await update.message.reply_text(

"""
🌐 کافی‌نت آنلاین ۲۴

به سامانه خدمات آنلاین خوش آمدید.

📌 خدمت موردنظر خود را انتخاب کنید:
""",

        reply_markup=main_keyboard(
            user.id
        )
    )



# =========================================================
# ONLINE REGISTRATION
# =========================================================


async def show_online_registrations(query):


    regs = get_today_registrations()


    if regs:

        text = """
📝 ثبت‌نام‌های آنلاین امروز

ثبت‌نام موردنظر را انتخاب کنید:
"""

    else:

        text = """
📝 ثبت‌نام‌های آنلاین امروز

فعلاً ثبت‌نامی برای امروز ثبت نشده است.

در صورت نبود گزینه موردنظر،
«سایر ثبت‌نام‌ها» را انتخاب کنید.
"""



    await query.edit_message_text(

        text,

        reply_markup=registrations_keyboard()

    )





async def select_registration(
    query,
    reg_id
):


    reg = get_registration(
        reg_id
    )


    if not reg:

        await query.answer(
            "این ثبت‌نام فعال نیست.",
            show_alert=True
        )

        return



    USER_STATES[
        query.from_user.id
    ] = {

        "state":
        STATE_REG_FULLNAME,

        "category":
        "📝 ثبت‌نام آنلاین",

        "service":
        reg["title"]

    }



    await query.edit_message_text(

f"""
📝 ثبت‌نام:
{reg['title']}

👤 نام و نام خانوادگی خود را ارسال کنید:
"""

    )






async def start_other_registration(query):


    USER_STATES[
        query.from_user.id
    ] = {

        "state":
        STATE_OTHER_FULLNAME,

        "category":
        "📝 ثبت‌نام آنلاین",

        "service":
        "➕ سایر ثبت‌نام‌ها"

    }



    await query.edit_message_text(

"""
➕ سایر ثبت‌نام‌ها

ثبت‌نام موردنظر در لیست نیست.

👤 نام و نام خانوادگی خود را ارسال کنید:
"""

    )





# =========================================================
# FINISH REQUEST
# =========================================================


async def finish_request(
    update,
    context,
    data
):

    user = update.effective_user



    req = create_request(

        user_id=user.id,

        username=user.username or "",

        full_name=data["full_name"],

        phone=data["phone"],

        telegram_id=data.get(
            "telegram_id",
            ""
        ),

        description=data["description"],

        category=data["category"],

        service=data["service"]

    )



    code = req["tracking_code"]



    save_message(

        code,

        "user",

        user.id,

        req["description"]

    )



    USER_STATES.pop(
        user.id,
        None
    )



    await update.message.reply_text(

f"""
✅ درخواست شما ثبت شد.

🎫 کد رهگیری:
{code}

📌 وضعیت:
🟡 در انتظار بررسی

⚠️ این کد را نگه دارید.
""",

        reply_markup=home_keyboard()

    )




    keyboard = InlineKeyboardMarkup([


        [

            InlineKeyboardButton(
                "🔵 در حال انجام",
                callback_data=f"doing|{code}"
            )

        ],


        [

            InlineKeyboardButton(
                "🟢 انجام شد",
                callback_data=f"done|{code}"
            ),

            InlineKeyboardButton(
                "🔴 رد شد",
                callback_data=f"reject|{code}"
            )

        ]

    ])




    await context.bot.send_message(

        ADMIN_ID,

f"""
🆕 درخواست جدید

🎫 کد:
{code}

📂 دسته:
{req['category']}

🔧 خدمت:
{req['service']}


👤 نام:
{req['full_name']}

📱 شماره:
{req['phone']}


📝 توضیحات:

{req['description']}


📌 وضعیت:
🟡 در انتظار بررسی
""",

        reply_markup=keyboard

    )# =========================================================
# CALLBACK HANDLER
# =========================================================


async def callback_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()


    user_id = query.from_user.id

    data = query.data



    # HOME

    if data == "home":

        USER_STATES.pop(
            user_id,
            None
        )


        await query.edit_message_text(

            "🌐 منوی اصلی کافی‌نت آنلاین ۲۴",

            reply_markup=main_keyboard(
                user_id
            )
        )

        return




    # ABOUT

    if data == "about":

        await about_page(query)

        return




    # ADMIN PANEL

    if data == "admin_panel":


        if user_id != ADMIN_ID:

            return



        await query.edit_message_text(

"""
🛠 پنل مدیریت کافی‌نت آنلاین ۲۴

بخش موردنظر را انتخاب کنید:
""",

            reply_markup=admin_keyboard()

        )

        return




    # ADD REG

    if data == "admin_add_reg":


        if user_id != ADMIN_ID:

            return



        USER_STATES[ADMIN_ID] = {

            "state":
            STATE_ADMIN_ADD_REG

        }


        await query.edit_message_text(

            "📝 نام ثبت‌نام جدید را ارسال کنید:"
        )

        return




    # ONLINE REG

    if data == "online_regs":


        await show_online_registrations(
            query
        )

        return




    if data == "other_registration":

        await start_other_registration(
            query
        )

        return




    if data.startswith(
        "registration|"
    ):


        reg_id = int(
            data.split("|")[1]
        )


        await select_registration(
            query,
            reg_id
        )

        return





    # UPDATING


    if data.startswith(
        "updating|"
    ):


        key = data.split("|")[1]


        name = UPDATING_SERVICES.get(
            key,
            "خدمت"
        )



        await query.edit_message_text(

f"""
{name}

🔄 این بخش در حال بروزرسانی است.

به‌زودی فعال خواهد شد.
""",

            reply_markup=home_keyboard()

        )


        return





    # TRACKING


    if data == "tracking":


        USER_STATES[user_id] = {

            "state":
            STATE_TRACKING

        }


        await query.edit_message_text(

"""
🔎 پیگیری درخواست

کد رهگیری خود را ارسال کنید:
"""

        )


        return




    # MY REQUESTS


    if data == "my_requests":


        reqs = get_user_requests(
            user_id
        )


        if not reqs:


            await query.edit_message_text(

"""
📋 درخواست‌های من

درخواستی ثبت نشده است.
""",

                reply_markup=home_keyboard()

            )


            return



        text = "📋 درخواست‌های من\n\n"



        for r in reqs[:10]:


            text += (

                f"🎫 {r['tracking_code']}\n"

                f"🔧 {r['service']}\n"

                f"📌 {r['status']}\n\n"

            )



        await query.edit_message_text(

            text,

            reply_markup=home_keyboard()

        )

        return




    # ADMIN STATUS


    if user_id == ADMIN_ID and "|" in data:


        action,code = data.split(
            "|",
            1
        )


        status = None



        if action == "doing":

            status = "🔵 در حال انجام"



        elif action == "done":

            status = "🟢 انجام شد"



        elif action == "reject":

            status = "🔴 رد شد"




        if status:


            update_status(
                code,
                status
            )



            req = get_request(
                code
            )



            if req:

                await context.bot.send_message(

                    req["user_id"],

f"""
🔔 وضعیت درخواست شما تغییر کرد

🎫 کد:
{code}

📌 وضعیت جدید:

{status}
"""

                )



            await query.edit_message_text(

                query.message.text +

                f"\n\n📌 وضعیت جدید: {status}"

            )

            return




# =========================================================
# TEXT HANDLER
# =========================================================


async def text_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):


    user = update.effective_user

    uid = user.id

    text = update.message.text.strip()



    state = USER_STATES.get(
        uid
    )


    if not state:

        return



    current = state["state"]




    # ADMIN ADD REG


    if current == STATE_ADMIN_ADD_REG:


        add_registration(
            text
        )


        USER_STATES.pop(
            uid,
            None
        )


        await update.message.reply_text(

f"""
✅ ثبت‌نام اضافه شد

📝 {text}
""",

            reply_markup=main_keyboard(uid)

        )

        return





    # TRACKING


    if current == STATE_TRACKING:


        req = get_request(
            text
        )



        if not req:


            await update.message.reply_text(

                "❌ کد رهگیری پیدا نشد."
            )

            return




        if req["user_id"] != uid and uid != ADMIN_ID:


            await update.message.reply_text(

                "❌ این درخواست متعلق به شما نیست."
            )

            return



        USER_STATES.pop(
            uid,
            None
        )



        await update.message.reply_text(

f"""
📋 جزئیات درخواست

🎫 کد:
{req['tracking_code']}

🔧 خدمت:
{req['service']}

📌 وضعیت:
{req['status']}

📝 توضیحات:
{req['description']}
""",

            reply_markup=home_keyboard()

        )


        return



# =========================================================
# MAIN
# =========================================================


def main():


    init_db()



    app = Application.builder().token(
        BOT_TOKEN
    ).build()



    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )



    app.add_handler(
        CallbackQueryHandler(
            callback_handler
        )
    )



    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_handler
        )
    )



    logger.info(
        "CafiNetOnline24 Started"
    )



    app.run_polling()



if __name__ == "__main__":

    main()
