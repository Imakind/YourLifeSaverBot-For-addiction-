from __future__ import annotations

import base64
import json
import os
import time
from typing import Any

from .dynamo_store import DynamoStore, mention_name, utcnow
from .telegram_api import TelegramClient
from .texts import MILESTONES, SOS_STEPS, TRIGGER_WORDS, random_fact, random_quote


COMMAND_COOLDOWN_SECONDS = 2.0
CALLBACK_COOLDOWN_SECONDS = 1.0
_RATE_LIMITS: dict[tuple[str, int, int, str], float] = {}


def response(status_code: int = 200, body: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body or {"ok": True}),
    }


def menu_keyboard() -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {"text": "Status", "callback_data": "status"},
                {"text": "History", "callback_data": "history"},
            ],
            [
                {"text": "SOS", "callback_data": "sos"},
                {"text": "Advice", "callback_data": "advice"},
            ],
            [
                {"text": "Top", "callback_data": "top"},
                {"text": "Partner", "callback_data": "partner"},
            ],
            [{"text": "Fact", "callback_data": "fact"}],
        ]
    }


def sos_keyboard() -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [{"text": "Я выдержал 10 минут", "callback_data": "survived_10"}],
            [{"text": "Дай еще совет", "callback_data": "advice"}],
        ]
    }


def format_status(stats: Any) -> str:
    return (
        f"Текущий streak: {stats.current_days} дн.\n"
        f"Рекорд: {stats.best_days} дн.\n"
        f"Среднее до срыва: {stats.average_days:.1f} дн.\n"
        f"Старт текущего периода: {stats.started_at.date().isoformat()}"
    )


def format_history(store: DynamoStore, chat_id: int, user_id: int) -> str:
    relapses, notes = store.history(chat_id, user_id)
    lines = ["История срывов:"]
    if relapses:
        lines.extend([f"- {item['relapse_at'][:10]}: {item['days']} дн.; {item['reason']}" for item in relapses])
    else:
        lines.append("- нет записей")
    lines.append("\nЗаметки:")
    if notes:
        lines.extend([f"- день {item['day_number']} ({item['note_date']}): {item['body']}" for item in notes])
    else:
        lines.append("- нет записей")
    return "\n".join(lines)


def format_top(store: DynamoStore, chat_id: int) -> str:
    rows = store.top(chat_id)
    if not rows:
        return "Пока нет участников."
    lines = ["Топ участников:"]
    lines.extend(
        [f"{idx}. {row['name']} - {row['current_days']} дн. (рекорд {row['best_days']})" for idx, row in enumerate(rows, 1)]
    )
    return "\n".join(lines)


def normalize_user(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(user["id"]),
        "username": user.get("username"),
        "first_name": user.get("first_name"),
        "last_name": user.get("last_name"),
    }


def register(store: DynamoStore, chat_id: int, user: dict[str, Any]) -> None:
    store.upsert_user(chat_id, normalize_user(user))


def command_parts(text: str) -> tuple[str, str]:
    first, _, rest = text.strip().partition(" ")
    command = first.split("@", 1)[0].lstrip("/").lower()
    return command, rest.strip()


def contains_trigger(text: str) -> bool:
    lower = text.lower()
    return any(word in lower for word in TRIGGER_WORDS)


def is_rate_limited(kind: str, chat_id: int, user_id: int, action: str, cooldown: float) -> bool:
    now = time.monotonic()
    key = (kind, chat_id, user_id, action)
    last = _RATE_LIMITS.get(key)
    if last is not None and now - last < cooldown:
        return True
    _RATE_LIMITS[key] = now
    if len(_RATE_LIMITS) > 2000:
        stale_before = now - 60
        for item_key, item_last in list(_RATE_LIMITS.items()):
            if item_last < stale_before:
                _RATE_LIMITS.pop(item_key, None)
    return False


def delete_user_command(tg: TelegramClient, chat_id: int, message: dict[str, Any]) -> None:
    try:
        tg.delete_message(chat_id, int(message["message_id"]))
    except Exception:
        pass


def edit_or_send(
    tg: TelegramClient,
    chat_id: int,
    message_id: int | None,
    text: str,
    reply_markup: dict[str, Any] | None = None,
) -> None:
    if message_id is not None:
        try:
            tg.edit_message_text(chat_id, message_id, text, reply_markup)
            return
        except Exception:
            pass
    tg.send_message(chat_id, text, reply_markup)


def start_text() -> str:
    return (
        "Бот трекинга воздержания для чата.\n\n"
        "Команды:\n"
        "/status - streak, рекорд, среднее\n"
        "/setday N - выставить текущий день, например /setday 12\n"
        "/history - срывы и заметки\n"
        "/reset причина - сброс с причиной\n"
        "/note текст - заметка на текущий день\n"
        "/advice - получить совет\n"
        "/advice текст - добавить совет\n"
        "/sos - протокол на пик тяги"
    )


def handle_command(store: DynamoStore, tg: TelegramClient, message: dict[str, Any]) -> None:
    chat_id = int(message["chat"]["id"])
    user = normalize_user(message["from"])
    text = message.get("text", "")
    command, arg = command_parts(text)
    delete_user_command(tg, chat_id, message)
    if is_rate_limited("command", chat_id, user["id"], command, COMMAND_COOLDOWN_SECONDS):
        return
    register(store, chat_id, user)

    if command in {"start", "join"}:
        tg.send_message(chat_id, start_text(), menu_keyboard())
    elif command == "status":
        stats = store.stats(chat_id, user["id"])
        tg.send_message(chat_id, format_status(stats), menu_keyboard())
    elif command == "setday":
        if not arg.isdigit():
            tg.send_message(chat_id, "Формат: /setday 12")
            return
        days = int(arg)
        try:
            store.set_current_day(chat_id, user["id"], days)
        except PermissionError:
            tg.send_message(chat_id, "Текущий день уже был выставлен. /setday можно использовать только один раз.")
            return
        except ValueError:
            tg.send_message(chat_id, "День должен быть от 0 до 10000.")
            return
        tg.send_message(chat_id, f"Текущий streak выставлен: {days} дн.", menu_keyboard())
    elif command == "reset":
        if not arg:
            tg.send_message(chat_id, "Укажи причину: /reset стресс, ночь, телефон в кровати")
            return
        days = store.reset(chat_id, user["id"], arg)
        tg.send_message(chat_id, f"Сброс зафиксирован: {days} дн.\nПричина: {arg[:500]}\nНовый период начат сейчас.")
    elif command == "note":
        if not arg:
            tg.send_message(chat_id, "Формат: /note что было триггером и что помогло")
            return
        day = store.add_note(chat_id, user["id"], arg)
        tg.send_message(chat_id, f"Заметка сохранена на день {day}.")
    elif command == "history":
        tg.send_message(chat_id, format_history(store, chat_id, user["id"]), menu_keyboard())
    elif command == "top":
        tg.send_message(chat_id, format_top(store, chat_id), menu_keyboard())
    elif command == "partner":
        if arg.lower() in {"off", "выкл"}:
            store.set_partner_opt_in(chat_id, user["id"], False)
            tg.send_message(chat_id, "Подбор напарника отключен.")
            return
        if arg.lower() in {"on", "вкл"}:
            store.set_partner_opt_in(chat_id, user["id"], True)
            tg.send_message(chat_id, "Подбор напарника включен.")
            return
        found = store.find_partner(chat_id, user["id"])
        if not found:
            tg.send_message(chat_id, "Свободный напарник не найден. Попроси участника написать /start и /partner.")
        else:
            tg.send_message(chat_id, f"Твой напарник: {mention_name(found)}. Договоритесь о коротком ежедневном отчете.")
    elif command == "sos":
        tg.send_message(chat_id, "SOS-протокол на дофаминовом пике:\n" + "\n".join(SOS_STEPS), sos_keyboard())
    elif command == "advice":
        if arg:
            store.add_advice(chat_id, user["id"], arg)
            tg.send_message(chat_id, "Совет сохранён и будет попадать в /advice.")
        else:
            tg.send_message(chat_id, store.random_advice(chat_id))
    elif command == "fact":
        tg.send_message(chat_id, random_fact())
    elif command == "quote":
        tg.send_message(chat_id, random_quote())
    elif command == "report":
        target = message.get("reply_to_message", {}).get("from")
        if not target:
            tg.send_message(chat_id, "Используй /report ответом на сообщение.")
            return
        store.add_warning(chat_id, int(target["id"]), user["id"], arg or "жалоба участника")
        tg.send_message(chat_id, "Жалоба сохранена.")


def handle_plain_text(store: DynamoStore, tg: TelegramClient, message: dict[str, Any]) -> None:
    chat_id = int(message["chat"]["id"])
    text = message.get("text", "")
    if not contains_trigger(text):
        return
    try:
        tg.delete_message(chat_id, int(message["message_id"]))
        tg.send_message(chat_id, "Триггерное сообщение скрыто.")
    except Exception:
        tg.send_message(chat_id, "Обнаружено триггерное сообщение. Нужны права админа для удаления.")


def handle_callback(store: DynamoStore, tg: TelegramClient, callback: dict[str, Any]) -> None:
    data = callback.get("data", "")
    message = callback.get("message") or {}
    chat_id = int(message["chat"]["id"])
    message_id = int(message["message_id"]) if message.get("message_id") is not None else None
    user = normalize_user(callback["from"])
    if is_rate_limited("callback", chat_id, user["id"], data, CALLBACK_COOLDOWN_SECONDS):
        tg.answer_callback_query(callback["id"], "Подожди секунду.")
        return
    tg.answer_callback_query(callback["id"])
    register(store, chat_id, user)

    if data == "status":
        stats = store.stats(chat_id, user["id"])
        edit_or_send(tg, chat_id, message_id, format_status(stats), menu_keyboard())
    elif data == "history":
        edit_or_send(tg, chat_id, message_id, format_history(store, chat_id, user["id"]), menu_keyboard())
    elif data == "top":
        edit_or_send(tg, chat_id, message_id, format_top(store, chat_id), menu_keyboard())
    elif data == "partner":
        found = store.find_partner(chat_id, user["id"])
        if not found:
            edit_or_send(tg, chat_id, message_id, "Свободный напарник не найден. Попроси участника написать /start и /partner.", menu_keyboard())
        else:
            edit_or_send(tg, chat_id, message_id, f"Твой напарник: {mention_name(found)}. Договоритесь о коротком ежедневном отчете.", menu_keyboard())
    elif data == "sos":
        edit_or_send(tg, chat_id, message_id, "SOS-протокол на дофаминовом пике:\n" + "\n".join(SOS_STEPS), sos_keyboard())
    elif data == "advice":
        edit_or_send(tg, chat_id, message_id, store.random_advice(chat_id), menu_keyboard())
    elif data == "fact":
        edit_or_send(tg, chat_id, message_id, random_fact(), menu_keyboard())
    elif data == "survived_10":
        day = store.add_note(chat_id, user["id"], "SOS: выдержал 10 минут")
        edit_or_send(tg, chat_id, message_id, f"Отмечено. День {day}: пик пережит.", sos_keyboard())


def parse_body(event: dict[str, Any]) -> dict[str, Any]:
    body = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        body = base64.b64decode(body).decode("utf-8")
    return json.loads(body)


def check_secret(event: dict[str, Any]) -> bool:
    expected = os.getenv("WEBHOOK_SECRET")
    if not expected:
        return True
    headers = {key.lower(): value for key, value in (event.get("headers") or {}).items()}
    return headers.get("x-telegram-bot-api-secret-token") == expected


def webhook_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    if not check_secret(event):
        return response(403, {"ok": False})
    update = parse_body(event)
    store = DynamoStore()
    tg = TelegramClient(os.environ["BOT_TOKEN"])

    if "callback_query" in update:
        handle_callback(store, tg, update["callback_query"])
    elif "message" in update:
        message = update["message"]
        text = message.get("text", "")
        if text.startswith("/"):
            handle_command(store, tg, message)
        else:
            handle_plain_text(store, tg, message)
    return response()


def schedule_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    store = DynamoStore()
    tg = TelegramClient(os.environ["BOT_TOKEN"])
    kind = event.get("kind", "milestones")

    if kind in {"morning", "evening"}:
        return response()

    for row in store.due_milestones(utcnow(), set(MILESTONES)):
        tg.send_message(
            int(row["chat_id"]),
            f"{row['name']}, milestone {row['days']} дн.\n{MILESTONES[int(row['days'])]}",
        )
    return response()


def setup_webhook_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    api_url = os.environ["WEBHOOK_URL"]
    tg = TelegramClient(os.environ["BOT_TOKEN"])
    tg.set_my_commands(
        [
            {"command": "start", "description": "зарегистрироваться"},
            {"command": "status", "description": "streak, рекорд, среднее"},
            {"command": "setday", "description": "выставить текущий день"},
            {"command": "history", "description": "история срывов и заметок"},
            {"command": "note", "description": "заметка на текущий день"},
            {"command": "reset", "description": "сброс streak с причиной"},
            {"command": "sos", "description": "SOS-протокол"},
            {"command": "advice", "description": "получить или добавить совет"},
            {"command": "top", "description": "топ участников"},
            {"command": "partner", "description": "напарник"},
        ]
    )
    tg.set_chat_menu_button()
    result = tg.set_webhook(api_url, os.getenv("WEBHOOK_SECRET"))
    return response(200, result)
