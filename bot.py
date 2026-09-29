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
ADMIN_ID = int(os.getenv("ADMIN_ID"))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, "cafinet.db")

IRAN_TZ = ZoneInfo("Asia/Tehran")

CHANNEL_LINK = "https://t.me/CafiNetOnlin24"
BOT_LINK = "https://t.me/CafiNetOnlinBot"


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
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
    return now >= time(23,0) or now < time(7,0)



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


    cur.execute("""
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
    """)


    cur.execute("""
    CREATE TABLE IF NOT EXISTS registrations(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        registration_date TEXT,
        active INTEGER DEFAULT 1,
        created_at TEXT
    )
    """)


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



# =========================
# SERVICES
# =========================

SERVICES = {

"vehicle":"🚗 خودرو",
"insurance":"🛡 بیمه",
"tax":"💰 مالیاتی",
"judicial":"⚖️ قضایی",
"bank":"🏦 بانکی",
"loan":"💵 وام",
"medical":"🏥 درمانی",
"education":"🎓 آموزشی",
"ticket":"🎫 بلیط",
"bill":"🧾 قبوض"

}



# =========================
# MAIN KEYBOARD
# =========================

def main_keyboard(user_id=None):

    buttons=[

        [
            InlineKeyboardButton(
            "📝 ثبت‌نام‌های آنلاین",
            callback_data="online_regs"
            )
        ],

        [
            InlineKeyboardButton(
            "🚗 خودرو",
            callback_data="update"
            ),
            InlineKeyboardButton(
            "🛡 بیمه",
            callback_data="update"
            )
        ],

        [
            InlineKeyboardButton(
            "🔎 پیگیری درخواست",
            callback_data="tracking"
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
            "💬 پشتیبانی",
            callback_data="support"
            ),
            InlineKeyboardButton(
            "ℹ️ درباره ما",
            callback_data="about"
            )
        ]

    ]


    if user_id == ADMIN_ID:
        buttons.append(
            [
                InlineKeyboardButton(
                "🛠 پنل مدیریت",
                callback_data="admin_panel"
                )
            ]
        )


    return InlineKeyboardMarkup(buttons)



# =========================
# ADMIN PANEL
# =========================

def admin_keyboard():

    return InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
            "📋 درخواست‌ها",
            callback_data="admin_requests"
            )
        ],

        [
            InlineKeyboardButton(
            "📝 افزودن ثبت‌نام",
            callback_data="admin_add_reg"
            ),

            InlineKeyboardButton(
            "📑 ثبت‌نام‌های امروز",
            callback_data="admin_regs"
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
            "🏠 منوی اصلی",
            callback_data="home"
            )
        ]

    ])



def home_keyboard():

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
            "🏠 منوی اصلی",
            callback_data="home"
            )
        ]
    ])# =========================
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
    service
):

    conn = get_db()
    cur = conn.cursor()


    cur.execute("""
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
    """,(
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

    code = f"CF{10000+rid}"


    cur.execute("""
    UPDATE requests
    SET tracking_code=?
    WHERE id=?
    """,(code,rid))


    conn.commit()


    row = cur.execute(
        "SELECT * FROM requests WHERE id=?",
        (rid,)
    ).fetchone()


    conn.close()

    return row



def get_request(code):

    code = code.upper().replace("#","")

    conn=get_db()

    row=conn.execute(
        """
        SELECT * FROM requests
        WHERE tracking_code=?
        """,
        (code,)
    ).fetchone()

    conn.close()

    return row



def update_status(code,status):

    conn=get_db()

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
            code
        )
    )

    conn.commit()
    conn.close()



def get_today_registrations():

    conn=get_db()

    rows=conn.execute(
        """
        SELECT *
        FROM registrations
        WHERE registration_date=?
        AND active=1
        """,
        (today_text(),)
    ).fetchall()

    conn.close()

    return rows



def add_registration(title):

    conn=get_db()

    conn.execute(
        """
        INSERT INTO registrations
        (
        title,
        registration_date,
        active,
        created_at
        )
        VALUES(?,?,1,?)
        """,
        (
            title,
            today_text(),
            now_text()
        )
    )

    conn.commit()
    conn.close()



# =========================
# SEND REQUEST DETAILS
# =========================


async def send_request_details(
    chat_id,
    request,
    context
):

    await context.bot.send_message(
        chat_id=chat_id,
        text=f"""
📋 جزئیات درخواست

🎫 کد رهگیری:
{request['tracking_code']}

📂 دسته:
{request['category']}

🔧 خدمت:
{request['service']}

👤 نام:
{request['full_name']}

📱 شماره:
{request['phone']}

📝 توضیحات:
{request['description']}

📌 وضعیت:
{request['status']}

🕐 زمان ثبت:
{request['created_at']}
""",
        reply_markup=home_keyboard()
    )



# =========================
# REGISTRATION KEYBOARD
# =========================


def registrations_keyboard():

    rows=[]

    for item in get_today_registrations():

        rows.append([
            InlineKeyboardButton(
                "📝 "+item["title"],
                callback_data=f"reg|{item['id']}"
            )
        ])


    rows.append([
        InlineKeyboardButton(
            "➕ سایر ثبت‌نام‌ها",
            callback_data="other_reg"
        )
    ])


    rows.append([
        InlineKeyboardButton(
            "🏠 بازگشت",
            callback_data="home"
        )
    ])


    return InlineKeyboardMarkup(rows)



# =========================
# ABOUT
# =========================


async def about_page(query):

    await query.edit_message_text(
f"""
⚡️ کافی‌نت آنلاین 24

سامانه هوشمند ثبت و پیگیری خدمات آنلاین

📝 ثبت درخواست
🔎 پیگیری با کد رهگیری
💬 ارتباط با پشتیبانی
🚀 انجام خدمات ساده‌تر و سریع‌تر

📢 کانال رسمی:
{CHANNEL_LINK}

🤖 ربات:
{BOT_LINK}
""",
        reply_markup=home_keyboard()
    )



# =========================
# STATUS BUTTONS ADMIN
# =========================


def status_keyboard(code):

    return InlineKeyboardMarkup([

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
        )
        ],

        [
        InlineKeyboardButton(
            "🔴 رد شد",
            callback_data=f"reject|{code}"
        )
        ]

    ])# =========================
# START
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    USER_STATES.pop(user.id,None)

    await update.message.reply_text(
        """
🌐 کافی‌نت آنلاین ۲۴

به سامانه خدمات آنلاین خوش آمدید.

📌 خدمت موردنظر خود را انتخاب کنید:
""",
        reply_markup=main_keyboard(user.id)
    )



# =========================
# CALLBACK HANDLER
# =========================

async def callback_handler(update:Update,
                           context:ContextTypes.DEFAULT_TYPE):

    query=update.callback_query
    await query.answer()

    user_id=query.from_user.id
    data=query.data


    # HOME

    if data=="home":

        USER_STATES.pop(user_id,None)

        await query.edit_message_text(
            "🌐 منوی اصلی کافی‌نت آنلاین ۲۴",
            reply_markup=main_keyboard(user_id)
        )
        return



    # ABOUT

    if data=="about":

        await about_page(query)
        return



    # ADMIN PANEL

    if data=="admin_panel":

        if user_id!=ADMIN_ID:
            return


        await query.edit_message_text(
            """
🛠 پنل مدیریت کافی‌نت آنلاین ۲۴

بخش مدیریت را انتخاب کنید:
""",
            reply_markup=admin_keyboard()
        )

        return



    # ADD REGISTRATION

    if data=="admin_add_reg":

        if user_id!=ADMIN_ID:
            return


        USER_STATES[ADMIN_ID]={
            "state":STATE_ADMIN_ADD_REG
        }


        await query.edit_message_text(
            "📝 نام ثبت‌نام جدید را ارسال کنید:"
        )

        return



    # SHOW REGISTRATIONS

    if data=="online_regs":


        regs=get_today_registrations()


        if not regs:

            text="""
📝 ثبت‌نام‌های آنلاین امروز

فعلاً ثبت‌نامی اضافه نشده است.
"""

        else:

            text="""
📝 ثبت‌نام‌های آنلاین امروز

مورد موردنظر را انتخاب کنید:
"""


        await query.edit_message_text(
            text,
            reply_markup=registrations_keyboard()
        )

        return



    # TRACKING

    if data=="tracking":

        USER_STATES[user_id]={
            "state":STATE_TRACKING
        }


        await query.edit_message_text(
            """
🔎 پیگیری درخواست

کد رهگیری خود را ارسال کنید:
"""
        )

        return



    # STATUS CHANGE ADMIN

    if user_id==ADMIN_ID:


        if "|" in data:

            action,code=data.split("|",1)

            status=None


            if action=="doing":
                status="🔵 در حال انجام"


            elif action=="done":
                status="🟢 انجام شد"


            elif action=="reject":
                status="🔴 رد شد"



            if status:


                update_status(
                    code,
                    status
                )


                request=get_request(code)


                if request:

                    try:

                        await context.bot.send_message(
                            request["user_id"],
                            f"""
🔔 وضعیت درخواست شما تغییر کرد

🎫 کد رهگیری:
{code}

📌 وضعیت جدید:
{status}
"""
                        )

                    except:
                        pass



                await query.edit_message_text(
                    query.message.text+
                    f"\n\n📌 وضعیت جدید: {status}"
                )

                return




# =========================
# TEXT HANDLER
# =========================

async def text_handler(update:Update,
                       context:ContextTypes.DEFAULT_TYPE):

    user=update.effective_user
    uid=user.id
    text=update.message.text.strip()


    state=USER_STATES.get(uid)


    if not state:

        return



    # ADMIN ADD REG

    if state["state"]==STATE_ADMIN_ADD_REG:


        if uid!=ADMIN_ID:
            return


        add_registration(text)

        USER_STATES.pop(uid,None)


        await update.message.reply_text(
            f"""
✅ ثبت‌نام اضافه شد

📝 {text}
""",
            reply_markup=main_keyboard(uid)
        )

        return



    # TRACKING

    if state["state"]==STATE_TRACKING:


        request=get_request(text)


        if not request:

            await update.message.reply_text(
                "❌ کد رهگیری پیدا نشد."
            )
            return



        if request["user_id"]!=uid and uid!=ADMIN_ID:

            await update.message.reply_text(
                "❌ این درخواست متعلق به شما نیست."
            )

            return



        USER_STATES.pop(uid,None)


        await send_request_details(
            uid,
            request,
            context
        )

        return




# =========================
# MAIN
# =========================

def main():

    init_db()


    app=Application.builder().token(
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



if __name__=="__main__":
    main()
