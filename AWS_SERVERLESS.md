# AWS Serverless deploy

## Архитектура

- Telegram webhook -> API Gateway HTTP API.
- API Gateway -> AWS Lambda `webhook_handler`.
- DynamoDB -> хранение streak, заметок, срывов, советов, напарников.
- EventBridge schedules -> Lambda `schedule_handler` для утренних/вечерних уведомлений и milestones.

SQLite в serverless-режиме не используется.

## Бесплатные лимиты

Официальные лимиты могут меняться. Перед деплоем проверь цены в своём регионе.

- AWS Lambda: 1M requests/month и 400,000 GB-seconds/month.
- DynamoDB: free tier для DynamoDB Standard включает 25 GB storage, 25 RCU, 25 WCU.
- EventBridge Scheduler: 14M invocations/month free tier.
- API Gateway HTTP API: free tier обычно ограничен первыми 12 месяцами для новых аккаунтов.

Источники:

- https://aws.amazon.com/lambda/pricing/
- https://aws.amazon.com/dynamodb/pricing/
- https://aws.amazon.com/eventbridge/pricing/
- https://aws.amazon.com/api-gateway/pricing/

## Требования

- AWS account.
- AWS CLI.
- AWS SAM CLI.
- Python 3.12 для локальной сборки SAM.
- Новый Telegram token из BotFather.

## Деплой

1. Настроить AWS CLI:

```bash
aws configure
```

2. Собрать:

```bash
sam build
```

3. Задеплоить:

```bash
sam deploy --guided \
  --parameter-overrides BotToken=YOUR_TELEGRAM_TOKEN WebhookSecret=RANDOM_LONG_SECRET
```

При первом запуске SAM спросит stack name и регион. Подтверди сохранение настроек.

4. В выводе SAM найди `TelegramWebhookUrl`.

5. Установить webhook в Telegram:

```bash
export BOT_TOKEN="YOUR_TELEGRAM_TOKEN"
export WEBHOOK_SECRET="RANDOM_LONG_SECRET"
export WEBHOOK_URL="https://...execute-api.../telegram"
python scripts/set_webhook.py
```

Для PowerShell:

```powershell
$env:BOT_TOKEN="YOUR_TELEGRAM_TOKEN"
$env:WEBHOOK_SECRET="RANDOM_LONG_SECRET"
$env:WEBHOOK_URL="https://...execute-api.../telegram"
python scripts/set_webhook.py
```

## Проверка

```bash
aws lambda list-functions
aws dynamodb describe-table --table-name YourLifeSaverBot
```

В Telegram:

```text
/start
/menu
/status
```

## Важные ограничения

- EventBridge cron в `template.yaml` задан в UTC: `04:00 UTC` = `09:00 Asia/Qyzylorda`, `16:00 UTC` = `21:00 Asia/Qyzylorda`.
- DynamoDB настроен на provisioned `1 RCU / 1 WCU`, чтобы держаться ближе к free tier. Для активного большого чата может потребоваться увеличить capacity.
- Админские команды частично отличаются от polling-версии: serverless handler сохраняет жалобы и пытается удалять триггерные сообщения, если у бота есть права.
