# TelegramOneDayBot

Бот для группового трекинга сексуального воздержания: streak, история срывов, заметки по дням, SOS-протокол, напарники, топ участников и базовая модерация чата.

## Установка

1. Создать виртуальное окружение:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

2. Установить зависимости:

```powershell
pip install -r requirements.txt
```

3. Задать переменные окружения:

```powershell
$env:BOT_TOKEN="your_telegram_bot_token"
$env:BOT_DB_PATH="bot.sqlite3"
```

Также можно создать файл `.env` в корне проекта:

```env
BOT_TOKEN=your_telegram_bot_token
BOT_DB_PATH=bot.sqlite3
```

4. Запустить:

```powershell
python -m abstinence_bot.bot
```

## Команды

- `/start` или `/join` - регистрация участника в чате.
- `/status` - текущий streak, рекорд, среднее.
- `/setday N` - один раз выставить текущий день при первом входе, например `/setday 12`.
- `/reset причина` - сброс счётчика с причиной срыва.
- `/note текст` - заметка на текущий день воздержания.
- `/history` - последние срывы и заметки.
- `/top` - рейтинг участников по текущему streak.
- `/partner` - найти accountability partner.
- `/partner on` / `/partner off` - включить или отключить подбор напарника.
- `/sos` - короткий протокол действий на пике тяги.
- `/advice` - получить случайный совет.
- `/advice текст совета` - добавить совет из чата в общую базу советов.
- `/fact` - факт о профилактике срыва.
- `/quote` - мотивационная фраза.
- `/report причина` - жалоба на сообщение, используется ответом на сообщение.
- `/warn причина` - предупреждение пользователю, только для админов, ответом на сообщение.
- `/delete` - удалить сообщение, только для админов, ответом на сообщение.

## База данных

Используется SQLite через встроенный модуль Python `sqlite3`; отдельный SQLite CLI устанавливать не нужно. Файл `bot.sqlite3` создаётся автоматически при первом запуске. Хранятся:

- участники и их участие в чатах;
- текущий старт streak, рекорд, среднее по завершённым периодам;
- история срывов с причиной;
- заметки по конкретному дню;
- пары напарников;
- отправленные milestones;
- предупреждения модерации.

## Уведомления

- Milestones: 7, 30, 90, 180 дней.

## Проверка

```powershell
pytest
```

## Деплой

Есть два режима деплоя:

- long-running worker: локально, VM, Docker Compose;
- AWS Serverless: API Gateway + Lambda + DynamoDB + EventBridge.

Для AWS см. [AWS_SERVERLESS.md](AWS_SERVERLESS.md).

Проект также можно запускать как long-running worker. Для Render подготовлен `render.yaml`.

Обязательный секрет на хостинге:

```env
BOT_TOKEN=your_telegram_bot_token
```

Для сохранения SQLite между рестартами нужен persistent disk. В `render.yaml` база настроена на `/data/bot.sqlite3`. По документации Render persistent disk доступен для платных worker-сервисов; без диска файловая система будет временной.

Если нужен именно бесплатный вариант, см. [DEPLOY_FREE.md](DEPLOY_FREE.md). Рекомендуемый вариант без переписывания архитектуры - Oracle Cloud Always Free VM + Docker Compose.
