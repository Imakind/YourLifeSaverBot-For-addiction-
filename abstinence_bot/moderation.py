from __future__ import annotations

from telegram import Message
from telegram.constants import ChatMemberStatus
from telegram.ext import ContextTypes

from .texts import TRIGGER_WORDS


def contains_trigger(text: str) -> bool:
    lower = text.lower()
    return any(word in lower for word in TRIGGER_WORDS)


async def is_admin(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int) -> bool:
    member = await context.bot.get_chat_member(chat_id, user_id)
    return member.status in {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER}


async def try_delete(message: Message) -> bool:
    try:
        await message.delete()
        return True
    except Exception:
        return False
