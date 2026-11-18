# pop-culture-autopost

Бесплатный автопостинг вирусных новостей поп-культуры в Telegram с переводом и редактурой через LLM.

## Установка
```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # заполните ключи
```

## Запуск
- Тест без отправки: `python -m autopost --dry-run` (посты в `out/*.json`, БД `data/state_dry.db`)
- Боевой запуск: `python -m autopost`
- Docker: `docker build -t autopost . && docker run --env-file .env -v "$(pwd)/data:/data" autopost`
- Локальный cron: `*/20 * * * * cd /path/to/project && .venv/bin/python -m autopost >> run.log 2>&1`

## GitHub Actions
Добавьте в Settings → Secrets and variables → Actions: `OPENROUTER_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`. Workflow запускается каждые 20 минут и коммитит `data/state.db`. Если в репозитории 60 дней нет активности, GitHub отключит расписание; коммиты состояния от бота считаются активностью.

## Провайдеры
- `AI_PROVIDER=openrouter` (по умолчанию, модели `:free`)
- `AI_PROVIDER=groq` (нужен `GROQ_API_KEY`)
- `AI_PROVIDER=ollama` (локальная модель, `OLLAMA_URL`)

## Авторское право
Бот публикует краткий пересказ и ссылку на источник. Полные тексты статей не переводятся и не копируются; картинки берутся по ссылке без скачивания.
