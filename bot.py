from pathlib import Path
import ast

src = Path("/mnt/data/bot.py")
code = src.read_text(encoding="utf-8")

# Verify the uploaded bot is syntactically valid before making any changes.
ast.parse(code)

# The requested behaviour is already present in the original online-registration
# functions: registrations are loaded dynamically from the database. We only
# ensure the online-registration section contains no hardcoded service categories.
# No unrelated code is changed.
start_marker = "# =========================\n# ONLINE REGISTRATIONS\n# ========================="
start = code.index(start_marker)
next_marker = "# =========================\n# CALLBACK HANDLER\n# ========================="
end = code.index(next_marker, start)

online_section = '''# =========================
# ONLINE REGISTRATIONS
# =========================
async def show_online_registrations(query):
    registrations = get_today_registrations()

    if registrations:
        text = (
            "📝 ثبت‌نام‌های آنلاین امروز\\n\\n"
            "ثبت‌نام موردنظر خود را انتخاب کنید:"
        )
    else:
        text = (
            "📝 ثبت‌نام‌های آنلاین امروز\\n\\n"
            "فعلاً ثبت‌نامی برای امروز ثبت نشده است.\\n"
            "در صورت نبودن ثبت‌نام موردنظر، گزینه "
            "«➕ سایر ثبت‌نام‌ها» را انتخاب کنید."
        )

    await query.edit_message_text(
        text,
        reply_markup=registrations_keyboard(),
    )


async def select_registration(query, reg_id):
    registration = get_registration(reg_id)

    if not registration:
        await query.answer(
            "این ثبت‌نام فعال نیست.",
            show_alert=True,
        )
        return

    USER_STATES[query.from_user.id] = {
        "state": STATE_NAME,
        "category": "📝 ثبت‌نام‌های آنلاین",
        "service": registration["title"],
    }

    await query.edit_message_text(
        f"📝 ثبت‌نام: {registration['title']}\\n\\n"
        "👤 لطفاً نام و نام خانوادگی خود را ارسال کنید:"
    )


async def other_registration(query):
    USER_STATES[query.from_user.id] = {
        "state": STATE_NAME,
        "category": "📝 ثبت‌نام‌های آنلاین",
        "service": "➕ سایر ثبت‌نام‌ها",
    }

    await query.edit_message_text(
        "➕ سایر ثبت‌نام‌ها\\n\\n"
        "ثبت‌نام موردنظر شما در فهرست امروز نیست.\\n\\n"
        "👤 لطفاً نام و نام خانوادگی خود را ارسال کنید:"
    )


'''

new_code = code[:start] + online_section + code[end:]
ast.parse(new_code)

out = Path("/mnt/data/bot_exact_fixed.py")
out.write_text(new_code, encoding="utf-8")
print(f"نسخه آماده شد: {out}")
print(f"خطوط: {len(new_code.splitlines())}")
