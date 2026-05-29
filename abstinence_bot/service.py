from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from random import choice
from typing import Iterable

from .db import Database
from .texts import ADVICE


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def mention_name(row: dict | object) -> str:
    username = row["username"] if row["username"] else None
    if username:
        return f"@{username}"
    first_name = row["first_name"] or "участник"
    return first_name


@dataclass(frozen=True)
class StreakStats:
    current_days: int
    best_days: int
    average_days: float
    completed_streaks: int
    started_at: datetime


class AbstinenceService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def upsert_user(self, user_id: int, username: str | None, first_name: str | None, last_name: str | None) -> None:
        now = iso(utcnow())
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO users (user_id, username, first_name, last_name, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username=excluded.username,
                    first_name=excluded.first_name,
                    last_name=excluded.last_name
                """,
                (user_id, username, first_name, last_name, now),
            )

    def join_chat(self, chat_id: int, user_id: int) -> None:
        now = iso(utcnow())
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO chat_users (chat_id, user_id, active, joined_at)
                VALUES (?, ?, 1, ?)
                ON CONFLICT(chat_id, user_id) DO UPDATE SET active=1
                """,
                (chat_id, user_id, now),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO streaks (chat_id, user_id, started_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (chat_id, user_id, now, now),
            )

    def stats(self, chat_id: int, user_id: int, now: datetime | None = None) -> StreakStats | None:
        now = now or utcnow()
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM streaks WHERE chat_id=? AND user_id=?",
                (chat_id, user_id),
            ).fetchone()
        if row is None:
            return None
        started_at = parse_iso(row["started_at"])
        current_days = max(0, (now.date() - started_at.date()).days)
        best_days = max(row["best_days"], current_days)
        average = row["total_completed_days"] / row["completed_streaks"] if row["completed_streaks"] else 0.0
        return StreakStats(current_days, best_days, average, row["completed_streaks"], started_at)

    def reset(self, chat_id: int, user_id: int, reason: str, now: datetime | None = None) -> int:
        now = now or utcnow()
        current = self.stats(chat_id, user_id, now)
        if current is None:
            self.join_chat(chat_id, user_id)
            current = self.stats(chat_id, user_id, now)
        assert current is not None
        reason = reason.strip() or "без причины"
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO relapses (chat_id, user_id, relapse_at, reason, days)
                VALUES (?, ?, ?, ?, ?)
                """,
                (chat_id, user_id, iso(now), reason[:500], current.current_days),
            )
            conn.execute(
                """
                UPDATE streaks
                SET started_at=?, best_days=?, total_completed_days=total_completed_days+?,
                    completed_streaks=completed_streaks+1, updated_at=?
                WHERE chat_id=? AND user_id=?
                """,
                (iso(now), current.best_days, current.current_days, iso(now), chat_id, user_id),
            )
            conn.execute("DELETE FROM sent_milestones WHERE chat_id=? AND user_id=?", (chat_id, user_id))
        return current.current_days

    def set_current_day(self, chat_id: int, user_id: int, days: int, now: datetime | None = None) -> None:
        if days < 0 or days > 10000:
            raise ValueError("days must be between 0 and 10000")
        now = now or utcnow()
        started_at = now - timedelta(days=days)
        current = self.stats(chat_id, user_id, now)
        best_days = max(current.best_days if current else 0, days)
        with self.db.connect() as conn:
            conn.execute(
                """
                UPDATE streaks
                SET started_at=?, best_days=?, updated_at=?
                WHERE chat_id=? AND user_id=?
                """,
                (iso(started_at), best_days, iso(now), chat_id, user_id),
            )
            conn.execute("DELETE FROM sent_milestones WHERE chat_id=? AND user_id=?", (chat_id, user_id))

    def add_note(self, chat_id: int, user_id: int, body: str, now: datetime | None = None) -> int:
        now = now or utcnow()
        current = self.stats(chat_id, user_id, now)
        if current is None:
            self.join_chat(chat_id, user_id)
            current = self.stats(chat_id, user_id, now)
        assert current is not None
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO day_notes (chat_id, user_id, day_number, note_date, body, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (chat_id, user_id, current.current_days, now.date().isoformat(), body[:1000], iso(now)),
            )
        return current.current_days

    def history(self, chat_id: int, user_id: int, limit: int = 10) -> tuple[list[dict], list[dict]]:
        with self.db.connect() as conn:
            relapses = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT relapse_at, reason, days
                    FROM relapses
                    WHERE chat_id=? AND user_id=?
                    ORDER BY relapse_at DESC
                    LIMIT ?
                    """,
                    (chat_id, user_id, limit),
                ).fetchall()
            ]
            notes = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT day_number, note_date, body, created_at
                    FROM day_notes
                    WHERE chat_id=? AND user_id=?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (chat_id, user_id, limit),
                ).fetchall()
            ]
        return relapses, notes

    def top(self, chat_id: int, limit: int = 10, now: datetime | None = None) -> list[dict]:
        now = now or utcnow()
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT s.*, u.username, u.first_name, u.last_name
                FROM streaks s
                JOIN chat_users cu ON cu.chat_id=s.chat_id AND cu.user_id=s.user_id
                JOIN users u ON u.user_id=s.user_id
                WHERE s.chat_id=? AND cu.active=1
                """,
                (chat_id,),
            ).fetchall()
        result = []
        for row in rows:
            started_at = parse_iso(row["started_at"])
            current_days = max(0, (now.date() - started_at.date()).days)
            result.append(
                {
                    "user_id": row["user_id"],
                    "name": mention_name(row),
                    "current_days": current_days,
                    "best_days": max(row["best_days"], current_days),
                }
            )
        result.sort(key=lambda item: (item["current_days"], item["best_days"]), reverse=True)
        return result[:limit]

    def set_partner_opt_in(self, chat_id: int, user_id: int, enabled: bool) -> None:
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE chat_users SET partner_opt_in=? WHERE chat_id=? AND user_id=?",
                (1 if enabled else 0, chat_id, user_id),
            )

    def partner_for(self, chat_id: int, user_id: int) -> dict | None:
        with self.db.connect() as conn:
            row = conn.execute(
                """
                SELECT p.*, u.user_id, u.username, u.first_name, u.last_name
                FROM partners p
                JOIN users u ON u.user_id = CASE WHEN p.user_a=? THEN p.user_b ELSE p.user_a END
                WHERE p.chat_id=? AND p.active=1 AND (p.user_a=? OR p.user_b=?)
                """,
                (user_id, chat_id, user_id, user_id),
            ).fetchone()
        return dict(row) if row else None

    def find_partner(self, chat_id: int, user_id: int) -> dict | None:
        existing = self.partner_for(chat_id, user_id)
        if existing:
            return existing
        now = iso(utcnow())
        with self.db.connect() as conn:
            candidate = conn.execute(
                """
                SELECT cu.user_id, u.username, u.first_name, u.last_name
                FROM chat_users cu
                JOIN users u ON u.user_id=cu.user_id
                WHERE cu.chat_id=? AND cu.user_id<>? AND cu.active=1 AND cu.partner_opt_in=1
                  AND NOT EXISTS (
                    SELECT 1 FROM partners p
                    WHERE p.chat_id=cu.chat_id AND p.active=1
                      AND (p.user_a=cu.user_id OR p.user_b=cu.user_id)
                  )
                ORDER BY RANDOM()
                LIMIT 1
                """,
                (chat_id, user_id),
            ).fetchone()
            if candidate is None:
                return None
            user_a, user_b = sorted((user_id, candidate["user_id"]))
            conn.execute(
                "INSERT INTO partners (chat_id, user_a, user_b, active, created_at) VALUES (?, ?, ?, 1, ?)",
                (chat_id, user_a, user_b, now),
            )
            return dict(candidate)

    def active_tracking_rows(self) -> Iterable[dict]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT s.chat_id, s.user_id, s.started_at, u.username, u.first_name, u.last_name
                FROM streaks s
                JOIN chat_users cu ON cu.chat_id=s.chat_id AND cu.user_id=s.user_id
                JOIN users u ON u.user_id=s.user_id
                WHERE cu.active=1
                """
            ).fetchall()
            return [dict(row) for row in rows]

    def due_milestones(self, now: datetime, milestones: set[int]) -> list[dict]:
        due = []
        for row in self.active_tracking_rows():
            days = max(0, (now.date() - parse_iso(row["started_at"]).date()).days)
            if days not in milestones:
                continue
            with self.db.connect() as conn:
                sent = conn.execute(
                    "SELECT 1 FROM sent_milestones WHERE chat_id=? AND user_id=? AND milestone_days=?",
                    (row["chat_id"], row["user_id"], days),
                ).fetchone()
                if sent:
                    continue
                conn.execute(
                    "INSERT INTO sent_milestones (chat_id, user_id, milestone_days, sent_at) VALUES (?, ?, ?, ?)",
                    (row["chat_id"], row["user_id"], days, iso(now)),
                )
            row["days"] = days
            row["name"] = mention_name(row)
            due.append(row)
        return due

    def add_warning(self, chat_id: int, user_id: int, moderator_id: int, reason: str) -> None:
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO warnings (chat_id, user_id, moderator_id, reason, created_at) VALUES (?, ?, ?, ?, ?)",
                (chat_id, user_id, moderator_id, reason[:500], iso(utcnow())),
            )

    def add_advice(self, chat_id: int, user_id: int, body: str) -> None:
        body = body.strip()
        if not body:
            return
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO advices (chat_id, user_id, body, created_at) VALUES (?, ?, ?, ?)",
                (chat_id, user_id, body[:1000], iso(utcnow())),
            )

    def random_advice(self, chat_id: int | None = None) -> str:
        params: tuple[int, ...] = ()
        where = ""
        if chat_id is not None:
            where = "WHERE chat_id=?"
            params = (chat_id,)
        with self.db.connect() as conn:
            rows = conn.execute(
                f"SELECT body FROM advices {where} ORDER BY RANDOM() LIMIT 20",
                params,
            ).fetchall()
        saved = [row["body"] for row in rows]
        return choice(saved or ADVICE)
