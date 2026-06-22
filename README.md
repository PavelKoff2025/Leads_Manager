# Lead Manager — MVP

Мини-сервис для приёма заявок с лендинга, сайта или формы: **webhook → валидация → SQLite → уведомление в лог**.

Решает задачу малого бизнеса: заявки из разных каналов попадают в одну базу, менеджер сразу видит, что пришла новая заявка.

---

## Соответствие заданию MVP

| Требование | Реализация | Статус |
|------------|------------|--------|
| Webhook `POST /lead` | Принимает JSON: `name`, `contact`, `source`, `comment` | ✅ |
| SQLite, таблица `leads` | `id`, `created_at`, `name`, `contact`, `source`, `comment` | ✅ |
| Событие «заявка принята» | Event Log: `New lead saved: <id>` в `logs/events.log` | ✅ |
| Валидация | Невалидный JSON / нет `contact` → HTTP **400** | ✅ |
| Ошибки БД | HTTP **500** + запись в лог | ✅ |
| Вход → обработка → выход | Webhook → Pydantic → SQLite → лог → JSON-ответ | ✅ |

---

## Как это работает

```
Лендинг / форма / curl
        │
        ▼
   POST /lead  (JSON)
        │
        ▼
   Валидация (Pydantic)
        │
        ▼
   SQLite (data/leads.db)
        │
        ▼
   logs/events.log  →  "New lead saved: 42"
        │
        ▼
   HTTP 201 + JSON с id заявки
```

---

## Быстрый старт

### Требования

- Python 3.10+
- pip

### Установка и запуск

```bash
git clone https://github.com/PavelKoff2025/Leads_Manager.git
cd lead-manager

python3 -m venv venv
source venv/bin/activate      # Linux / macOS
# venv\Scripts\activate       # Windows

pip install -r requirements.txt
python run.py
```

Сервис доступен на:

| URL | Назначение |
|-----|------------|
| http://localhost:8000/ | Веб-интерфейс |
| http://localhost:8000/docs | Swagger UI |
| http://localhost:8000/health | Проверка состояния |

Альтернативный запуск:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

---

## Webhook — `POST /lead` (основной endpoint MVP)

### Формат запроса

```json
{
  "name": "Ирина",
  "contact": "+79990000000",
  "source": "landing",
  "comment": "Хочу консультацию по тарифам"
}
```

| Поле | Обязательное | Описание |
|------|--------------|----------|
| `name` | да | Имя клиента |
| `contact` | да | Телефон или email |
| `source` | нет | Канал: `landing`, `telegram`, `instagram` и т.д. |
| `comment` | нет | Комментарий к заявке |

### Пример (curl)

```bash
curl -X POST http://localhost:8000/lead \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Ирина",
    "contact": "+79990000000",
    "source": "landing",
    "comment": "Хочу консультацию по тарифам"
  }'
```

### Успешный ответ — HTTP 201

```json
{
  "id": 1,
  "name": "Ирина",
  "contact": "+79990000000",
  "source": "landing",
  "comment": "Хочу консультацию по тарифам",
  "created_at": "2026-06-22T15:50:25.575555Z",
  "status": "new"
}
```

### Подключение с лендинга (JavaScript)

```javascript
fetch("http://localhost:8000/lead", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    name: document.getElementById("name").value,
    contact: document.getElementById("phone").value,
    source: "landing",
    comment: document.getElementById("message").value,
  }),
});
```

---

## База данных (SQLite)

Файл: `data/leads.db` (создаётся автоматически при первом запуске).

### Таблица `leads` — поля MVP

| Поле | Тип | Описание |
|------|-----|----------|
| `id` | INTEGER | Первичный ключ, автоинкремент |
| `created_at` | TEXT | Дата и время создания (ISO UTC) |
| `name` | TEXT | Имя |
| `contact` | TEXT | Контакт (телефон или email) |
| `source` | TEXT | Источник заявки |
| `comment` | TEXT | Комментарий |

Дополнительные поля (`email`, `phone`, `status`, `notes`, `updated_at`) используются расширенным API и веб-интерфейсом.

---

## Уведомления — Event Log (вариант A)

При каждой новой заявке в `logs/events.log` пишется строка:

```
2026-06-22 18:50:25 | New lead saved: 1
```

Проверка:

```bash
tail -f logs/events.log
```

Дополнительно в консоль выводится форматированный блок с данными заявки.

---

## Обработка ошибок

Все ошибки возвращаются в формате `{"error": "..."}`.

| Ситуация | HTTP | Пример ответа |
|----------|------|---------------|
| Невалидный JSON | 400 | `{"error": "Невалидный JSON"}` |
| Отсутствует `contact` | 400 | `{"error": "Отсутствует или невалидное поле contact"}` |
| Ошибка SQLite | 500 | `{"error": "Database error"}` |
| Дубликат email (расширенный API) | 409 | `{"error": "Лид с таким email уже существует"}` |

Примеры проверки:

```bash
# Нет contact → 400
curl -s -X POST http://localhost:8000/lead \
  -H "Content-Type: application/json" \
  -d '{"name": "Тест"}'

# Невалидный JSON → 400
curl -s -X POST http://localhost:8000/lead \
  -H "Content-Type: application/json" \
  -d 'not json'
```

---

## Тестирование

Готовые payload-ы: `tests/test_payloads.json`.

### Webhook (MVP)

```bash
curl -s -X POST http://localhost:8000/lead \
  -H "Content-Type: application/json" \
  -d @- <<'EOF'
{
  "name": "Ирина",
  "contact": "+79990000000",
  "source": "landing",
  "comment": "Хочу консультацию по тарифам"
}
EOF
```

### Массовая загрузка тестовых лидов

```bash
for payload in $(jq -c '.create_leads[]' tests/test_payloads.json); do
  curl -s -X POST http://localhost:8000/leads \
    -H "Content-Type: application/json" \
    -d "$payload" | jq .
done
```

---

## Структура проекта

```
lead-manager/
├── app/
│   ├── main.py              # FastAPI: маршруты, обработка ошибок
│   ├── database.py          # SQLite: схема, CRUD, миграции
│   ├── models.py            # Pydantic-модели и валидация
│   ├── logger.py            # Логирование
│   ├── notifications.py     # Event log + уведомления
│   ├── importer.py          # Импорт из .xlsx
│   └── static/              # Веб-интерфейс (HTML, CSS, JS)
├── data/
│   └── leads.db             # SQLite (создаётся автоматически)
├── logs/
│   └── events.log           # Лог событий
├── tests/
│   └── test_payloads.json   # Тестовые запросы
├── run.py                   # Точка входа
├── requirements.txt
└── README.md
```

---

## Дополнительные возможности (сверх MVP)

Помимо обязательного webhook, в проекте реализованы инструменты для ежедневной работы менеджера с заявками.

| Возможность | Endpoint / UI |
|-------------|---------------|
| Веб-панель менеджера | `GET /` |
| CRUD по лидам | `POST/GET/PATCH/DELETE /leads` |
| Поиск и фильтрация | `GET /leads?q=...&search_by=...&status=...` |
| Импорт Excel / Bitrix24 | `POST /leads/import` |
| Дашборд | `GET /api/dashboard` (вкладка «Дашборд» в UI) |
| Статусы воронки | `new` → `contacted` → `qualified` / `lost` |

### Импорт заявок из Excel (.xlsx)

Загрузка файла через веб-интерфейс (блок **«Импорт из Excel»**) или API:

```bash
curl -X POST http://localhost:8000/leads/import \
  -F "file=@leads.xlsx"
```

Шаблон для ручного заполнения: http://localhost:8000/leads/import/template

**Обычный формат** — первая строка заголовки, далее данные. Поддерживаются русские и английские названия колонок (распознавание по синонимам):

| Поле | Примеры заголовков |
|------|-------------------|
| Имя | `Имя`, `ФИО`, `Клиент`, `name` |
| Email | `Email`, `Почта`, `mail` |
| Телефон | `Телефон`, `Тел`, `phone` |
| Контакт | `Контакт`, `contact` |
| Источник | `Источник`, `Канал`, `source` |
| Комментарий | `Комментарий`, `Описание`, `notes` |

**Адаптация под Bitrix24** — при импорте выгрузки CRM сервис автоматически:

- определяет формат Bitrix по характерным колонкам (`Название лида`, `Рабочий телефон`, `Источник`);
- выбирает лист с наибольшим числом строк (удобно для файлов с десятками колонок);
- собирает **имя** из полей `Имя` + `Отчество` + `Фамилия` (или берёт `Название лида`);
- извлекает **телефон** из рабочего, мобильного, домашнего и других телефонных полей;
- извлекает **email** из рабочего, частного и прочих email-полей;
- формирует **комментарий** из `Комментарий`, `Обращение`, `Стадия`, `Дополнительно о стадии`;
- сохраняет **источник** из колонки `Источник`.

Ответ API: количество созданных и пропущенных записей, список ошибок по строкам.

### Поиск и фильтрация заявок

Доступно в веб-интерфейсе (строка поиска + выпадающий список) и через API `GET /leads`.

**Поиск по параметрам** (`?q=текст&search_by=...`):

| Параметр `search_by` | Что ищется |
|----------------------|------------|
| `name` | Имя клиента (по умолчанию) |
| `phone` | Телефон / контакт (`contact`) |
| `source` | Источник заявки (`landing`, `telegram`, `yandex` и т.д.) |

Поиск нечувствителен к регистру, работает по подстроке (`LIKE %...%`).

**Фильтр по статусу** — параметр `?status=new|contacted|qualified|lost` (в UI — выпадающий список «Все статусы / Новые / …»).

**Пагинация** — `?limit=100&offset=0` (максимум 500 за запрос).

Примеры:

```bash
# По имени
curl "http://localhost:8000/leads?q=Ирина&search_by=name"

# По телефону
curl "http://localhost:8000/leads?q=7999&search_by=phone"

# По источнику + только новые
curl "http://localhost:8000/leads?q=landing&search_by=source&status=new"
```

### Дашборд аналитики

Вкладка **«Дашборд»** в веб-интерфейсе или `GET /api/dashboard`.

Выводится:

- **Всего заявок** — общее количество лидов в базе;
- **По дате** — столбчатая диаграмма: сколько заявок пришло в каждый день (последние 30 дней);
- **По источнику** — распределение по каналам (`landing`, `telegram`, `instagram` и др.; пустые — «Не указан»), топ-20;
- **По квалификации** — разбивка по статусам воронки: *Новый*, *Связались*, *Квалифицирован*, *Потерян*.

Данные обновляются кнопкой «Обновить» или при переключении на вкладку.

```bash
curl http://localhost:8000/api/dashboard
```

Пример фрагмента ответа:

```json
{
  "total": 327,
  "by_date": [{"label": "22.06.2026", "count": 15}],
  "by_source": [{"label": "landing", "count": 120}],
  "by_status": [{"label": "Новый", "count": 280}]
}
```

---

## API (полный список)

| Метод | Endpoint | Описание |
|-------|----------|----------|
| GET | `/` | Веб-интерфейс |
| GET | `/api/info` | Информация о сервисе |
| GET | `/health` | Проверка состояния |
| **POST** | **`/lead`** | **Webhook: принять заявку (MVP)** |
| POST | `/leads` | Создать лид (расширенный формат) |
| GET | `/leads` | Список лидов |
| GET | `/leads/{id}` | Получить лид |
| PATCH | `/leads/{id}` | Обновить лид |
| DELETE | `/leads/{id}` | Удалить лид |
| POST | `/leads/import` | Импорт из .xlsx |
| GET | `/leads/import/template` | Шаблон .xlsx |
| GET | `/api/dashboard` | Статистика по дате, источнику, статусу |

---

## Стек технологий

Соответствие рекомендуемому стеку из задания MVP:

| Требование | Реализация в проекте | Статус |
|------------|----------------------|--------|
| Web-фреймворк: FastAPI или Flask | **FastAPI** 0.104.1 — `app/main.py`, `requirements.txt` | ✅ |
| База данных: SQLite | `data/leads.db` — `app/database.py`, модуль `sqlite3` | ✅ |
| Python 3.10+ | Python **3.11** (минимум задания: 3.10+) | ✅ |
| Pydantic для валидации | `pydantic[email]==2.5.0` — `app/models.py`, обработка `RequestValidationError` | ✅ |
| smtplib / email-провайдер (вариант B) | Не используется — выбран **вариант A** (Event Log) | ➖ не требуется |

### Используемые технологии

| Компонент | Версия / пакет | Назначение |
|-----------|----------------|------------|
| FastAPI | 0.104.1 | HTTP API, маршруты, Swagger (`/docs`) |
| Pydantic | 2.5.0 | Валидация JSON, модели `LeadWebhook`, `LeadCreate` |
| SQLite | 3.x (stdlib) | Хранение заявок в `data/leads.db` |
| Uvicorn | 0.24.0 | ASGI-сервер для запуска приложения |
| openpyxl | 3.1.2 | Импорт заявок из `.xlsx` (в т.ч. Bitrix24) |
| python-multipart | 0.0.6 | Загрузка файлов через `POST /leads/import` |

Валидация через Pydantic: проверка полей webhook (`name`, `contact`, `source`, `comment`), тип `EmailStr` для email, кастомный валидатор контакта (телефон или email).

---

## Для портфолио

### Краткий pitch (для отклика на фриланс)

> Разработал Lead Manager — мини-сервис приёма заявок для малого бизнеса.
> Webhook `POST /lead` принимает заявки с лендинга, сохраняет в SQLite и пишет событие в лог.
> Дополнительно: веб-панель, импорт Excel и выгрузок Bitrix24, поиск по имени/телефону/источнику, дашборд по дате, каналам и квалификации.
> Есть валидация, обработка ошибок (400/500). Стек: Python, FastAPI, SQLite. Запуск за 2 минуты по README.

### Что показать заказчику

1. **Swagger** — http://localhost:8000/docs (endpoint `POST /lead`)
2. **Веб-интерфейс** — http://localhost:8000/ (список заявок, поиск, импорт)
3. **Дашборд** — вкладка «Дашборд» (заявки по дате, источнику, квалификации)
4. **Импорт Bitrix** — загрузка `.xlsx` выгрузки CRM через UI или `POST /leads/import`
5. **Лог событий** — `tail logs/events.log` после отправки заявки
6. **Скриншоты** — добавьте в репозиторий папку `docs/screenshots/`:
   - веб-интерфейс со списком заявок
   - дашборд с диаграммами
   - Swagger с успешным `POST /lead`
   - строка `New lead saved: ...` в `events.log`

### Чеклист перед публикацией на GitHub

- [x] Заменить `<your-repo-url>` на ссылку на репозиторий — https://github.com/PavelKoff2025/Leads_Manager
- [ ] Добавить 2–3 скриншота в `docs/screenshots/`
- [ ] Убедиться, что `data/leads.db` и `logs/*.log` в `.gitignore`
- [ ] Проверить `curl`-запрос из раздела Webhook
- [ ] Заполнить описание репозитория на GitHub (pitch из раздела выше)

---

## Лицензия

MIT (или укажите свою лицензию при публикации).
