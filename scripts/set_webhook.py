from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from abstinence_bot.telegram_api import TelegramClient


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
