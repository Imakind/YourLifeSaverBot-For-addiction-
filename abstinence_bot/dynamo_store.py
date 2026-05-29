from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from random import choice
from typing import Any

from .texts import ADVICE


def _boto3_resource():
    import boto3

    return boto3.resource("dynamodb")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def mention_name(row: dict[str, Any]) -> str:
    username = row.get("username")
    if username:
        return f"@{username}"
    return row.get("first_name") or "участник"


@dataclass(frozen=True)
class StreakStats:
    current_days: int
    best_days: int
    average_days: float
    completed_streaks: int
    started_at: datetime


class DynamoStore:
    def __init__(self, table_name: str | None = None) -> None:
        self.table_name = table_name or os.environ["TABLE_NAME"]
        self.table = _boto3_resource().Table(self.table_name)

    @staticmethod
    def chat_pk(chat_id: int) -> str:
        return f"CHAT#{chat_id}"

    @staticmethod
    def user_sk(user_id: int) -> str:
        return f"USER#{user_id}"

    @staticmethod
    def history_pk(chat_id: int, user_id: int) -> str:
        return f"HISTORY#{chat_id}#{user_id}"

    def upsert_user(self, chat_id: int, user: dict[str, Any]) -> None:
        now = iso(utcnow())
        item = self.get_user_item(chat_id, int(user["id"]))
        values = {
            ":type": "member",
            ":active": 1,
            ":partner_opt_in": 1,
            ":username": user.get("username"),
            ":first_name": user.get("first_name"),
            ":last_name": user.get("last_name"),
            ":now": now,
            ":zero": 0,
        }
        if item is None:
            self.table.put_item(
                Item={
                    "PK": self.chat_pk(chat_id),
                    "SK": self.user_sk(int(user["id"])),
                    "type": "member",
                    "chat_id": chat_id,
                    "user_id": int(user["id"]),
                    "active": 1,
                    "partner_opt_in": 1,
                    "username": user.get("username"),
                    "first_name": user.get("first_name"),
                    "last_name": user.get("last_name"),
                    "started_at": now,
                    "best_days": 0,
                    "total_completed_days": 0,
                    "completed_streaks": 0,
                    "created_at": now,
                    "updated_at": now,
                }
            )
            return
        self.table.update_item(
            Key={"PK": self.chat_pk(chat_id), "SK": self.user_sk(int(user["id"]))},
            UpdateExpression=(
                "SET active=:active, partner_opt_in=if_not_exists(partner_opt_in, :partner_opt_in), "
                "username=:username, first_name=:first_name, last_name=:last_name, "
                "started_at=if_not_exists(started_at, :now), best_days=if_not_exists(best_days, :zero), "
                "total_completed_days=if_not_exists(total_completed_days, :zero), "
                "completed_streaks=if_not_exists(completed_streaks, :zero), updated_at=:now"
            ),
            ExpressionAttributeValues=values,
        )

    def get_user_item(self, chat_id: int, user_id: int) -> dict[str, Any] | None:
        response = self.table.get_item(Key={"PK": self.chat_pk(chat_id), "SK": self.user_sk(user_id)})
        return response.get("Item")

    def stats(self, chat_id: int, user_id: int, now: datetime | None = None) -> StreakStats | None:
        item = self.get_user_item(chat_id, user_id)
        if item is None:
            return None
        now = now or utcnow()
        started_at = parse_iso(item["started_at"])
        current_days = max(0, (now.date() - started_at.date()).days)
        best_days = max(int(item.get("best_days", 0)), current_days)
        completed = int(item.get("completed_streaks", 0))
        total = int(item.get("total_completed_days", 0))
        average = total / completed if completed else 0.0
        return StreakStats(current_days, best_days, average, completed, started_at)

    def reset(self, chat_id: int, user_id: int, reason: str, now: datetime | None = None) -> int:
        now = now or utcnow()
        current = self.stats(chat_id, user_id, now)
        if current is None:
            raise ValueError("user is not registered")
        reason = (reason.strip() or "без причины")[:500]
        self.table.put_item(
            Item={
                "PK": self.history_pk(chat_id, user_id),
                "SK": f"RELAPSE#{iso(now)}#{uuid.uuid4().hex}",
                "type": "relapse",
                "chat_id": chat_id,
                "user_id": user_id,
                "relapse_at": iso(now),
                "reason": reason,
                "days": current.current_days,
            }
        )
        self.table.update_item(
            Key={"PK": self.chat_pk(chat_id), "SK": self.user_sk(user_id)},
            UpdateExpression=(
                "SET started_at=:started_at, best_days=:best_days, updated_at=:updated_at "
                "ADD total_completed_days :days, completed_streaks :one"
            ),
            ExpressionAttributeValues={
                ":started_at": iso(now),
                ":best_days": current.best_days,
                ":updated_at": iso(now),
                ":days": current.current_days,
                ":one": 1,
            },
        )
        self.clear_milestones(chat_id, user_id)
        return current.current_days

    def add_note(self, chat_id: int, user_id: int, body: str, now: datetime | None = None) -> int:
        now = now or utcnow()
        current = self.stats(chat_id, user_id, now)
        if current is None:
            raise ValueError("user is not registered")
        self.table.put_item(
            Item={
                "PK": self.history_pk(chat_id, user_id),
                "SK": f"NOTE#{iso(now)}#{uuid.uuid4().hex}",
                "type": "note",
                "chat_id": chat_id,
                "user_id": user_id,
                "day_number": current.current_days,
                "note_date": now.date().isoformat(),
                "body": body[:1000],
                "created_at": iso(now),
            }
        )
        return current.current_days

    def history(self, chat_id: int, user_id: int, limit: int = 10) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        response = self.table.query(
            KeyConditionExpression="PK = :pk",
            ExpressionAttributeValues={":pk": self.history_pk(chat_id, user_id)},
            ScanIndexForward=False,
            Limit=50,
        )
        relapses: list[dict[str, Any]] = []
        notes: list[dict[str, Any]] = []
        for item in response.get("Items", []):
            if item.get("type") == "relapse" and len(relapses) < limit:
                relapses.append(item)
            if item.get("type") == "note" and len(notes) < limit:
                notes.append(item)
        return relapses, notes

    def top(self, chat_id: int, limit: int = 10, now: datetime | None = None) -> list[dict[str, Any]]:
        now = now or utcnow()
        response = self.table.query(
            KeyConditionExpression="PK = :pk AND begins_with(SK, :prefix)",
            ExpressionAttributeValues={":pk": self.chat_pk(chat_id), ":prefix": "USER#"},
        )
        rows = []
        for item in response.get("Items", []):
            if int(item.get("active", 0)) != 1:
                continue
            started_at = parse_iso(item["started_at"])
            current_days = max(0, (now.date() - started_at.date()).days)
            rows.append(
                {
                    "user_id": int(item["user_id"]),
                    "name": mention_name(item),
                    "current_days": current_days,
                    "best_days": max(int(item.get("best_days", 0)), current_days),
                }
            )
        rows.sort(key=lambda row: (row["current_days"], row["best_days"]), reverse=True)
        return rows[:limit]

    def set_partner_opt_in(self, chat_id: int, user_id: int, enabled: bool) -> None:
        self.table.update_item(
            Key={"PK": self.chat_pk(chat_id), "SK": self.user_sk(user_id)},
            UpdateExpression="SET partner_opt_in=:enabled",
            ExpressionAttributeValues={":enabled": 1 if enabled else 0},
        )

    def partner_for(self, chat_id: int, user_id: int) -> dict[str, Any] | None:
        response = self.table.query(
            KeyConditionExpression="PK = :pk AND begins_with(SK, :prefix)",
            ExpressionAttributeValues={":pk": self.chat_pk(chat_id), ":prefix": "PARTNER#"},
        )
        for item in response.get("Items", []):
            if int(item.get("active", 0)) != 1:
                continue
            users = {int(item["user_a"]), int(item["user_b"])}
            if user_id not in users:
                continue
            other_id = next(uid for uid in users if uid != user_id)
            return self.get_user_item(chat_id, other_id)
        return None

    def find_partner(self, chat_id: int, user_id: int) -> dict[str, Any] | None:
        existing = self.partner_for(chat_id, user_id)
        if existing:
            return existing
        response = self.table.query(
            KeyConditionExpression="PK = :pk AND begins_with(SK, :prefix)",
            ExpressionAttributeValues={":pk": self.chat_pk(chat_id), ":prefix": "USER#"},
        )
        for item in response.get("Items", []):
            candidate_id = int(item["user_id"])
            if candidate_id == user_id or int(item.get("active", 0)) != 1 or int(item.get("partner_opt_in", 1)) != 1:
                continue
            if self.partner_for(chat_id, candidate_id):
                continue
            user_a, user_b = sorted((user_id, candidate_id))
            self.table.put_item(
                Item={
                    "PK": self.chat_pk(chat_id),
                    "SK": f"PARTNER#{user_a}#{user_b}",
                    "type": "partner",
                    "chat_id": chat_id,
                    "user_a": user_a,
                    "user_b": user_b,
                    "active": 1,
                    "created_at": iso(utcnow()),
                }
            )
            return item
        return None

    def add_advice(self, chat_id: int, user_id: int, body: str) -> None:
        body = body.strip()
        if not body:
            return
        self.table.put_item(
            Item={
                "PK": self.chat_pk(chat_id),
                "SK": f"ADVICE#{uuid.uuid4().hex}",
                "type": "advice",
                "chat_id": chat_id,
                "user_id": user_id,
                "body": body[:1000],
                "created_at": iso(utcnow()),
            }
        )

    def random_advice(self, chat_id: int) -> str:
        response = self.table.query(
            KeyConditionExpression="PK = :pk AND begins_with(SK, :prefix)",
            ExpressionAttributeValues={":pk": self.chat_pk(chat_id), ":prefix": "ADVICE#"},
            Limit=50,
        )
        saved = [item["body"] for item in response.get("Items", []) if item.get("body")]
        return choice(saved or ADVICE)

    def add_warning(self, chat_id: int, user_id: int, moderator_id: int, reason: str) -> None:
        self.table.put_item(
            Item={
                "PK": self.chat_pk(chat_id),
                "SK": f"WARNING#{iso(utcnow())}#{uuid.uuid4().hex}",
                "type": "warning",
                "chat_id": chat_id,
                "user_id": user_id,
                "moderator_id": moderator_id,
                "reason": reason[:500],
                "created_at": iso(utcnow()),
            }
        )

    def active_tracking_rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        scan_kwargs: dict[str, Any] = {
            "FilterExpression": "#type = :type AND active = :active",
            "ExpressionAttributeNames": {"#type": "type"},
            "ExpressionAttributeValues": {":type": "member", ":active": 1},
        }
        while True:
            response = self.table.scan(**scan_kwargs)
            rows.extend(response.get("Items", []))
            last_key = response.get("LastEvaluatedKey")
            if not last_key:
                return rows
            scan_kwargs["ExclusiveStartKey"] = last_key

    def clear_milestones(self, chat_id: int, user_id: int) -> None:
        response = self.table.query(
            KeyConditionExpression="PK = :pk AND begins_with(SK, :prefix)",
            ExpressionAttributeValues={":pk": self.chat_pk(chat_id), ":prefix": f"MILESTONE#{user_id}#"},
        )
        for item in response.get("Items", []):
            self.table.delete_item(Key={"PK": item["PK"], "SK": item["SK"]})

    def due_milestones(self, now: datetime, milestones: set[int]) -> list[dict[str, Any]]:
        due = []
        for item in self.active_tracking_rows():
            days = max(0, (now.date() - parse_iso(item["started_at"]).date()).days)
            if days not in milestones:
                continue
            sk = f"MILESTONE#{item['user_id']}#{days}"
            try:
                self.table.put_item(
                    Item={
                        "PK": self.chat_pk(int(item["chat_id"])),
                        "SK": sk,
                        "type": "milestone",
                        "chat_id": int(item["chat_id"]),
                        "user_id": int(item["user_id"]),
                        "milestone_days": days,
                        "sent_at": iso(now),
                    },
                    ConditionExpression="attribute_not_exists(PK)",
                )
            except Exception:
                continue
            item["days"] = days
            item["name"] = mention_name(item)
            due.append(item)
        return due
