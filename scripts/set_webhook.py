from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from abstinence_bot.bot import load_env_file
from abstinence_bot.telegram_api import TelegramClient


def main() -> None:
    load_env_file()
    token = os.getenv("BOT_TOKEN")
    webhook_url = os.getenv("WEBHOOK_URL")
    secret = os.getenv("WEBHOOK_SECRET")
    if not token:
        raise SystemExit("BOT_TOKEN is required")
    if not webhook_url:
        raise SystemExit("WEBHOOK_URL is required")
    result = TelegramClient(token).set_webhook(webhook_url, secret)
    print(result)


if __name__ == "__main__":
    main()
