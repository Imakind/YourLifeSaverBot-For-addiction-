# Бесплатный деплой

## Рекомендуемый вариант: Oracle Cloud Always Free VM

Почему этот вариант подходит:

- бот работает через polling и должен быть запущен постоянно;
- SQLite хранится как файл и требует постоянного диска;
- текущий код не нужно переводить на webhook или внешнюю БД.

Официальная документация Oracle указывает, что Always Free включает Compute VM resources. Доступность конкретных VM зависит от региона и лимитов аккаунта.

## Шаги на VM

1. Установить Docker и Docker Compose plugin.

2. Склонировать репозиторий:

```bash
git clone https://github.com/Imakind/YourLifeSaverBot-For-addiction-.git
cd YourLifeSaverBot-For-addiction-
```

3. Создать `.env`:

```env
BOT_TOKEN=your_telegram_bot_token
BOT_TZ=Asia/Qyzylorda
MORNING_NOTIFY=09:00
EVENING_NOTIFY=21:00
```

4. Запустить:

```bash
docker compose up -d --build
```

5. Проверить логи:

```bash
docker compose logs -f bot
```

6. Остановить:

```bash
docker compose down
```

## Почему не Render Free

Render Blueprint сам по себе не тарифицируется, но он создаёт сервисы. Для этого бота нужен background worker и persistent disk. По документации Render:

- free instance type не доступен для background workers;
- persistent disk доступен для paid services;
- без persistent disk SQLite-файл может пропасть после redeploy/restart.

## Альтернативы с ограничениями

- Koyeb Free Web Service: бесплатный web service есть, но free instance не поддерживает worker services, volumes и scale-to-zero после простоя. Для Telegram polling и SQLite это неподходящий вариант без архитектурной переделки.
- Railway Free Trial: это trial/credits, не постоянный бесплатный хостинг.
