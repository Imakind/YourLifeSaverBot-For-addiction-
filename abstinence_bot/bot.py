from __future__ import annotations

import logging
import os
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, MenuButtonCommands, Update
from telegram.constants import ChatType
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .db import Database
from .moderation import contains_trigger, is_admin, try_delete
from .service import AbstinenceService, mention_name, utcnow
from .texts import MILESTONES, SOS_STEPS, random_fact, random_quote

LOGGER = logging.getLogger(__name__)


def load_env_file(path: str = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def parse_hhmm(value: str, fallback: time) -> time:
    try:
        hour, minute = value.split(":", 1)
        return time(hour=int(hour), minute=int(minute))
    except Exception:
        return fallback


def service(context: ContextTypes.DEFAULT_TYPE) -> AbstinenceService:
    return context.application.bot_data["service"]


def user_label(update: Update) -> str:
    user = update.effective_user
    if not user:
        return "участник"
    if user.username:
        return f"@{user.username}"
    return user.first_name or "участник"


def keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("SOS", callback_data="sos"),
                InlineKeyboardButton("Статус", callback_data="status"),
            ],
            [
                InlineKeyboardButton("Совет", callback_data="advice"),
                InlineKeyboardButton("History", callback_data="history"),
            ],
            [
                InlineKeyboardButton("Факт", callback_data="fact"),
                InlineKeyboardButton("Топ", callback_data="top"),
            ],
        ]
    )


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Status", callback_data="status"),
                InlineKeyboardButton("History", callback_data="history"),
            ],
            [
                InlineKeyboardButton("SOS", callback_data="sos"),
                InlineKeyboardButton("Advice", callback_data="advice"),
            ],
            [
                InlineKeyboardButton("Top", callback_data="top"),
                InlineKeyboardButton("Partner", callback_data="partner"),
            ],
            [
                InlineKeyboardButton("Fact", callback_data="fact"),
            ],
        ]
    )


async def ensure_registered(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.effective_chat:
        return
    user = update.effective_user
    svc = service(context)
    svc.upsert_user(user.id, user.username, user.first_name, user.last_name)
    svc.join_chat(update.effective_chat.id, user.id)


def format_status(stats) -> str:
    return (
        f"Текущий streak: {stats.current_days} дн.\n"
        f"Рекорд: {stats.best_days} дн.\n"
        f"Среднее до срыва: {stats.average_days:.1f} дн.\n"
        f"Старт текущего периода: {stats.started_at.date().isoformat()}"
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_registered(update, context)
    text = (
        "Бот трекинга воздержания для чата.\n\n"
        "Основное:\n"
        "/status - streak, рекорд, среднее\n"
        "/setday N - выставить текущий день, например /setday 12\n"
        "/reset причина - сброс с причиной\n"
        "/note текст - заметка на текущий день\n"
        "/history - срывы и заметки\n"
        "/top - топ участников\n"
        "/partner - напарник\n"
        "/sos - протокол на пик тяги\n"
        "/advice - совет\n"
        "/fact - факт\n"
        "/report причина - пожаловаться на сообщение ответом"
    )
    await update.effective_message.reply_text(text, reply_markup=keyboard())


async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_registered(update, context)
    await update.effective_message.reply_text("Меню бота:", reply_markup=main_menu_keyboard())


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_registered(update, context)
    stats = service(context).stats(update.effective_chat.id, update.effective_user.id)
    await update.effective_message.reply_text(format_status(stats), reply_markup=keyboard())


async def setday(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_registered(update, context)
    raw = context.args[0] if context.args else ""
    if not raw.isdigit():
        await update.effective_message.reply_text("Формат: /setday 12")
        return
    days = int(raw)
    try:
        service(context).set_current_day(update.effective_chat.id, update.effective_user.id, days)
    except ValueError:
        await update.effective_message.reply_text("День должен быть от 0 до 10000.")
        return
    await update.effective_message.reply_text(
        f"Текущий streak выставлен: {days} дн.",
        reply_markup=main_menu_keyboard(),
    )


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_registered(update, context)
    reason = " ".join(context.args).strip()
    if not reason:
        await update.effective_message.reply_text("Укажи причину: /reset стресс, ночь, телефон в кровати")
        return
    days = service(context).reset(update.effective_chat.id, update.effective_user.id, reason)
    await update.effective_message.reply_text(
        f"Сброс зафиксирован: {days} дн.\nПричина: {reason[:500]}\nНовый период начат сейчас."
    )


async def note(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_registered(update, context)
    body = " ".join(context.args).strip()
    if not body:
        await update.effective_message.reply_text("Формат: /note что было триггером и что помогло")
        return
    day = service(context).add_note(update.effective_chat.id, update.effective_user.id, body)
    await update.effective_message.reply_text(f"Заметка сохранена на день {day}.")


async def history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_registered(update, context)
    text = format_history(service(context), update.effective_chat.id, update.effective_user.id)
    await update.effective_message.reply_text(text, reply_markup=main_menu_keyboard())


def format_history(svc: AbstinenceService, chat_id: int, user_id: int) -> str:
    relapses, notes = svc.history(chat_id, user_id)
    lines = ["История срывов:"]
    if relapses:
        lines.extend([f"- {r['relapse_at'][:10]}: {r['days']} дн.; {r['reason']}" for r in relapses])
    else:
        lines.append("- нет записей")
    lines.append("\nЗаметки:")
    if notes:
        lines.extend([f"- день {n['day_number']} ({n['note_date']}): {n['body']}" for n in notes])
    else:
        lines.append("- нет записей")
    return "\n".join(lines)


async def top(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_registered(update, context)
    text = format_top(service(context), update.effective_chat.id)
    await update.effective_message.reply_text(text, reply_markup=main_menu_keyboard())


def format_top(svc: AbstinenceService, chat_id: int) -> str:
    rows = svc.top(chat_id)
    if not rows:
        return "Пока нет участников."
    lines = ["Топ участников:"]
    lines.extend([f"{idx}. {row['name']} - {row['current_days']} дн. (рекорд {row['best_days']})" for idx, row in enumerate(rows, 1)])
    return "\n".join(lines)


async def partner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_registered(update, context)
    args = [arg.lower() for arg in context.args]
    svc = service(context)
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if args and args[0] in {"off", "выкл"}:
        svc.set_partner_opt_in(chat_id, user_id, False)
        await update.effective_message.reply_text("Подбор напарника отключен.")
        return
    if args and args[0] in {"on", "вкл"}:
        svc.set_partner_opt_in(chat_id, user_id, True)
        await update.effective_message.reply_text("Подбор напарника включен.")
        return
    found = svc.find_partner(chat_id, user_id)
    if not found:
        await update.effective_message.reply_text("Свободный напарник не найден. Попроси участника написать /start и /partner.")
        return
    await update.effective_message.reply_text(f"Твой напарник: {mention_name(found)}. Договоритесь о коротком ежедневном чек-ине.")


async def sos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_registered(update, context)
    text = "SOS-протокол на дофаминовом пике:\n" + "\n".join(SOS_STEPS)
    buttons = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Я выдержал 10 минут", callback_data="survived_10")],
            [InlineKeyboardButton("Дай еще совет", callback_data="advice")],
        ]
    )
    await update.effective_message.reply_text(text, reply_markup=buttons)


async def advice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_registered(update, context)
    body = " ".join(context.args).strip()
    svc = service(context)
    if body:
        svc.add_advice(update.effective_chat.id, update.effective_user.id, body)
        await update.effective_message.reply_text("Совет сохранён и будет попадать в /advice.")
        return
    await update.effective_message.reply_text(svc.random_advice(update.effective_chat.id))


async def fact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_registered(update, context)
    await update.effective_message.reply_text(random_fact())


async def quote(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_registered(update, context)
    await update.effective_message.reply_text(random_quote())


async def report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message.reply_to_message:
        await update.effective_message.reply_text("Используй /report ответом на сообщение.")
        return
    reason = " ".join(context.args).strip() or "жалоба участника"
    target = update.effective_message.reply_to_message.from_user
    if not target:
        await update.effective_message.reply_text("Не удалось определить автора сообщения.")
        return
    service(context).add_warning(update.effective_chat.id, target.id, update.effective_user.id, reason)
    await update.effective_message.reply_text("Жалоба сохранена. Модератор может удалить сообщение или выдать санкции.")


async def warn(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat.type == ChatType.PRIVATE:
        await update.effective_message.reply_text("Команда работает в группе.")
        return
    if not await is_admin(context, update.effective_chat.id, update.effective_user.id):
        await update.effective_message.reply_text("Команда доступна администраторам.")
        return
    if not update.effective_message.reply_to_message or not update.effective_message.reply_to_message.from_user:
        await update.effective_message.reply_text("Используй /warn причина ответом на сообщение.")
        return
    reason = " ".join(context.args).strip() or "нарушение правил чата"
    target = update.effective_message.reply_to_message.from_user
    service(context).add_warning(update.effective_chat.id, target.id, update.effective_user.id, reason)
    await update.effective_message.reply_text(f"Предупреждение сохранено для {target.mention_html()}.", parse_mode="HTML")


async def delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat.type == ChatType.PRIVATE:
        return
    if not await is_admin(context, update.effective_chat.id, update.effective_user.id):
        await update.effective_message.reply_text("Команда доступна администраторам.")
        return
    target_message = update.effective_message.reply_to_message
    if not target_message:
        await update.effective_message.reply_text("Используй /delete ответом на сообщение.")
        return
    deleted = await try_delete(target_message)
    await update.effective_message.reply_text("Сообщение удалено." if deleted else "Не удалось удалить сообщение. Проверь права бота.")


async def moderate_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not message or not message.text or update.effective_chat.type == ChatType.PRIVATE:
        return
    if not contains_trigger(message.text):
        return
    deleted = await try_delete(message)
    warning = "Триггерное сообщение скрыто." if deleted else "Обнаружено триггерное сообщение. Нужны права админа для удаления."
    await context.bot.send_message(chat_id=update.effective_chat.id, text=warning)


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not query.message:
        return
    if query.data == "sos":
        await query.message.reply_text("SOS-протокол на дофаминовом пике:\n" + "\n".join(SOS_STEPS))
    elif query.data == "status":
        stats = service(context).stats(query.message.chat_id, query.from_user.id)
        if stats is None:
            await query.message.reply_text("Сначала напиши /start.")
        else:
            await query.message.reply_text(format_status(stats), reply_markup=main_menu_keyboard())
    elif query.data == "history":
        svc = service(context)
        svc.upsert_user(query.from_user.id, query.from_user.username, query.from_user.first_name, query.from_user.last_name)
        svc.join_chat(query.message.chat_id, query.from_user.id)
        await query.message.reply_text(format_history(svc, query.message.chat_id, query.from_user.id), reply_markup=main_menu_keyboard())
    elif query.data == "top":
        await query.message.reply_text(format_top(service(context), query.message.chat_id), reply_markup=main_menu_keyboard())
    elif query.data == "partner":
        svc = service(context)
        svc.upsert_user(query.from_user.id, query.from_user.username, query.from_user.first_name, query.from_user.last_name)
        svc.join_chat(query.message.chat_id, query.from_user.id)
        found = svc.find_partner(query.message.chat_id, query.from_user.id)
        if not found:
            await query.message.reply_text("Свободный напарник не найден. Попроси участника написать /start и /partner.")
        else:
            await query.message.reply_text(f"Твой напарник: {mention_name(found)}. Договоритесь о коротком ежедневном чек-ине.")
    elif query.data == "advice":
        await query.message.reply_text(service(context).random_advice(query.message.chat_id))
    elif query.data == "fact":
        await query.message.reply_text(random_fact())
    elif query.data == "survived_10":
        svc = service(context)
        svc.upsert_user(query.from_user.id, query.from_user.username, query.from_user.first_name, query.from_user.last_name)
        svc.join_chat(query.message.chat_id, query.from_user.id)
        day = svc.add_note(query.message.chat_id, query.from_user.id, "SOS: выдержал 10 минут")
        await query.message.reply_text(f"Отмечено. День {day}: пик пережит.")


async def daily_message(context: ContextTypes.DEFAULT_TYPE) -> None:
    kind = context.job.data["kind"]
    svc = service(context)
    quote_or_fact = random_quote() if kind == "morning" else random_fact()
    prefix = "Утренний чек-ин" if kind == "morning" else "Вечерний чек-ин"
    chat_ids = sorted({row["chat_id"] for row in svc.active_tracking_rows()})
    for chat_id in chat_ids:
        await context.bot.send_message(chat_id=chat_id, text=f"{prefix}:\n{quote_or_fact}\n/status - проверить прогресс")


async def milestone_scan(context: ContextTypes.DEFAULT_TYPE) -> None:
    svc = service(context)
    for row in svc.due_milestones(utcnow(), set(MILESTONES)):
        await context.bot.send_message(
            chat_id=row["chat_id"],
            text=f"{row['name']}, milestone {row['days']} дн.\n{MILESTONES[row['days']]}",
        )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    LOGGER.exception("Unhandled bot error", exc_info=context.error)


async def setup_bot_menu(app: Application) -> None:
    commands = [
        BotCommand("menu", "главное меню"),
        BotCommand("status", "streak, рекорд, среднее"),
        BotCommand("setday", "выставить текущий день"),
        BotCommand("history", "история срывов и заметок"),
        BotCommand("note", "заметка на текущий день"),
        BotCommand("reset", "сброс streak с причиной"),
        BotCommand("sos", "SOS-протокол"),
        BotCommand("advice", "получить или добавить совет"),
        BotCommand("top", "топ участников"),
        BotCommand("partner", "напарник"),
    ]
    await app.bot.set_my_commands(commands)
    await app.bot.set_chat_menu_button(menu_button=MenuButtonCommands())


def build_application(token: str, db_path: str, tz_name: str, morning: str, evening: str) -> Application:
    db = Database(db_path)
    app = Application.builder().token(token).post_init(setup_bot_menu).build()
    app.bot_data["service"] = AbstinenceService(db)

    app.add_handler(CommandHandler(["start", "join"], start))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("setday", setday))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("note", note))
    app.add_handler(CommandHandler("history", history))
    app.add_handler(CommandHandler("top", top))
    app.add_handler(CommandHandler("partner", partner))
    app.add_handler(CommandHandler("sos", sos))
    app.add_handler(CommandHandler("advice", advice))
    app.add_handler(CommandHandler("fact", fact))
    app.add_handler(CommandHandler("quote", quote))
    app.add_handler(CommandHandler("report", report))
    app.add_handler(CommandHandler("warn", warn))
    app.add_handler(CommandHandler("delete", delete))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, moderate_message))
    app.add_error_handler(error_handler)

    tz = ZoneInfo(tz_name)
    app.job_queue.run_daily(daily_message, parse_hhmm(morning, time(9, 0, tzinfo=tz)).replace(tzinfo=tz), data={"kind": "morning"})
    app.job_queue.run_daily(daily_message, parse_hhmm(evening, time(21, 0, tzinfo=tz)).replace(tzinfo=tz), data={"kind": "evening"})
    app.job_queue.run_repeating(milestone_scan, interval=3600, first=30)
    return app


def main() -> None:
    logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
    load_env_file()
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise SystemExit("BOT_TOKEN is required")
    db_path = os.getenv("BOT_DB_PATH", "bot.sqlite3")
    tz_name = os.getenv("BOT_TZ", "Asia/Qyzylorda")
    morning = os.getenv("MORNING_NOTIFY", "09:00")
    evening = os.getenv("EVENING_NOTIFY", "21:00")
    app = build_application(token, db_path, tz_name, morning, evening)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
