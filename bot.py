import os
import logging
from datetime import datetime

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# =========================
# تنظیمات
# =========================

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set.")

if not ADMIN_ID:
    raise RuntimeError("ADMIN_ID is not set.")

try:
    ADMIN_ID = int(ADMIN_ID)
except ValueError:
    raise RuntimeError("ADMIN_ID must be a number.")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# =========================
# وضعیت‌ها
# =========================

NAME, PHONE, TELEGRAM_ID, DESCRIPTION = range(4)

requests_data = {}
user_active_request = {}

request_counter = 1000


# =========================
# متن‌ها
# =========================

WELCOME_TEXT = """
👋 به «کافی‌نت آنلاین ۲۴» خوش آمدید.

خدمات آنلاین و ثبت‌نام‌های اینترنتی را به‌صورت غیرحضوری انجام دهید.

لطفاً یکی از گزینه‌های زیر را انتخاب کنید:
"""


# =========================
# کیبورد اصلی
# =========================

def main_menu():
    keyboard = [
        [
            InlineKeyboardButton(
                "📝 ثبت‌نام اینترنتی",
                callback_data="online_registration"
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
            )
        ],
        [
            InlineKeyboardButton(
                "📢 اطلاعیه‌ها",
                callback_data="announcements"
            ),
            InlineKeyboardButton(
                "ℹ️ درباره ما",
                callback_data="about"
            ),
        ],
    ]

    return InlineKeyboardMarkup(keyboard)


# =========================
# خدمات
# =========================

def services_menu():
    keyboard = [
        [
            InlineKeyboardButton(
                "📝 ثبت‌نام اینترنتی",
                callback_data="registration_list"
            )
        ],
        [
            InlineKeyboardButton(
                "💰 مالیاتی 🔒",
                callback_data="coming_soon"
            ),
            InlineKeyboardButton(
                "🛡️ بیمه 🔒",
                callback_data="coming_soon"
            ),
        ],
        [
            InlineKeyboardButton(
                "⚖️ قضایی 🔒",
                callback_data="coming_soon"
            ),
            InlineKeyboardButton(
                "🏦 بانکی 🔒",
                callback_data="coming_soon"
            ),
        ],
        [
            InlineKeyboardButton(
                "💳 وام 🔒",
                callback_data="coming_soon"
            ),
            InlineKeyboardButton(
                "🏥 درمانی 🔒",
                callback_data="coming_soon"
            ),
        ],
        [
            InlineKeyboardButton(
                "🎫 بلیط 🔒",
                callback_data="coming_soon"
            ),
            InlineKeyboardButton(
                "🧾 قبض 🔒",
                callback_data="coming_soon"
            ),
        ],
        [
            InlineKeyboardButton(
                "➕ دیگر خدمات 🔒",
                callback_data="coming_soon"
            )
        ],
        [
            InlineKeyboardButton(
                "🔙 بازگشت",
                callback_data="back_main"
            )
        ],
    ]

    return InlineKeyboardMarkup(keyboard)


# =========================
# شروع
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    text = WELCOME_TEXT

    if user:
        text += f"\n👤 سلام {user.first_name}!"

    await update.message.reply_text(
        text,
        reply_markup=main_menu()
    )


# =========================
# ثبت‌نام اینترنتی
# =========================

async def online_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "📝 بخش ثبت‌نام اینترنتی\n\n"
        "در حال حاضر ثبت‌نام‌های فعال این بخش در دسترس هستند.",
        reply_markup=services_menu()
    )


async def registration_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    keyboard = [
        [
            InlineKeyboardButton(
                "📝 ثبت درخواست ثبت‌نام",
                callback_data="start_request"
            )
        ],
        [
            InlineKeyboardButton(
                "🔙 بازگشت",
                callback_data="online_registration"
            )
        ],
    ]

    text = """
📝 ثبت‌نام اینترنتی

در حال حاضر امکان ثبت درخواست ثبت‌نام اینترنتی فعال است.

پس از ارسال درخواست، پشتیبانی آن را بررسی می‌کند و نتیجه از طریق همین ربات به شما اطلاع داده می‌شود.
"""

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# =========================
# شروع فرم
# =========================

async def start_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    context.user_data.clear()

    await query.message.reply_text(
        "📝 ثبت درخواست\n\n"
        "لطفاً نام و نام خانوادگی خود را وارد کنید:"
    )

    return NAME


# =========================
# نام
# =========================

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text.strip()

    await update.message.reply_text(
        "📱 لطفاً شماره همراه خود را ارسال کنید:",
        reply_markup=ReplyKeyboardMarkup(
            [
                [
                    KeyboardButton(
                        "📱 ارسال شماره همراه",
                        request_contact=True
                    )
                ]
            ],
            resize_keyboard=True,
            one_time_keyboard=True
        )
    )

    return PHONE


# =========================
# شماره
# =========================

async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.contact:
        phone = update.message.contact.phone_number
    else:
        phone = update.message.text.strip()

    context.user_data["phone"] = phone

    await update.message.reply_text(
        "🔹 آیدی تلگرام خود را وارد کنید.\n\n"
        "اگر آیدی ندارید یا نمی‌خواهید وارد کنید، روی «رد کردن» بزنید.",
        reply_markup=ReplyKeyboardMarkup(
            [["⏭️ رد کردن"]],
            resize_keyboard=True,
            one_time_keyboard=True
        )
    )

    return TELEGRAM_ID


# =========================
# آیدی تلگرام
# =========================

async def get_telegram_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if text == "⏭️ رد کردن":
        context.user_data["telegram_id"] = "ثبت نشده"
    else:
        context.user_data["telegram_id"] = text

    await update.message.reply_text(
        "📝 توضیحات درخواست را وارد کنید.\n\n"
        "اگر توضیح خاصی ندارید، «رد کردن» را بزنید.",
        reply_markup=ReplyKeyboardMarkup(
            [["⏭️ رد کردن"]],
            resize_keyboard=True,
            one_time_keyboard=True
        )
    )

    return DESCRIPTION


# =========================
# توضیحات و ثبت نهایی
# =========================

async def get_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global request_counter

    text = update.message.text.strip()

    if text == "⏭️ رد کردن":
        description = "بدون توضیحات"
    else:
        description = text

    request_counter += 1
    request_id = request_counter

    user = update.effective_user

    request = {
        "id": request_id,
        "user_id": user.id,
        "username": user.username or "ندارد",
        "name": context.user_data.get("name", ""),
        "phone": context.user_data.get("phone", ""),
        "telegram_id": context.user_data.get(
            "telegram_id",
            "ثبت نشده"
        ),
        "description": description,
        "status": "در انتظار بررسی",
        "created_at": datetime.now().strftime(
            "%Y/%m/%d - %H:%M"
        ),
    }

    requests_data[request_id] = request
    user_active_request[user.id] = request_id

    await update.message.reply_text(
        f"""
✅ درخواست شما با موفقیت ثبت شد.

🆔 شماره درخواست: #{request_id}

🟡 وضعیت: در انتظار بررسی

پس از بررسی درخواست توسط پشتیبانی، نتیجه از طریق همین ربات برای شما ارسال خواهد شد.
""",
        reply_markup=ReplyKeyboardMarkup(
            [["🏠 منوی اصلی"]],
            resize_keyboard=True
        )
    )

    admin_text = f"""
📥 درخواست جدید

🆔 درخواست: #{request_id}

👤 نام:
{request["name"]}

📱 شماره:
{request["phone"]}

🔹 آیدی تلگرام:
{request["telegram_id"]}

📝 توضیحات:
{request["description"]}

👤 Username:
@{request["username"]}

🕐 زمان:
{request["created_at"]}

🟡 وضعیت:
در انتظار بررسی
"""

    keyboard = [
        [
            InlineKeyboardButton(
                "✅ تأیید درخواست",
                callback_data=f"approve:{request_id}"
            ),
            InlineKeyboardButton(
                "❌ رد درخواست",
                callback_data=f"reject:{request_id}"
            ),
        ]
    ]

    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=admin_text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        logger.error("Could not send request to admin: %s", e)

    context.user_data.clear()

    return ConversationHandler.END


# =========================
# تأیید / رد درخواست
# =========================

async def request_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.from_user.id != ADMIN_ID:
        await query.answer(
            "⛔ شما دسترسی ندارید.",
            show_alert=True
        )
        return

    action, request_id_text = query.data.split(":")
    request_id = int(request_id_text)

    request = requests_data.get(request_id)

    if not request:
        await query.edit_message_text(
            "❌ این درخواست پیدا نشد."
        )
        return

    user_id = request["user_id"]

    if action == "approve":
        request["status"] = "تأیید شده"

        await query.edit_message_reply_markup(
            reply_markup=None
        )

        await query.message.reply_text(
            f"🟢 درخواست #{request_id} تأیید شد."
        )

        keyboard = [
            [
                InlineKeyboardButton(
                    "💬 شروع گفتگو با پشتیبانی",
                    callback_data=f"chat:{request_id}"
                )
            ]
        ]

        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"""
✅ درخواست شما تأیید شد.

🆔 درخواست: #{request_id}

🟢 وضعیت: تأیید شده

اکنون می‌توانید از طریق همین ربات با پشتیبانی در ارتباط باشید.
""",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception as e:
            logger.error("Could not notify user: %s", e)

    elif action == "reject":
        request["status"] = "رد شده"

        await query.edit_message_reply_markup(
            reply_markup=None
        )

        await query.message.reply_text(
            f"🔴 درخواست #{request_id} رد شد."
        )

        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"""
🔴 درخواست شما رد شد.

🆔 درخواست: #{request_id}

برای پیگیری بیشتر می‌توانید با پشتیبانی تماس بگیرید.
"""
            )
        except Exception as e:
            logger.error("Could not notify user: %s", e)


# =========================
# شروع چت
# =========================

async def start_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    request_id = int(query.data.split(":")[1])

    request = requests_data.get(request_id)

    if not request:
        await query.message.reply_text(
            "❌ درخواست پیدا نشد."
        )
        return

    if request["user_id"] != query.from_user.id:
        return

    context.user_data["chat_request_id"] = request_id

    await query.message.reply_text(
        f"""
💬 گفتگو با پشتیبانی فعال شد.

🆔 درخواست: #{request_id}

پیام خود را ارسال کنید تا برای پشتیبانی ارسال شود.

برای پایان گفتگو:
 /endchat
"""
    )


# =========================
# پیام‌های چت
# =========================

async def relay_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    # پیام ادمین به کاربر
    if user.id == ADMIN_ID:

        if not update.message:
            return

        text = update.message.text

        if not text:
            return

        request_id = context.user_data.get("admin_chat_request")

        if not request_id:
            return

        request = requests_data.get(request_id)

        if not request:
            return

        try:
            await context.bot.send_message(
                chat_id=request["user_id"],
                text=f"💬 پشتیبانی:\n\n{text}"
            )
        except Exception as e:
            logger.error("Admin relay error: %s", e)

        return

    # پیام کاربر
    request_id = context.user_data.get("chat_request_id")

    if not request_id:
        return

    request = requests_data.get(request_id)

    if not request:
        return

    if request["user_id"] != user.id:
        return

    text = update.message.text

    if not text:
        return

    admin_text = f"""
💬 پیام جدید کاربر

🆔 درخواست: #{request_id}

👤 {request["name"]}

📱 {request["phone"]}

پیام:

{text}
"""

    keyboard = [
        [
            InlineKeyboardButton(
                "💬 پاسخ",
                callback_data=f"adminchat:{request_id}"
            )
        ]
    ]

    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=admin_text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        await update.message.reply_text(
            "✅ پیام شما برای پشتیبانی ارسال شد."
        )

    except Exception as e:
        logger.error("User relay error: %s", e)


# =========================
# شروع چت ادمین
# =========================

async def admin_start_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.from_user.id != ADMIN_ID:
        return

    request_id = int(query.data.split(":")[1])

    request = requests_data.get(request_id)

    if not request:
        await query.message.reply_text(
            "❌ درخواست پیدا نشد."
        )
        return

    context.user_data["admin_chat_request"] = request_id

    await query.message.reply_text(
        f"""
💬 پاسخ به کاربر فعال شد.

🆔 درخواست: #{request_id}

پیام خود را ارسال کنید.
"""
    )


# =========================
# پایان چت
# =========================

async def end_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("chat_request_id", None)
    context.user_data.pop("admin_chat_request", None)

    await update.message.reply_text(
        "🔴 گفتگو پایان یافت."
    )


# =========================
# درخواست‌های من
# =========================

async def my_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id

    user_requests = [
        req for req in requests_data.values()
        if req["user_id"] == user_id
    ]

    if not user_requests:
        text = """
📋 درخواست‌های من

هنوز هیچ درخواستی ثبت نکرده‌اید.
"""
    else:
        text = "📋 درخواست‌های من\n\n"

        for req in user_requests[-10:]:
            text += (
                f"🆔 #{req['id']}\n"
                f"📌 وضعیت: {req['status']}\n"
                f"🕐 {req['created_at']}\n\n"
            )

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔙 بازگشت",
                    callback_data="back_main"
                )
            ]
        ])
    )


# =========================
# پشتیبانی
# =========================

async def support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        """
💬 پشتیبانی کافی‌نت آنلاین ۲۴

اگر درخواست فعالی دارید، ابتدا درخواست خود را ثبت کنید.

پس از تأیید درخواست، امکان گفتگو مستقیم با پشتیبانی از داخل ربات فعال می‌شود.
""",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "📝 ثبت درخواست",
                    callback_data="registration_list"
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 بازگشت",
                    callback_data="back_main"
                )
            ]
        ])
    )


# =========================
# درباره ما
# =========================

async def about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        """
ℹ️ درباره کافی‌نت آنلاین ۲۴

ارائه خدمات و ثبت‌نام‌های اینترنتی به‌صورت غیرحضوری.

درخواست خود را ثبت کنید و مراحل انجام آن را از طریق همین ربات پیگیری کنید.
""",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔙 بازگشت",
                    callback_data="back_main"
                )
            ]
        ])
    )


# =========================
# اطلاعیه‌ها
# =========================

async def announcements(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        """
📢 اطلاعیه‌ها

در حال حاضر اطلاعیه‌ای ثبت نشده است.
""",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔙 بازگشت",
                    callback_data="back_main"
                )
            ]
        ])
    )


# =========================
# خدمات غیرفعال
# =========================

async def coming_soon(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer(
        "این خدمت به‌زودی فعال می‌شود.",
        show_alert=True
    )


# =========================
# بازگشت
# =========================

async def back_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        WELCOME_TEXT,
        reply_markup=main_menu()
    )


# =========================
# دکمه منوی اصلی
# =========================

async def keyboard_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 منوی اصلی":
        await update.message.reply_text(
            WELCOME_TEXT,
            reply_markup=main_menu()
        )


# =========================
# اجرای ربات
# =========================

def main():
    application = Application.builder().token(BOT_TOKEN).build()

    conversation_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(
                start_request,
                pattern="^start_request$"
            )
        ],
        states={
            NAME: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    get_name
                )
            ],
            PHONE: [
                MessageHandler(
                    filters.CONTACT,
                    get_phone
                ),
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    get_phone
                ),
            ],
            TELEGRAM_ID: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    get_telegram_id
                )
            ],
            DESCRIPTION: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    get_description
                )
            ],
        },
        fallbacks=[],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("endchat", end_chat))

    application.add_handler(conversation_handler)

    application.add_handler(
        CallbackQueryHandler(
            request_action,
            pattern=r"^(approve|reject):\d+$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            start_chat,
            pattern=r"^chat:\d+$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            admin_start_chat,
            pattern=r"^adminchat:\d+$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            online_registration,
            pattern="^online_registration$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            registration_list,
            pattern="^registration_list$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            my_requests,
            pattern="^my_requests$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            support,
            pattern="^support$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            about,
            pattern="^about$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            announcements,
            pattern="^announcements$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            coming_soon,
            pattern="^coming_soon$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            back_main,
            pattern="^back_main$"
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            relay_message
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            keyboard_main
        )
    )

    logger.info("CafiNetOnline24 bot started.")

    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()
