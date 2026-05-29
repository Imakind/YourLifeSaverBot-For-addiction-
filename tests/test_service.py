from __future__ import annotations

from datetime import datetime, timezone

from abstinence_bot.db import Database
from abstinence_bot.service import AbstinenceService


def fixed(day: int) -> datetime:
    return datetime(2026, 5, day, 12, 0, tzinfo=timezone.utc)


def make_service(tmp_path):
    return AbstinenceService(Database(tmp_path / "test.sqlite3"))


def test_streak_reset_history_and_average(tmp_path):
    svc = make_service(tmp_path)
    svc.upsert_user(1, "alice", "Alice", None)
    svc.join_chat(100, 1)

    assert svc.stats(100, 1, fixed(8)).current_days == 0

    # Replace the initial start with a deterministic reset baseline.
    svc.reset(100, 1, "baseline", fixed(1))
    assert svc.stats(100, 1, fixed(8)).current_days == 7

    completed = svc.reset(100, 1, "late night trigger", fixed(8))
    assert completed == 7

    stats = svc.stats(100, 1, fixed(10))
    assert stats.current_days == 2
    assert stats.best_days == 7
    assert stats.completed_streaks == 2
    assert stats.average_days == 3.5

    relapses, _ = svc.history(100, 1)
    assert relapses[0]["reason"] == "late night trigger"
    assert relapses[0]["days"] == 7


def test_notes_are_saved_for_current_day(tmp_path):
    svc = make_service(tmp_path)
    svc.upsert_user(1, None, "Alice", None)
    svc.join_chat(100, 1)
    svc.reset(100, 1, "baseline", fixed(1))

    day = svc.add_note(100, 1, "walked outside", fixed(4))

    assert day == 3
    _, notes = svc.history(100, 1)
    assert notes[0]["day_number"] == 3
    assert notes[0]["body"] == "walked outside"


def test_top_and_milestones(tmp_path):
    svc = make_service(tmp_path)
    for user_id, username in [(1, "alice"), (2, "bob")]:
        svc.upsert_user(user_id, username, username.title(), None)
        svc.join_chat(100, user_id)
    svc.reset(100, 1, "baseline", fixed(1))
    svc.reset(100, 2, "baseline", fixed(3))

    rows = svc.top(100, now=fixed(8))

    assert rows[0]["name"] == "@alice"
    assert rows[0]["current_days"] == 7
    due = svc.due_milestones(fixed(8), {7, 30})
    assert len(due) == 1
    assert due[0]["user_id"] == 1
    assert svc.due_milestones(fixed(8), {7, 30}) == []


def test_partner_matching(tmp_path):
    svc = make_service(tmp_path)
    for user_id, username in [(1, "alice"), (2, "bob")]:
        svc.upsert_user(user_id, username, username.title(), None)
        svc.join_chat(100, user_id)

    partner = svc.find_partner(100, 1)

    assert partner["user_id"] == 2
    assert svc.partner_for(100, 2)["user_id"] == 1


def test_user_advice_is_saved_and_returned(tmp_path):
    svc = make_service(tmp_path)
    svc.upsert_user(1, "alice", "Alice", None)
    svc.join_chat(100, 1)

    svc.add_advice(100, 1, "Leave the room for 10 minutes")

    assert svc.random_advice(100) == "Leave the room for 10 minutes"
