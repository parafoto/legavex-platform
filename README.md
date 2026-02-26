# LegaVex Advisor Portal

<p align="center">
  <strong>Кабинет консультанта для legal-tech платформы LegaVex</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11+-blue.svg" alt="Python">
  <img src="https://img.shields.io/badge/FastAPI-0.109-green.svg" alt="FastAPI">
  <img src="https://img.shields.io/badge/Prisma-0.12-purple.svg" alt="Prisma">
  <img src="https://img.shields.io/badge/PostgreSQL-15-blue.svg" alt="PostgreSQL">
</p>

---

## 📋 Описание

LegaVex Advisor Portal — веб-платформа для управления юридическими консультациями. Система позволяет консультантам принимать дела, вести переписку с клиентами, загружать документы, а администраторам — контролировать качество и управлять процессами.

### Ключевые особенности

- **🔐 RBAC** — Ролевая модель доступа (Client, Consultant, Admin)
- **📋 Управление делами** — Полный цикл от создания до завершения
- **💬 Чат** — Коммуникация консультант-клиент
- **📄 Документы** — Загрузка, проверка старшим юристом, доставка клиенту
- **📧 Email доставка** — Защищённая отправка через Proton Mail (SMTP)
- **⚙️ Мастер-переключатели** — Гибкое управление workflow через админ-панель

---

## 🏗 Архитектура

```
legavex-platform/
├── apps/
│   ├── api/                    # FastAPI Backend
│   │   ├── main.py             # Точка входа
│   │   ├── config.py           # Конфигурация из .env
│   │   ├── dependencies.py     # Dependency Injection
│   │   ├── middleware/
│   │   │   └── rbac.py         # RBAC middleware
│   │   ├── routers/
│   │   │   ├── auth.py         # Аутентификация
│   │   │   ├── consultant.py   # API консультанта
│   │   │   └── admin.py        # API администратора
│   │   ├── services/
│   │   │   ├── case_service.py     # Бизнес-логика дел
│   │   │   ├── email_service.py    # Email сервис
│   │   │   └── audit_service.py    # Аудит-лог
│   │   ├── schemas/            # Pydantic v2 схемы
│   │   └── models/             # Prisma client
│   │
│   └── web/                    # Next.js Frontend (Этап 2)
│
├── infra/
│   ├── prisma/
│   │   └── schema.prisma       # Схема базы данных
│   └── docker/
│
├── docker-compose.yml          # Docker конфигурация
├── .env.example                # Пример переменных окружения
└── README.md
```

---

## 🗄 Схема базы данных

### Основные модели

| Модель | Описание |
|--------|----------|
| `User` | Пользователи (CLIENT, CONSULTANT, ADMIN) |
| `ConsultantProfile` | Профиль консультанта (специализация, регион, лимиты) |
| `Case` | Дело (заявка клиента) |
| `CaseAssignment` | Назначение консультанта на дело |
| `CaseMessage` | Сообщения в чате дела |
| `CaseDocument` | Документы по делу |
| `Payout` | Выплаты консультантам |
| `GlobalSettings` | Глобальные настройки (тоглы) |
| `EmailLog` | Лог отправленных email |
| `AuditLog` | Аудит действий пользователей |

### Статусы дел

```
NEW → WAITING_CONSULTANT → IN_PROGRESS → REVIEW → DONE
         ↓                      ↓           ↓
    ESCALATED              CANCELLED    (rejected → IN_PROGRESS)
```

---

## 🔌 API Endpoints

### Аутентификация (`/api/auth/`)

| Метод | Endpoint | Описание |
|-------|----------|----------|
| POST | `/login` | Вход по email/password, возвращает JWT |
| POST | `/register` | Регистрация (для тестов) |
| GET | `/me` | Текущий пользователь |

### Консультант (`/api/consultant/`)

| Метод | Endpoint | Описание |
|-------|----------|----------|
| GET | `/cases` | Список дел консультанта |
| GET | `/cases/{id}` | Детали дела |
| POST | `/cases/{id}/accept` | Принять дело |
| POST | `/cases/{id}/decline` | Отказаться от дела |
| GET | `/cases/{id}/messages` | История чата |
| POST | `/cases/{id}/messages` | Отправить сообщение |
| GET | `/cases/{id}/documents` | Список документов |
| POST | `/cases/{id}/documents` | Загрузить документ |
| POST | `/cases/{id}/documents/{doc_id}/submit` | Отправить документ |
| GET | `/payouts` | Список выплат |

### Администратор (`/api/admin/`)

| Метод | Endpoint | Описание |
|-------|----------|----------|
| GET | `/cases` | Все дела |
| GET | `/cases/{id}` | Детали дела |
| POST | `/cases/{id}/assign` | Назначить консультанта |
| POST | `/cases/{id}/documents/{doc_id}/approve` | Одобрить документ |
| POST | `/cases/{id}/documents/{doc_id}/reject` | Вернуть на правки |
| GET | `/payouts` | Все выплаты |
| GET | `/consultants` | Список консультантов |
| GET | `/settings` | Глобальные настройки |
| PATCH | `/settings` | Обновить настройки |

---

## ⚙️ Мастер-переключатели

### Toggle 1: `isReviewRequired`
**"Обязательная проверка перед отправкой"**

- `ON` → Документ уходит на проверку старшему юристу (статус `PENDING_REVIEW`)
- `OFF` → Документ сразу доставляется клиенту

### Toggle 2: `useEmailDelivery`
**"Доставка через защищённую почту"**

- `ON` → Документ отправляется клиенту по email (Proton Mail SMTP)
- `OFF` → Документ доступен в интерфейсе платформы

> 💡 Оба тогла могут работать одновременно: сначала проверка → потом отправка по почте

---

## 🚀 Быстрый старт

### Docker (рекомендуется)

```bash
# Клонировать репозиторий
git clone https://github.com/parafoto/legavex-platform.git
cd legavex-platform

# Скопировать и настроить переменные окружения
cp .env.example .env
# Отредактировать .env

# Запустить через Docker Compose
docker-compose up -d

# API доступен на http://localhost:8000
# Документация: http://localhost:8000/docs
```

### Локальная разработка

```bash
# 1. Установить зависимости
cd apps/api
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 2. Настроить Prisma
cd ../../infra/prisma
prisma generate
prisma db push  # Создать таблицы

# 3. Запустить сервер
cd ../../apps/api
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Переменные окружения

```env
# Database
DATABASE_URL=postgresql://user:password@localhost:5432/legavex_platform

# JWT
JWT_SECRET=your-secret-key-min-32-characters

# SMTP (Proton Mail)
SMTP_HOST=smtp.protonmail.ch
SMTP_PORT=587
SMTP_USER=legavex@proton.me
SMTP_PASSWORD=***
EMAIL_ENABLED=false

# Business
OFFER_TIMEOUT_HOURS=24
```

---

## 📧 Email интеграция

Email сервис поддерживает:
- **Proton Mail** — рекомендуемый вариант (через SMTP Bridge)
- **Любой SMTP** — настраивается через переменные окружения

### Текущий статус

🟡 **Заглушка** — Email логируется в `EmailLog`, но не отправляется реально.

Для активации реальной отправки:
1. Настроить SMTP в `.env`
2. Установить `EMAIL_ENABLED=true`
3. Раскомментировать код в `email_service.py`

---

## 🔒 Безопасность

- **JWT аутентификация** с истечением токенов
- **RBAC middleware** — проверка ролей на каждом эндпоинте
- **Audit Log** — логирование всех важных действий
- **Хеширование паролей** — bcrypt
- **CORS** — настраиваемый список разрешённых источников

---

## 📝 Планы на Этап 2

### Frontend (Next.js 14)

- [ ] Страница входа консультанта
- [ ] Дашборд с табами (Новые / В работе / Завершённые)
- [ ] Карточка дела с чатом и документами
- [ ] Админ-панель с тоглами
- [ ] Интеграция NextAuth.js

### Backend улучшения

- [ ] WebSocket для real-time чата
- [ ] Загрузка файлов (S3/MinIO)
- [ ] Celery для фоновых задач
- [ ] Уведомления (push, email)

---

## 🤝 Связь с Telegram ботом

LegaVex Advisor Portal работает совместно с Telegram ботом:
- **Бот:** [github.com/parafoto/DeepAgent](https://github.com/parafoto/DeepAgent)
- **Общая БД:** PostgreSQL (разные таблицы)
- **Интеграция:** Дела создаются через бот, обрабатываются в веб-портале

---

## 📄 Лицензия

MIT © LegaVex Team
