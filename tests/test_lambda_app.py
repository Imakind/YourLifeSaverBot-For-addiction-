from __future__ import annotations

from dataclasses import dataclass

from abstinence_bot.lambda_app import handle_callback, handle_command


@dataclass
class FakeStats:
    current_days: int = 3
    best_days: int = 7
    average_days: float = 4.0

    @property
    def started_at(self):
        from datetime import datetime, timezone

        return datetime(2026, 5, 1, tzinfo=timezone.utc)


class FakeStore:
    def __init__(self) -> None:
        self.users = []
        self.advices = []

    def upsert_user(self, chat_id, user):
        self.users.append((chat_id, user))

    def stats(self, chat_id, user_id):
        return FakeStats()

    def add_advice(self, chat_id, user_id, body):
        self.advices.append((chat_id, user_id, body))

    def random_advice(self, chat_id):
        return self.advices[-1][2] if self.advices else "fallback advice"

    def history(self, chat_id, user_id):
        return [], []

    def top(self, chat_id):
        return []

    def find_partner(self, chat_id, user_id):
        return None


class FakeTelegram:
    def __init__(self) -> None:
        self.messages = []
        self.callbacks = []

    def send_message(self, chat_id, text, reply_markup=None, parse_mode=None):
        self.messages.append(
            {"chat_id": chat_id, "text": text, "reply_markup": reply_markup, "parse_mode": parse_mode}
        )

    def answer_callback_query(self, callback_query_id, text=None):
        self.callbacks.append((callback_query_id, text))


def message(text: str):
    return {
        "message_id": 10,
        "chat": {"id": 100},
        "from": {"id": 1, "username": "alice", "first_name": "Alice"},
        "text": text,
    }


def test_start_command_sends_menu():
    store = FakeStore()
    tg = FakeTelegram()

    handle_command(store, tg, message("/start"))

    assert store.users[0][0] == 100
    assert "Бот трекинга" in tg.messages[0]["text"]
    assert tg.messages[0]["reply_markup"]["inline_keyboard"]


def test_advice_command_saves_user_advice():
    store = FakeStore()
    tg = FakeTelegram()

    handle_command(store, tg, message("/advice Leave the room"))
    handle_command(store, tg, message("/advice"))

    assert store.advices == [(100, 1, "Leave the room")]
    assert tg.messages[-1]["text"] == "Leave the room"


def test_history_callback_answers_and_sends_history():
    store = FakeStore()
    tg = FakeTelegram()
    callback = {
        "id": "cb1",
        "data": "history",
        "from": {"id": 1, "username": "alice", "first_name": "Alice"},
        "message": {"chat": {"id": 100}, "message_id": 10},
    }

    handle_callback(store, tg, callback)

    assert tg.callbacks == [("cb1", None)]
    assert "История срывов" in tg.messages[0]["text"]
